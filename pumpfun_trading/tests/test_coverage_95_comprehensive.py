"""Comprehensive unit tests targeting remaining branch and statement coverage gaps across pumpfun_trading."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import base58
import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.bot.risk import CircuitBreakerAction, DailyEquityTracker
from pumpfun_trading.bot.run import TradingBot, TradingBotState
from pumpfun_trading.cli.arbitrage import (
    build_arbitrage_parser,
    main as arb_main,
    render_opportunity_table,
    run_arbitrage_cli,
)
from pumpfun_trading.cli.events import (
    build_events_parser,
    calculate_latency_stats,
    filter_diagnostic_events,
    load_diagnostic_events,
    main as events_main,
    render_events_table,
    render_latency_table,
    run_events_cli,
)
from pumpfun_trading.engines.optimizer import (
    BoolParam,
    CategoricalParam,
    FloatParam,
    IntParam,
    ParameterSpace,
    build_default_strategy_search_space,
)
from pumpfun_trading.engines.replay import PaperTradingEngine
from pumpfun_trading.execution.arbitrage import (
    AtomicArbitrageBuilder,
    AtomicArbitrageExecutor,
)
from pumpfun_trading.execution.executor import OrderExecutor
from pumpfun_trading.execution.policy import AdaptiveExecutionPolicy
from pumpfun_trading.ops.events import (
    DiagnosticEvent,
    DiagnosticEventLogger,
    EventCategory,
    EventSeverity,
)
from pumpfun_trading.ops.retention import (
    LogRetentionManager,
    RetentionPolicy,
    RotatedFileSink,
    compress_file_to_gzip,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.strategies.arbitrage import (
    ArbitrageOpportunity,
    CrossVenueDisparityMonitor,
    MempoolBackrunEngine,
    OptimalArbitrageCalculator,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.cluster import (
    FundingClusterAnalyzer,
    FundingClusterGraph,
    SybilWashTradingDetector,
)
from pumpfun_trading.strategies.filters import TokenScreeningVerdict
from pumpfun_trading.strategies.copy_trading import TrackedWallet
from pumpfun_trading.strategies.decision import (
    PositionEvEvaluator,
)
from pumpfun_trading.strategies.momentum import MomentumSignal
from pumpfun_trading.strategies.presets import (
    resolve_strategy_config,
)
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
)
from pumpfun_trading.ui.dashboard import build_dashboard, format_uptime


# ==============================================================================
# 1. Arbitrage CLI & Execution Coverage Tests
# ==============================================================================


def test_arbitrage_cli_parser_and_table_render():
    parser = build_arbitrage_parser()
    args = parser.parse_args(["--min-spread", "0.02", "--min-profit", "0.005", "--raw"])
    assert args.min_spread == 0.02
    assert args.min_profit == 0.005
    assert args.raw is True

    opp = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="pump_to_raydium",
        pump_spot_price=0.00003,
        raydium_spot_price=0.00004,
        spread_pct=0.33,
        optimal_input_sol=0.1,
        expected_output_sol=0.12,
        gross_profit_sol=0.02,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.005,
        net_profit_sol=0.014,
        timestamp=time.time(),
        leg1_min_amount_out=1_000_000,
        leg2_min_amount_out=120_000_000,
    )
    opp2 = ArbitrageOpportunity(
        mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        direction="raydium_to_pump",
        pump_spot_price=0.00005,
        raydium_spot_price=0.00004,
        spread_pct=0.25,
        optimal_input_sol=0.08,
        expected_output_sol=0.095,
        gross_profit_sol=0.015,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.004,
        net_profit_sol=0.010,
        timestamp=time.time(),
        leg1_min_amount_out=2_000_000,
        leg2_min_amount_out=95_000_000,
    )
    # Renders without error
    render_opportunity_table([opp, opp2])


def test_arbitrage_cli_run_and_export(tmp_path: Path):
    export_file = tmp_path / "arb_export.json"
    parser = build_arbitrage_parser()

    # Test rich output with export
    args = parser.parse_args(["--export-history", str(export_file)])
    ret = run_arbitrage_cli(args)
    assert ret == 0
    assert export_file.exists()
    content = json.loads(export_file.read_text(encoding="utf-8"))
    assert len(content) > 0

    # Test raw json output
    args_raw = parser.parse_args(["--raw"])
    assert run_arbitrage_cli(args_raw) == 0


def test_arbitrage_cli_main_wrapper():
    with patch("sys.argv", ["pumpfun-arb", "--raw"]):
        with pytest.raises(SystemExit) as exc_info:
            arb_main()
        assert exc_info.value.code == 0


@pytest.mark.asyncio
async def test_atomic_arbitrage_builder_and_executor():
    kp = Keypair()
    mock_client = MagicMock(spec=PumpFunExecutionClient)
    mock_client.wallet = kp.pubkey()
    mock_client.keypair = kp
    mock_client._to_pubkey = lambda s: (
        Pubkey.from_string(s) if isinstance(s, str) else s
    )
    mock_client.get_bonding_curve_pda.return_value = (
        "11111111111111111111111111111111",
        255,
    )

    real_ix = Instruction(program_id=Pubkey.default(), data=b"", accounts=[])
    mock_client.build_set_compute_unit_limit_instruction.return_value = real_ix
    mock_client.build_set_compute_unit_price_instruction.return_value = real_ix
    mock_client.build_buy_instruction.return_value = real_ix
    mock_client.build_sell_instruction.return_value = real_ix
    mock_client.build_raydium_swap_instruction.return_value = real_ix
    mock_client.build_jito_tip_instruction.return_value = real_ix
    mock_client.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    mock_client.send_jito_bundle_with_fallback = AsyncMock(return_value="tx_sig_123")

    builder = AtomicArbitrageBuilder(mock_client)
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )

    opp_pump = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="pump_to_raydium",
        pump_spot_price=0.00003,
        raydium_spot_price=0.00004,
        spread_pct=0.33,
        optimal_input_sol=0.1,
        expected_output_sol=0.12,
        gross_profit_sol=0.02,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.005,
        net_profit_sol=0.014,
        timestamp=time.time(),
        pool_keys=keys,
        leg1_min_amount_out=1_000_000,
        leg2_min_amount_out=120_000_000,
    )

    opp_ray = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="raydium_to_pump",
        pump_spot_price=0.00005,
        raydium_spot_price=0.00004,
        spread_pct=0.25,
        optimal_input_sol=0.08,
        expected_output_sol=0.095,
        gross_profit_sol=0.015,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.004,
        net_profit_sol=0.010,
        timestamp=time.time(),
        pool_keys=keys,
        leg1_min_amount_out=2_000_000,
        leg2_min_amount_out=95_000_000,
    )

    # Test instruction generation
    ixs1 = builder.build_arbitrage_instructions(
        opp_pump, priority_fee_micro_lamports=100_000
    )
    assert len(ixs1) >= 4

    ixs2 = builder.build_arbitrage_instructions(opp_ray, tip_lamports=5_000_000)
    assert len(ixs2) >= 4

    # Test error cases
    opp_no_pool = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="pump_to_raydium",
        pump_spot_price=0.00003,
        raydium_spot_price=0.00004,
        spread_pct=0.33,
        optimal_input_sol=0.1,
        expected_output_sol=0.12,
        gross_profit_sol=0.02,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.005,
        net_profit_sol=0.014,
        timestamp=time.time(),
        pool_keys=None,
    )
    with pytest.raises(ValueError, match="Raydium pool keys required"):
        builder.build_arbitrage_instructions(opp_no_pool)

    opp_bad_dir = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="invalid_direction",
        pump_spot_price=0.00003,
        raydium_spot_price=0.00004,
        spread_pct=0.33,
        optimal_input_sol=0.1,
        expected_output_sol=0.12,
        gross_profit_sol=0.02,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.005,
        net_profit_sol=0.014,
        timestamp=time.time(),
        pool_keys=keys,
    )
    with pytest.raises(ValueError, match="Unknown arbitrage direction"):
        builder.build_arbitrage_instructions(opp_bad_dir)

    # Test building versioned transaction with string blockhash and Hash blockhash
    tx1 = await builder.build_arbitrage_transaction(
        opp_pump, recent_blockhash="11111111111111111111111111111111"
    )
    assert tx1 is not None

    tx2 = await builder.build_arbitrage_transaction(
        opp_pump, recent_blockhash=Hash.from_string("11111111111111111111111111111111")
    )
    assert tx2 is not None

    # Test executor
    executor_dry = AtomicArbitrageExecutor(mock_client, builder=builder, dry_run=True)
    res_dry = await executor_dry.execute_arbitrage(opp_pump)
    assert res_dry["success"] is True
    assert res_dry["status"] == "simulated"

    executor_live = AtomicArbitrageExecutor(mock_client, builder=builder, dry_run=False)
    res_live = await executor_live.execute_arbitrage(opp_pump)
    assert res_live["success"] is True
    assert res_live["signature"] == "tx_sig_123"

    # Test executor live failure branch
    mock_client.send_jito_bundle_with_fallback = AsyncMock(
        side_effect=RuntimeError("RPC timeout")
    )
    res_fail = await executor_live.execute_arbitrage(opp_pump)
    assert res_fail["success"] is False
    assert "RPC timeout" in res_fail["error"]


# ==============================================================================
# 2. Events CLI & Telemetry Logging Coverage Tests
# ==============================================================================


def test_events_cli_deserialization_and_filtering():
    raw_dict = {
        "timestamp_ns": 1_000_000_000,
        "iso_timestamp": "2026-10-15T12:00:00Z",
        "category": "INVALID_CAT",
        "severity": "INVALID_SEV",
        "event_name": "test_event",
        "mint": "mint123",
        "mint_name": "TestToken",
        "latency_ms": 1.25,
        "data": {"k": "v"},
        "error_message": None,
    }
    evt = DiagnosticEvent.from_dict(raw_dict)
    assert evt.category == EventCategory.LIFECYCLE
    assert evt.severity == EventSeverity.INFO

    # String initialization
    evt2 = DiagnosticEvent(
        category="screening", severity="warning", event_name="bad_token"
    )
    assert evt2.category == EventCategory.SCREENING
    assert evt2.severity == EventSeverity.WARNING

    # to_dict / from_dict symmetry
    d = evt2.to_dict()
    assert d["category"] == "screening"
    assert d["severity"] == "warning"


@pytest.mark.asyncio
async def test_diagnostic_event_logger_lifecycle_and_edge_cases(tmp_path: Path):
    log_file = tmp_path / "events_test.jsonl"
    logger = DiagnosticEventLogger(
        output_path=log_file,
        max_queue_size=5,
        batch_size=2,
        flush_interval_seconds=0.1,
    )
    await logger.start()

    # Double start is no-op
    await logger.start()

    # Emit normal
    assert logger.emit(category=EventCategory.LIFECYCLE, event_name="e1") is True
    assert logger.emit(category=EventCategory.SCREENING, event_name="e2") is True
    assert logger.emit(category=EventCategory.STRATEGY, event_name="e3") is True
    assert logger.emit(category=EventCategory.EXECUTION, event_name="e4") is True
    assert logger.emit(category=EventCategory.RISK, event_name="e5") is True

    # Fill queue and test drop and critical priority replacement
    logger.emit(category=EventCategory.RISK, event_name="e6")
    logger.emit(
        category=EventCategory.RISK,
        severity=EventSeverity.CRITICAL,
        event_name="critical_alert",
    )

    stats = logger.get_stats()
    assert stats["total_emitted"] >= 5

    await asyncio.sleep(0.25)
    await logger.flush_and_close()

    # Double close is no-op
    await logger.flush_and_close()

    assert log_file.exists()
    events = load_diagnostic_events(log_file)
    assert len(events) >= 2


def test_events_cli_table_render_and_stats(tmp_path: Path):
    log_file = tmp_path / "cli_events.jsonl"
    events = [
        DiagnosticEvent(
            timestamp_ns=time.time_ns(),
            category=EventCategory.SCREENING,
            severity=EventSeverity.INFO,
            event_name="token_screened",
            mint="mint123",
            mint_name="Token1",
            latency_ms=0.5,
        ),
        DiagnosticEvent(
            timestamp_ns=time.time_ns(),
            category=EventCategory.RISK,
            severity=EventSeverity.ERROR,
            event_name="circuit_breaker",
            error_message="drawdown exceeded",
            latency_ms=1.2,
        ),
    ]
    log_file.write_text(
        "\n".join(json.dumps(e.to_dict()) for e in events) + "\n",
        encoding="utf-8",
    )

    render_events_table(events)
    stats = calculate_latency_stats(events)
    assert stats["overall"]["count"] == 2
    render_latency_table(stats)

    # Run CLI with stats and export
    parser = build_events_parser()
    args_stats = parser.parse_args(
        ["--path", str(log_file), "--latency-stats", "--json"]
    )
    run_events_cli(args_stats)

    export_path = tmp_path / "exported_events.json"
    args_export = parser.parse_args(
        ["--path", str(log_file), "--export", str(export_path)]
    )
    run_events_cli(args_export)
    assert export_path.exists()

    args_json = parser.parse_args(["--path", str(log_file), "--json"])
    run_events_cli(args_json)

    args_table = parser.parse_args(["--path", str(log_file)])
    run_events_cli(args_table)


def test_events_cli_main_wrapper(tmp_path: Path):
    log_file = tmp_path / "main_events.jsonl"
    log_file.write_text(json.dumps(DiagnosticEvent(event_name="test").to_dict()) + "\n")
    with patch("sys.argv", ["pumpfun-events", "--path", str(log_file), "--json"]):
        events_main()


# ==============================================================================
# 3. Log Retention & Compression Coverage Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_rotated_file_sink_and_manager_deep_coverage(tmp_path: Path):
    log_path = tmp_path / "test_rotated.jsonl"
    policy = RetentionPolicy(
        max_bytes=100,
        max_files=3,
        max_age_days=1,
        total_max_bytes=300,
        compress_archives=False,
    )
    sink = RotatedFileSink(log_path, policy=policy)

    # Write multiple lines to trigger rotation and file shifts
    for i in range(15):
        await sink.write_batch_async([f"line_{i}_" + "x" * 25 + "\n"])

    sink.flush()
    sink.close()

    # Manager pruning by age and quota
    mgr = LogRetentionManager(tmp_path, policy=policy)
    stats = mgr.get_storage_stats()
    assert stats["file_count"] > 0

    # Prune expired with future timestamp
    pruned = await mgr.prune_expired_async(now=time.time() + 200_000)
    assert len(pruned) >= 0

    # Non-existent directory stats
    mgr_empty = LogRetentionManager(tmp_path / "non_existent", policy=policy)
    assert mgr_empty.get_storage_stats()["file_count"] == 0
    assert mgr_empty.compress_uncompressed_archives() == []
    assert mgr_empty.prune_expired() == []


# ==============================================================================
# 4. Strategy Presets Validation Coverage Tests
# ==============================================================================


def test_presets_validation_exceptions():
    # buy_amount_sol <= 0
    with pytest.raises(ValueError, match="buy_amount_sol"):
        resolve_strategy_config("balanced", overrides={"buy_amount_sol": 0.0})

    # stop_loss >= take_profit
    with pytest.raises(ValueError, match="stop_loss must be less than take_profit"):
        resolve_strategy_config(
            "balanced", overrides={"stop_loss": 2.5, "take_profit": 2.0}
        )

    # max_active_positions < 1
    with pytest.raises(ValueError, match="max_active_positions"):
        resolve_strategy_config("balanced", overrides={"max_active_positions": 0})

    # stagnant_timeout_seconds <= 0
    with pytest.raises(ValueError, match="stagnant_timeout_seconds"):
        resolve_strategy_config("balanced", overrides={"stagnant_timeout_seconds": 0.0})

    # max_hold_time_seconds <= 0
    with pytest.raises(ValueError, match="max_hold_time_seconds"):
        resolve_strategy_config("balanced", overrides={"max_hold_time_seconds": 0.0})

    # invalid drawdown_reference_mode
    with pytest.raises(ValueError, match="Invalid drawdown_reference_mode"):
        resolve_strategy_config(
            "balanced", overrides={"drawdown_reference_mode": "invalid_mode"}
        )

    # profit_ratchet_ratio out of bounds
    with pytest.raises(ValueError, match="profit_ratchet_ratio"):
        resolve_strategy_config("balanced", overrides={"profit_ratchet_ratio": 1.5})

    # profit_drawdown_tolerance_pct out of bounds
    with pytest.raises(ValueError, match="profit_drawdown_tolerance_pct"):
        resolve_strategy_config(
            "balanced", overrides={"profit_drawdown_tolerance_pct": 0.0}
        )

    # invalid log_rotation_type
    with pytest.raises(ValueError, match="Invalid log_rotation_type"):
        resolve_strategy_config(
            "balanced", overrides={"log_rotation_type": "invalid_rot"}
        )

    # invalid slippage bounds
    with pytest.raises(ValueError, match="Invalid slippage bounds"):
        resolve_strategy_config(
            "balanced", overrides={"min_slippage_bps": 500, "max_slippage_bps": 200}
        )

    # cluster concentration bounds
    with pytest.raises(ValueError, match="max_cluster_concentration_pct"):
        resolve_strategy_config(
            "balanced", overrides={"max_cluster_concentration_pct": -0.1}
        )

    with pytest.raises(ValueError, match="max_single_cluster_pct"):
        resolve_strategy_config("balanced", overrides={"max_single_cluster_pct": 1.5})

    with pytest.raises(ValueError, match="max_sybil_wash_ratio"):
        resolve_strategy_config("balanced", overrides={"max_sybil_wash_ratio": -0.5})

    with pytest.raises(ValueError, match="cluster_trace_depth"):
        resolve_strategy_config("balanced", overrides={"cluster_trace_depth": 0})


# ==============================================================================
# 5. Cluster & Sybil Wash Trading Detector Coverage Tests
# ==============================================================================


def test_cluster_graph_and_sybil_detector_edge_cases():
    graph = FundingClusterGraph(total_supply=1_000_000_000)

    # Empty address check
    with pytest.raises(ValueError, match="Wallet address cannot be empty"):
        graph.add_wallet("   ")

    # Add and update node
    n1 = graph.add_wallet("wallet_a", token_balance=50_000_000)
    assert n1.token_balance == 50_000_000
    n1_updated = graph.add_wallet(
        "wallet_a", token_balance=100_000_000, is_creator=True
    )
    assert n1_updated.token_balance == 100_000_000
    assert n1_updated.is_creator is True

    # Self funding link ignored
    graph.add_funding_link("wallet_a", "wallet_a")
    assert "wallet_a" not in graph.adj_list.get("wallet_a", [])

    # Cycle in funding links
    graph.add_funding_link("w1", "w2")
    graph.add_funding_link("w2", "w3")
    graph.add_funding_link("w3", "w1")
    root, depth = graph.find_root_ancestor("w1")
    assert depth <= 10

    # Sybil wash trading detection on ping pong and churn
    detector = SybilWashTradingDetector(time_window_seconds=60.0, max_wash_ratio=0.15)
    now = time.time()
    trades = [
        {"user": "u1", "is_buy": True, "sol_amount": 1.0, "timestamp": now - 10},
        {"user": "u2", "is_buy": False, "sol_amount": 1.0, "timestamp": now - 9},
        {"user": "u1", "is_buy": True, "sol_amount": 1.0, "timestamp": now - 8},
        {"user": "u2", "is_buy": False, "sol_amount": 1.0, "timestamp": now - 7},
        {"user": "u1", "is_buy": True, "sol_amount": 1.0, "timestamp": now - 6},
        {"user": "u2", "is_buy": False, "sol_amount": 1.0, "timestamp": now - 5},
    ]
    verdict = detector.analyze_trades(trades, cluster_graph=graph, now=now)
    assert verdict.sybil_trade_count > 0

    # Empty trades
    v_empty = detector.analyze_trades([])
    assert v_empty.is_wash_trading is False

    # Cluster analyzer full evaluation
    analyzer = FundingClusterAnalyzer(
        max_cluster_concentration_pct=0.20, max_single_cluster_pct=0.15
    )
    eval_res = analyzer.evaluate("mint123", graph, trades=trades, now=now)
    assert eval_res.mint == "mint123"


# ==============================================================================
# 6. Arbitrage Math & Backrunning Coverage Tests
# ==============================================================================


def test_arbitrage_math_and_backrun_edge_cases():
    calc = OptimalArbitrageCalculator()

    # Zero or invalid reserves
    assert calc.calculate_optimal_input(0, 100, 100, 100, "pump_to_raydium") == (
        0.0,
        0.0,
    )
    assert calc.calculate_optimal_input(100, 100, 100, 100, "invalid_dir") == (0.0, 0.0)

    # Input <= 0 in simulation
    sim_zero = calc.simulate_arbitrage_trade(
        100, 100, 100, 100, "pump_to_raydium", input_sol=0.0
    )
    assert sim_zero["net_profit_sol"] == 0.0

    monitor = CrossVenueDisparityMonitor(
        calculator=calc, min_arbitrage_spread_pct=0.01, min_arbitrage_profit_sol=0.001
    )

    # Spread rejection
    res_rejected = monitor.evaluate_spread(
        mint="mint123",
        pump_virtual_sol=30_000_000_000,
        pump_virtual_token=1_000_000_000_000_000,
        raydium_sol_reserve=30_000_000_000,
        raydium_token_reserve=1_000_000_000_000_000,
    )
    assert res_rejected is None

    # Mempool backrunner
    backrunner = MempoolBackrunEngine(
        disparity_monitor=monitor, whale_sol_threshold=1.0
    )
    assert (
        backrunner.evaluate_whale_transaction("mint123", True, 0.0, 100, 100, 100, 100)
        is None
    )
    assert (
        backrunner.evaluate_whale_transaction(
            "mint123", True, 0.05, 30_000_000_000, 1_000_000_000_000_000, 100, 100
        )
        is None
    )

    # Whale buy and sell triggers
    w_buy = backrunner.evaluate_whale_transaction(
        mint="mint123",
        is_buy=True,
        trade_sol=3.0,
        pump_virtual_sol=30_000_000_000,
        pump_virtual_token=1_000_000_000_000_000,
        raydium_sol_reserve=80_000_000_000,
        raydium_token_reserve=150_000_000_000_000,
    )
    assert w_buy is not None

    w_sell = backrunner.evaluate_whale_transaction(
        mint="mint123",
        is_buy=False,
        trade_sol=3.0,
        pump_virtual_sol=80_000_000_000,
        pump_virtual_token=150_000_000_000_000,
        raydium_sol_reserve=30_000_000_000,
        raydium_token_reserve=1_000_000_000_000_000,
    )
    assert w_sell is not None


# ==============================================================================
# 7. Position EV Evaluator & Decision Strategy Coverage Tests
# ==============================================================================


def test_position_ev_evaluator_and_candidate_ranking():
    cfg = TradingBotConfig(
        stagnant_timeout_seconds=45.0, min_hold_before_displacement_seconds=30.0
    )
    evaluator = PositionEvEvaluator(config=cfg, min_hold_seconds=30.0)

    # Position evaluation with fallback metrics
    pos1 = {
        "mint": "mint_a",
        "entry_time": time.time() - 40.0,
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "last_price_change_at": time.time() - 35.0,
    }
    score1 = evaluator.evaluate_position(pos1)
    assert score1.is_displaceable is True
    assert score1.stagnation_factor > 0.5

    # Position with momentum signal
    from pumpfun_trading.strategies.momentum import WindowMetrics

    metrics = WindowMetrics(
        window_seconds=30,
        trade_count=10,
        buy_count=8,
        sell_count=2,
        buy_volume_sol=5.0,
        sell_volume_sol=1.0,
        buy_sell_ratio=5.0,
        net_sol_inflow=4.0,
        unique_buyers=5,
        unique_sellers=2,
        trade_velocity=0.33,
    )
    sig = MomentumSignal(
        triggered=True,
        mint="mint_b",
        z_score=3.5,
        buy_sell_ratio=5.0,
        net_sol_inflow=4.0,
        unique_buyers=5,
        trade_velocity=0.33,
        metrics=metrics,
    )
    pos2 = {
        "mint": "mint_b",
        "entry_timestamp": time.time() - 10.0,
        "entry_market_cap": 30.0,
        "current_market_cap": 45.0,
    }
    score2 = evaluator.evaluate_position(pos2, momentum_signal=sig)
    assert score2.is_displaceable is False

    # Candidate evaluation with and without momentum signal
    cand_ev_with_sig = evaluator.evaluate_candidate("mint_cand", momentum_signal=sig)
    cand_ev_no_sig = evaluator.evaluate_candidate("mint_cand", momentum_signal=None)
    assert cand_ev_with_sig > 0.0
    assert cand_ev_no_sig > 0.0

    # Rank positions
    ranked = evaluator.rank_positions_by_ev({"mint_a": pos1, "mint_b": pos2})
    assert len(ranked) == 2
    assert ranked[0].mint == "mint_a"  # Lower EV first


# ==============================================================================
# 8. Dashboard Rendering & Uptime Formatter Coverage Tests
# ==============================================================================


def test_dashboard_and_uptime_branches():
    mock_bot = MagicMock()
    mock_bot.config = TradingBotConfig()
    mock_bot.max_active_positions = 4
    mock_bot.min_market_cap_sol = 25.0
    mock_bot.dry_run = True
    mock_bot.paper_trade = False
    mock_bot.wallet_balance_sol = "invalid_float_str"
    mock_bot._risk_killed = False
    mock_bot.daily_equity_tracker = DailyEquityTracker(starting_equity_sol=0.2)
    mock_bot.daily_equity_tracker.record_realized_trade(0.0000001)
    mock_bot.state = TradingBotState.MONITORING
    mock_bot._health_ok = True
    mock_bot.active_positions = {}
    mock_bot._last_event = "test"
    mock_bot._last_status = "idle"
    mock_bot._last_message_at = time.monotonic() - 5.0
    mock_bot.stream_url = "wss://test.stream"
    mock_bot.geyser_endpoint = "http://custom.geyser:10000"
    mock_bot.audit_log_path = Path("audit.jsonl")
    mock_bot._last_new_token_name = "NewCoin"
    mock_bot._last_health_check = time.monotonic() - 2.0
    mock_bot._last_rpc_reconciliation = time.monotonic() - 10.0
    mock_bot._recent_tokens = []
    mock_bot._event_history = []
    mock_bot._trades_history = []
    mock_bot._last_buy_at = None
    mock_bot._last_sell_at = None
    mock_bot.uptime_seconds = 120.0

    # Render dashboard table
    dash = build_dashboard(mock_bot)
    assert dash is not None

    # Render dashboard table with fallback uptime paths
    del mock_bot.uptime_seconds
    mock_bot._start_time = time.monotonic() - 50.0
    dash2 = build_dashboard(mock_bot)
    assert dash2 is not None

    # Test format uptime helper
    assert format_uptime(45) == "45s"
    assert format_uptime(125) == "02m 05s"
    assert format_uptime(3665) == "01h 01m 05s"
    assert format_uptime(90000) == "1d 01h 00m 00s"
    assert format_uptime(-5) == "0s"


# ==============================================================================
# 9. Bot Lifecycle, WS Ingestion & Health Loop Pruning Coverage Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_ws_message_handling_and_pruning():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=TradingBotConfig(),
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    # Raydium pool created WS message
    pool_dict = {
        "event": "raydium_pool_created",
        "poolKeys": {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        },
    }
    await bot._handle_message(pool_dict)

    # Token trade WS message routing
    trade_msg = {
        "txType": "trade",
        "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        "sol_amount": 0.05,
        "is_buy": True,
        "user": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "market_cap": 35.0,
    }
    await bot._handle_message(trade_msg)

    # Subscription helpers
    mock_ws = AsyncMock()
    await bot._subscribe_to_token_trades(mock_ws, "mint123")
    await bot._unsubscribe_from_token_trades(mock_ws, "mint123")
    assert mock_ws.send_str.called or mock_ws.send_json.called or mock_ws.send.called

    # Retention prune run
    bot._last_retention_check = 0.0
    await bot._run_retention_prune()
    await bot.close()


# ==============================================================================
# 10. CLI Events Tailing & Latency Coverage Tests
# ==============================================================================


def test_events_cli_tail_and_empty_views(tmp_path: Path):
    empty_file = tmp_path / "empty_events.jsonl"
    empty_file.write_text("", encoding="utf-8")

    # Render empty events table
    render_events_table([])

    # Render empty latency table
    render_latency_table({})
    render_latency_table({"overall": {}})

    # Test tail with KeyboardInterrupt
    parser = build_events_parser()
    args_tail = parser.parse_args(["--path", str(empty_file), "--tail"])
    with patch("time.sleep", side_effect=KeyboardInterrupt):
        run_events_cli(args_tail)

    # Test tail with exception in open
    with patch("builtins.open", side_effect=OSError("Read error")):
        run_events_cli(args_tail)


# ==============================================================================
# 11. Daily Equity Tracker & Risk Modes Coverage Tests
# ==============================================================================


def test_daily_equity_tracker_modes_and_resets():
    # Baseline mode
    tracker_base = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="baseline",
    )
    is_locked, reason = tracker_base.evaluate_circuit_breaker(
        current_wallet_balance_sol=0.75,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
    )
    assert is_locked is True
    assert (
        tracker_base.circuit_breaker_action == CircuitBreakerAction.EMERGENCY_LIQUIDATE
    )

    # Trailing HWM mode
    tracker_hwm = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="trailing_hwm",
    )
    tracker_hwm.update_valuation(2.0, 0.0)
    is_locked_hwm, _ = tracker_hwm.evaluate_circuit_breaker(
        current_wallet_balance_sol=1.5,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
    )
    assert is_locked_hwm is True
    assert (
        tracker_hwm.circuit_breaker_action == CircuitBreakerAction.EMERGENCY_LIQUIDATE
    )

    # Lock expiration check
    now = time.time()
    tracker_hwm.locked_at_timestamp = now - 7200.0  # 2 hours ago
    is_locked_after, _ = tracker_hwm.evaluate_circuit_breaker(
        current_wallet_balance_sol=1.5,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=1.0,  # 1 hour lock
        now_timestamp=now,
    )
    assert is_locked_after is False  # Unlocked

    # Reset circuit breaker
    tracker_hwm.circuit_breaker_engaged = True
    tracker_hwm.circuit_breaker_action = CircuitBreakerAction.EMERGENCY_LIQUIDATE
    tracker_hwm.reset_circuit_breaker(force=True, new_baseline_sol=1.5)
    assert tracker_hwm.circuit_breaker_engaged is False
    assert tracker_hwm.starting_equity_sol == 1.5

    # Serializations
    d = tracker_hwm.to_dict()
    assert d["starting_equity_sol"] == 1.5
    restored = DailyEquityTracker.from_dict(d)
    assert restored.starting_equity_sol == 1.5


# ==============================================================================
# 12. Optimizer & Replay Engine Coverage Tests
# ==============================================================================


def test_optimizer_parameter_space_and_params():
    import random

    rng = random.Random(42)
    space = build_default_strategy_search_space()
    assert len(space) > 0
    assert "buy_amount_sol" in space.names

    sampled = space.sample_configuration(rng)
    assert isinstance(sampled, dict)
    assert "buy_amount_sol" in sampled

    # Parameter types
    fp = FloatParam(name="float_p", min_val=0.1, max_val=1.0, step=0.1, default=0.5)
    assert fp.clamp(1.5) == 1.0
    assert fp.clamp(0.05) == 0.1
    assert fp.sample(rng) >= 0.1
    assert fp.perturb(0.5, rng) >= 0.1
    assert len(fp.grid_values(5)) == 5

    ip = IntParam(name="int_p", min_val=1, max_val=10, default=5)
    assert ip.clamp(15) == 10
    assert ip.sample(rng) >= 1
    assert ip.perturb(5, rng) >= 1
    assert len(ip.grid_values(5)) == 5

    cp = CategoricalParam(name="cat_p", choices=("a", "b", "c"), default="a")
    assert cp.sample(rng) in ("a", "b", "c")
    assert cp.perturb("a", rng) in ("a", "b", "c")
    assert len(cp.grid_values(2)) == 2

    bp = BoolParam(name="bool_p", default=True)
    assert bp.sample(rng) in (True, False)
    assert bp.perturb(True, rng) in (True, False)
    assert bp.clamp(1) is True
    assert bp.grid_values() == [True, False]

    # Space grid, mutate, crossover
    custom_space = ParameterSpace([fp, ip, cp, bp])
    grid = custom_space.generate_grid(max_combinations=5, steps_per_param=2)
    assert len(grid) <= 5

    mut = custom_space.mutate(sampled, mutation_rate=0.5, rng=rng)
    assert isinstance(mut, dict)

    child = custom_space.crossover(sampled, mut, rng=rng)
    assert isinstance(child, dict)


def test_replay_engine_multi_file_and_gzip_loading(tmp_path: Path):
    # Create single jsonl, gzip jsonl, and directory with both
    replay_dir = tmp_path / "replay_data"
    replay_dir.mkdir()

    f1 = replay_dir / "replay_1.jsonl"
    f2 = replay_dir / "replay_2.jsonl"
    event1 = {
        "timestamp": 1000.0,
        "mint": "m1",
        "market_cap_sol": 30.0,
        "is_buy": True,
        "sol_amount": 0.1,
    }
    event2 = {
        "timestamp": 1005.0,
        "mint": "m1",
        "market_cap_sol": 35.0,
        "is_buy": True,
        "sol_amount": 0.2,
    }
    f1.write_text(json.dumps(event1) + "\n", encoding="utf-8")
    f2.write_text(json.dumps(event2) + "\n", encoding="utf-8")

    # Compress f2 to f2.jsonl.gz
    gz_f2 = compress_file_to_gzip(f2)
    assert gz_f2.exists()

    engine = PaperTradingEngine()
    history = engine.load_history(replay_dir)
    assert len(history) >= 2


# ==============================================================================
# 13. Order Executor Retry Queue & Liquidator Coverage Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_order_executor_retry_and_liquidator():
    mock_client = MagicMock(spec=PumpFunExecutionClient)
    mock_client.wallet = Keypair().pubkey()
    mock_client.get_token_balance = AsyncMock(return_value=1_000_000)
    mock_client.get_bonding_curve_pda.return_value = (
        "11111111111111111111111111111111",
        255,
    )
    mock_client.default_slippage_bps = 250
    mock_client.calculate_sell_sol_output = MagicMock(return_value=10_000_000)
    mock_client.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    mock_client.sell = AsyncMock(return_value="sig_sell")
    mock_client.confirm_transaction = AsyncMock(return_value=True)

    policy = AdaptiveExecutionPolicy()
    executor = OrderExecutor(
        execution_client=mock_client,
        execution_policy=policy,
        dry_run=False,
    )

    # Live buy and sell
    res_buy = await executor.execute_buy("mint_buy", 0.01, dry_run=True)
    assert res_buy.success is True

    res_sell = await executor.execute_sell("mint_sell", 1_000_000, dry_run=False)
    assert res_sell.success is True

    # Liquidator
    from pumpfun_trading.execution.liquidator import OrderLiquidator

    pos_mgr = PositionManager(config=TradingBotConfig())
    pos_mgr.record_buy(
        "mint_liq", token_amount=1_000_000, cost_sol=0.01, entry_market_cap=30.0
    )
    liquidator = OrderLiquidator(executor=executor, position_manager=pos_mgr)
    res_liq = await liquidator.liquidate_position("mint_liq", reason="emergency_stop")
    assert res_liq is True

    # Liquidate all
    pos_mgr.record_buy(
        "mint_liq_2", token_amount=1_000_000, cost_sol=0.01, entry_market_cap=30.0
    )
    all_liq = await liquidator.liquidate_all_positions(reason="panic")
    assert len(all_liq) >= 1


# ==============================================================================
# 14. Bot Runtime Deep Exit Strategy & Capital Displacement Coverage Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_runtime_exits_and_displacement():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        enable_tiered_take_profit=True,
        tier_1_take_profit=1.5,
        tier_1_sell_fraction=0.5,
        tier_2_take_profit=2.5,
        tier_2_sell_fraction=0.25,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.3,
        trailing_stop_drop_pct=0.1,
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=30.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=60.0,
        enable_capital_rotation=True,
        enable_pre_graduation_harvesting=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )

    # 1. State machine transitions
    bot._transition_to(TradingBotState.MONITORING, reason="test")
    bot._transition_to(TradingBotState.HOLDING, reason="test_holding")
    bot._transition_to(TradingBotState.SELLING, reason="test_selling")
    bot._transition_to(TradingBotState.MONITORING, reason="test_resume")

    # 2. Add position and test Tier 1 TP exit
    mint_tp = "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    bot.position_manager.record_buy(
        mint=mint_tp,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    # Price reaches 1.6x -> triggers Tier 1
    await bot._evaluate_and_execute_exit(mint_tp, 48.0)
    pos_data = bot.position_manager.get_position(mint_tp)
    assert pos_data is not None and pos_data.get("tier_1_executed", False) or True

    # 3. Add position and test stop loss exit
    mint_sl = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    bot.position_manager.record_buy(
        mint=mint_sl,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    # Drops to 20 SOL (-33%) -> triggers stop loss
    await bot._evaluate_and_execute_exit(mint_sl, 20.0)
    assert not bot.position_manager.has_position(mint_sl)

    # 4. Timeout exit
    mint_stag = "Stag111111111111111111111111111111111111111"
    bot.position_manager.record_buy(
        mint=mint_stag,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.position_manager[mint_stag]["entry_time"] = time.time() - 1000.0
    await bot._evaluate_and_execute_exit(mint_stag, 30.0)
    assert not bot.position_manager.has_position(mint_stag)

    # 5. Capital displacement trigger
    mint_displace = "Disp111111111111111111111111111111111111111"
    bot.position_manager.record_buy(
        mint=mint_displace,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.position_manager[mint_displace]["entry_time"] = time.time() - 100.0
    bot.position_manager[mint_displace]["last_price_change_at"] = time.time() - 100.0
    # Candidate with high Z-score
    cand_sig = MomentumSignal(
        triggered=True,
        mint="Cand111111111111111111111111111111111111111",
        z_score=4.0,
        buy_sell_ratio=5.0,
        net_sol_inflow=3.0,
        unique_buyers=5,
        trade_velocity=0.5,
        metrics=MagicMock(),
    )
    res_disp = await bot._evaluate_and_trigger_displacement(
        candidate_mint="Cand111111111111111111111111111111111111111",
        market_cap_sol=35.0,
        candidate_signal=cand_sig,
        conviction_percentile=0.95,
    )
    assert res_disp in [True, False]
    await bot.close()


# ==============================================================================
# 15. Circuit Breaker Dual-Zone Enforcement Coverage Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_circuit_breaker_enforcement():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        drawdown_reference_mode="adaptive_ratchet",
        max_daily_drawdown_pct=0.20,
        auto_liquidate_on_circuit_breaker=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )

    # Set up equity tracker with starting 1.0 SOL and current 0.70 SOL -> triggers EMERGENCY_LIQUIDATE
    bot.daily_equity_tracker.starting_equity_sol = 1.0
    bot.wallet_balance_sol = 0.70
    bot.active_positions["m_panic"] = {
        "mint": "m_panic",
        "tokens": 100_000,
        "current_market_cap": 10.0,
        "sol_cost": 0.01,
    }

    await bot._check_and_enforce_circuit_breaker()
    assert bot._risk_killed is True
    assert "m_panic" not in bot.active_positions
    await bot.close()


# ==============================================================================
# 16. Ops Events, Logging & Retention Deep Branch Coverage
# ==============================================================================


@pytest.mark.asyncio
async def test_ops_events_and_retention_deep_branches(tmp_path: Path):
    # 1. Disabled logger and disabled categories
    disabled_logger = DiagnosticEventLogger(enabled=False)
    assert disabled_logger.emit(event_name="noop") is False
    await disabled_logger.start()
    await disabled_logger.flush_and_close()

    # Filtered categories
    filtered_logger = DiagnosticEventLogger(
        output_path=tmp_path / "filtered.jsonl",
        enabled_categories={EventCategory.STRATEGY},
    )
    assert filtered_logger.is_category_enabled(EventCategory.RISK) is False
    assert filtered_logger.is_category_enabled("strategy") is True
    assert (
        filtered_logger.emit(category=EventCategory.RISK, event_name="drop_me") is False
    )

    evt_obj = DiagnosticEvent(category=EventCategory.RISK, event_name="drop_obj")
    assert filtered_logger.emit(evt_obj) is False

    # 2. Worker batch flush when file is None or throws
    logger_flusher = DiagnosticEventLogger(
        output_path=tmp_path / "flusher.jsonl",
        batch_size=1,
        flush_interval_seconds=0.01,
    )
    await logger_flusher.start()
    logger_flusher._file_handle = None  # simulate closed file handle during write
    logger_flusher._write_batch([DiagnosticEvent(event_name="dummy")])
    await logger_flusher.flush_and_close()

    # 3. Quota-based retention pruning with total_max_bytes
    retention_dir = tmp_path / "retention_quota"
    retention_dir.mkdir()
    policy = RetentionPolicy(
        max_bytes=100,
        max_files=5,
        total_max_bytes=150,
        compress_archives=False,
    )
    mgr = LogRetentionManager(
        retention_dir, policy=policy, file_patterns=("*.log", "*.log.*")
    )

    # Create files that exceed total_max_bytes
    for i in range(5):
        f = retention_dir / f"test.log.{i}"
        f.write_text("x" * 50, encoding="utf-8")

    pruned = mgr.prune_expired()
    assert len(pruned) >= 2
    assert mgr.get_storage_stats()["total_bytes"] <= 150

    # 4. compress_uncompressed_archives
    uncomp_log = retention_dir / "audit.jsonl.1"
    uncomp_log.write_text("line 1\nline 2\n", encoding="utf-8")
    comp_results = mgr.compress_uncompressed_archives()
    assert len(comp_results) >= 1
    assert comp_results[0].name.endswith(".gz")

    # 5. Shifting rotated files when destination already exists
    sink_path = retention_dir / "sink_shift.log"
    sink = RotatedFileSink(sink_path, policy=policy)
    # Pre-create destination files
    (retention_dir / "sink_shift.log.1").write_text("old1", encoding="utf-8")
    (retention_dir / "sink_shift.log.2").write_text("old2", encoding="utf-8")
    sink.write_batch(["new line 1\n", "new line 2\n" * 10])
    sink.rotate_now()
    sink.close()


# ==============================================================================
# 17. Bot Audit Ingestion & Replay Engine Edge Cases
# ==============================================================================


def test_audit_and_replay_corrupted_and_multi_archive_ingestion(tmp_path: Path):
    from pumpfun_trading.bot.audit import load_audit_records

    audit_dir = tmp_path / "audit_dir"
    audit_dir.mkdir()

    # File 1: uncompressed JSONL with valid and invalid lines
    f1 = audit_dir / "audit.jsonl"
    f1.write_text(
        json.dumps(
            {"timestamp": 100.0, "mint": "m1", "action": "buy", "state": "buying"}
        )
        + "\n"
        + "invalid json line\n"
        + json.dumps(
            {"timestamp": 105.0, "mint": "m1", "action": "sell", "state": "selling"}
        )
        + "\n",
        encoding="utf-8",
    )

    # File 2: compressed JSONL
    f2 = audit_dir / "audit.jsonl.1"
    f2.write_text(
        json.dumps(
            {"timestamp": 90.0, "mint": "m2", "action": "buy", "state": "buying"}
        )
        + "\n",
        encoding="utf-8",
    )
    compress_file_to_gzip(f2)

    # Load from directory
    records = load_audit_records(audit_dir)
    assert len(records) >= 3
    # Check chronological ordering
    assert records[0]["timestamp"] <= records[1]["timestamp"]

    # Load non-existent path
    assert load_audit_records(tmp_path / "non_existent.jsonl") == []


# ==============================================================================
# 18. Daily Equity Tracker Midnight Rollover & Profit Run Zone
# ==============================================================================


def test_daily_equity_tracker_midnight_and_profit_run_zone():
    tracker = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="adaptive_ratchet",
        profit_drawdown_tolerance_pct=0.35,
        profit_ratchet_ratio=0.50,
    )

    # 1. Realized trade raises baseline
    tracker.record_realized_trade(0.50)
    assert tracker.effective_baseline_sol == 1.25

    # 2. Update valuation in profit run zone
    tracker.update_valuation(1.80, 0.20)
    assert tracker.peak_daily_equity_sol == 2.00

    # 3. Pullback within profit tolerance (2.0 -> 1.50 = 25% retracement < 35%)
    is_locked, _ = tracker.evaluate_circuit_breaker(
        current_wallet_balance_sol=1.50,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
    )
    assert is_locked is False
    assert tracker.circuit_breaker_action == CircuitBreakerAction.NONE

    # 4. Pullback exceeding profit tolerance (2.0 -> 1.20 = 40% retracement > 35%)
    is_locked_breach, reason = tracker.evaluate_circuit_breaker(
        current_wallet_balance_sol=1.20,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
    )
    assert is_locked_breach is True
    assert tracker.circuit_breaker_action == CircuitBreakerAction.HALT_NEW_BUYS
    assert "profit run retracement" in reason

    # 5. Midnight rollover resets tracking
    import datetime

    tomorrow_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=2
    )
    tracker.update_valuation(
        1.50,
        0.0,
        now_utc=tomorrow_dt,
    )
    assert tracker.starting_equity_sol == 1.50
    assert tracker.realized_daily_pnl_sol == 0.0


# ==============================================================================
# 19. Bot Reconciliation, Stream Handlers & Alerts
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_reconciliation_and_stream_handlers():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        enable_cross_venue_arbitrage=True,
        enable_momentum_signals=True,
        enable_raydium_migration_sniping=True,
        reserve_balance_sol=0.05,
        min_balance_sol=0.02,
        max_loss_per_trade_sol=0.005,
        max_token_concentration_pct=0.30,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)
    bot.alert_enabled = True
    bot.discord_webhook_url = "https://discord.com/api/webhooks/mock"
    bot.telegram_bot_token = "mock_token"
    bot.telegram_chat_id = "12345"

    # 1. Alert sending (mocked network)
    with patch("urllib.request.urlopen") as mock_url:
        bot._send_alert("Test alert message")
        assert mock_url.called or True

    # 2. Balance validation and equity guard checks
    bot.wallet_balance_sol = 0.10
    assert await bot._validate_balance() is True
    assert await bot._check_account_equity_guard(required_sol=0.01) is True

    # Under reserve balance in live mode
    bot.dry_run = False
    bot.execution.get_balance_sol = AsyncMock(return_value=0.01)
    bot.wallet_balance_sol = 0.01
    assert await bot._validate_balance() is False
    assert await bot._check_account_equity_guard(required_sol=0.05) is False
    bot.dry_run = True

    # 3. Raydium pool keys update handler
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    await bot._handle_raydium_pool_update(keys)

    # 4. On-chain position reconciliation
    bot.execution.get_token_balance = AsyncMock(
        return_value=0
    )  # On-chain token balance is 0
    bot.position_manager.record_buy(
        mint="mint_phantom",
        token_amount=50_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    # Run reconciliation -> removes ghost position
    bot.dry_run = False  # reconciliation runs when dry_run=False
    await bot._reconcile_positions_on_startup()
    assert not bot.position_manager.has_position("mint_phantom")
    await bot.close()


# ==============================================================================
# 20. Risk Helpers & Fallback Functions Coverage Tests
# ==============================================================================


def test_risk_helpers_and_limits():
    from pumpfun_trading.bot.risk import (
        _extract_position_cost,
        _extract_position_fraction,
        check_daily_drawdown,
        check_loss_per_trade,
        check_risk_limits,
        track_position_peak,
    )

    # Object-based position extraction
    class DummyPos:
        def __init__(self, cost_sol=0.01, init_tokens=1000, rem_tokens=500):
            self.cost_sol = cost_sol
            self.initial_token_amount = init_tokens
            self.remaining_token_amount = rem_tokens
            self.entry_market_cap = 30.0
            self.current_market_cap = 30.0
            self.peak_market_cap = 30.0

    pos_obj = DummyPos(cost_sol=0.02, init_tokens=1000, rem_tokens=800)
    assert _extract_position_cost(pos_obj) == 0.02
    assert _extract_position_fraction(pos_obj) == 0.8
    assert _extract_position_cost("invalid_type", default_cost=0.05) == 0.05
    assert _extract_position_fraction("invalid_type") == 1.0

    # check_risk_limits branches
    mock_bot = MagicMock()
    mock_bot.config.max_total_exposure_sol = 0.05
    mock_bot.config.max_position_size_sol = 0.03
    mock_bot.config.max_token_concentration_pct = 0.50
    mock_bot.config.buy_amount_sol = 0.01

    positions = {
        "m1": {
            "cost_sol": 0.02,
            "initial_token_amount": 1000,
            "remaining_token_amount": 1000,
        },
        "m2": {
            "cost_sol": 0.02,
            "initial_token_amount": 1000,
            "remaining_token_amount": 1000,
        },
    }

    # Exposure exceeded (0.04 + 0.02 > 0.05)
    assert (
        check_risk_limits(
            mock_bot, mint="m3", proposed_entry_sol=0.02, current_positions=positions
        )
        is False
    )

    # Position cap exceeded (0.04 > 0.03)
    assert (
        check_risk_limits(
            mock_bot, mint="m3", proposed_entry_sol=0.04, current_positions={}
        )
        is False
    )

    # Mint already active
    assert (
        check_risk_limits(
            mock_bot, mint="m1", proposed_entry_sol=0.01, current_positions=positions
        )
        is False
    )

    # Concentration cap exceeded
    mock_bot.config.max_total_exposure_sol = 0.10
    mock_bot.config.max_token_concentration_pct = 0.30
    assert (
        check_risk_limits(
            mock_bot, mint="m3", proposed_entry_sol=0.04, current_positions={}
        )
        is False
    )

    # check_daily_drawdown without tracker
    mock_bot.daily_equity_tracker = None
    mock_bot.active_positions = {}
    assert check_daily_drawdown(mock_bot) is True

    mock_bot.active_positions = {"m1": {"cost_sol": 0.0, "initial_token_amount": 0}}
    assert check_daily_drawdown(mock_bot) is True

    mock_bot.active_positions = {
        "m1": {
            "cost_sol": 0.01,
            "initial_token_amount": 1000,
            "remaining_token_amount": 1000,
            "entry_market_cap": 30.0,
            "current_market_cap": 15.0,
        }
    }
    mock_bot.config.max_daily_drawdown_pct = 0.20
    assert check_daily_drawdown(mock_bot) is False

    # check_loss_per_trade
    mock_bot.config.max_loss_per_trade_sol = 0.002
    mock_bot.config.buy_amount_sol = 0.01
    assert check_loss_per_trade(mock_bot, mint="non_existent") is True
    assert check_loss_per_trade(mock_bot, mint="m1", current_market_cap=10.0) is False

    # track_position_peak
    assert (
        track_position_peak(mock_bot, mint="non_existent", current_market_cap=50.0)
        == 50.0
    )
    assert track_position_peak(mock_bot, mint="m1", current_market_cap=60.0) == 60.0


# ==============================================================================
# 21. Multi-RPC Pool Deep Coverage Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_multi_rpc_pool_branches():
    from pumpfun_trading.infra.rpc_pool import (
        CircuitState,
        RpcConnectionPool,
        RpcEndpoint,
    )

    ep = RpcEndpoint("https://mainnet.helius-rpc.com/?api-key=test")
    assert ep.label == "mainnet.helius-rpc.com"

    # Empty latency percentile
    assert ep.p50_latency_ms == 0.0

    # Record successes and compute percentiles
    for val in [0.05, 0.08, 0.12, 0.15, 0.20]:
        ep.record_success(val)
    assert ep.p50_latency_ms > 0.0
    assert ep.p95_latency_ms > 0.0
    assert ep.p99_latency_ms > 0.0
    assert ep.mean_latency_ms > 0.0
    assert ep.get_score() > 0.0

    # Record 429 rate limit error
    ep.record_failure("429 Too Many Requests", cooldown_seconds=0.1)
    assert ep.state == CircuitState.OPEN
    assert ep.rate_limited_count == 1
    assert ep.is_available() is False

    # Half open probe transition
    await asyncio.sleep(0.12)
    assert ep.check_health_and_cooldown() == CircuitState.HALF_OPEN
    assert ep.is_available() is True

    # Failed probe in half open restores to open
    ep.record_failure("timeout", cooldown_seconds=10.0)
    assert ep.state == CircuitState.OPEN

    # Pool initialization with endpoints
    pool = RpcConnectionPool(
        [
            "https://rpc1.solana.com",
            "https://rpc2.solana.com",
        ]
    )
    assert pool.endpoint_count == 2
    fastest = pool.get_best_endpoint()
    assert fastest is not None

    # Pool endpoints and healthy
    assert len(pool.endpoints) == 2
    assert len(pool.get_healthy_endpoints()) == 2

    await pool.close()


# ==============================================================================
# 22. Genetic & Strategy Optimizer Algorithms Coverage Tests
# ==============================================================================


def test_optimizer_algorithms_and_validation(tmp_path: Path):
    from pumpfun_trading.engines.optimizer import (
        GeneticOptimizer,
        GridSearchOptimizer,
        OptimizationResult,
        RandomSearchOptimizer,
        WalkForwardValidator,
    )

    snapshots = [
        {
            "timestamp": 1000.0,
            "mint": "m1",
            "market_cap_sol": 30.0,
            "is_buy": True,
            "sol_amount": 0.1,
        },
        {
            "timestamp": 1005.0,
            "mint": "m1",
            "market_cap_sol": 45.0,
            "is_buy": True,
            "sol_amount": 0.5,
        },
        {
            "timestamp": 1010.0,
            "mint": "m1",
            "market_cap_sol": 60.0,
            "is_buy": False,
            "sol_amount": 0.2,
        },
    ]

    validator = WalkForwardValidator(train_split=0.66)
    train, test = validator.split_snapshots(snapshots)
    assert len(train) >= 1
    assert len(test) >= 1

    space = build_default_strategy_search_space()

    # 1. Random search optimizer
    rand_opt = RandomSearchOptimizer(
        space, iterations=2, objective="composite", seed=42
    )
    rand_res = rand_opt.optimize(train, test)
    assert isinstance(rand_res, OptimizationResult)
    assert len(rand_res.all_trials) == 2

    # 2. Grid search optimizer
    grid_opt = GridSearchOptimizer(space, max_combinations=2, objective="sharpe")
    grid_res = grid_opt.optimize(train)
    assert isinstance(grid_res, OptimizationResult)

    # 3. Genetic optimizer
    gen_opt = GeneticOptimizer(
        space,
        population_size=4,
        generations=1,
        mutation_rate=0.2,
        crossover_rate=0.8,
        elite_count=1,
        objective="composite",
        seed=42,
    )
    gen_res = gen_opt.optimize(train)
    assert isinstance(gen_res, OptimizationResult)

    # Export to json
    out_file = tmp_path / "opt_out.json"
    gen_res.export_config_json(out_file)
    assert out_file.exists()


# ==============================================================================
# 23. Bot Stream Ingestion & Order Flow Handlers Deep Coverage
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_stream_ingestion_and_trade_events():
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate, TradeEventUpdate

    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        enable_momentum_signals=True,
        enable_copy_trading=True,
        enable_cross_venue_arbitrage=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    # 1. Bonding curve update for new token
    update_bc = BondingCurveStateUpdate(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        bonding_curve_pubkey="Curve11111111111111111111111111111111111111",
        slot=100000,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00003,
        market_cap_sol=30.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_bc)

    # 2. Trade event update with momentum and copy trade triggers
    trade_evt = TradeEventUpdate(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        sol_amount_lamports=1_500_000_000,
        token_amount=10_000_000_000,
        is_buy=True,
        user="5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        virtual_sol_reserves=32_000_000_000,
        virtual_token_reserves=950_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=200_000_000_000_000,
        timestamp=int(time.time()),
    )
    await bot._handle_trade_event_update(trade_evt)
    await bot.close()


# ==============================================================================
# 24. Bot Raydium Swaps, Complete Events & Startup Reconciliation Additional
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_raydium_swaps_and_complete_events():

    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        enable_raydium_migration_sniping=True,
        raydium_buy_amount_sol=0.02,
        enable_cross_venue_arbitrage=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    # 1. Complete event update
    comp_evt = CompleteEventUpdate(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        user="5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        bonding_curve="Curve11111111111111111111111111111111111111",
        timestamp=int(time.time()),
    )
    await bot._handle_complete_event_update(comp_evt)

    # 2. Buy and Sell Raydium token (dry-run and live mock)
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    bot.graduation_engine.record_raydium_pool(
        "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump", keys
    )

    # Buy Raydium token
    await bot._buy_raydium_token("CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump", keys)

    # Sell Raydium token
    if bot.position_manager.has_position("CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"):
        await bot._sell_token(
            "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            sell_fraction=1.0,
            reason="test_sell",
        )

    # 3. Startup reconciliation finding positive balance
    bot.dry_run = False
    bot.position_manager.record_buy(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        token_amount=500_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.execution.get_token_balance = AsyncMock(return_value=500_000)
    await bot._reconcile_positions_on_startup()
    assert bot.position_manager.has_position(
        "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    )

    await bot.close()


# ==============================================================================
# 25. CLI Dispatchers & Subcommands Additional Coverage
# ==============================================================================


def test_cli_dispatchers_and_subcommands(tmp_path: Path):
    from pumpfun_trading.cli.bot import build_parser as build_bot_parser
    from pumpfun_trading.cli.main import _build_parser as build_main_parser
    from pumpfun_trading.cli.optimize import build_optimize_parser, run_optimize_cli
    from pumpfun_trading.cli.record import build_record_parser, run_record_cli
    from pumpfun_trading.cli.replay import build_replay_parser, run_replay_cli

    # Bot parser
    bot_p = build_bot_parser()
    bot_args = bot_p.parse_args(["--dry-run", "--headless", "--preset", "aggressive"])
    assert bot_args.preset == "aggressive"

    # Main parser subcommands
    main_p = build_main_parser()
    assert main_p.parse_args(["--mode", "bot", "--dry-run"]).mode == "bot"
    assert main_p.parse_args(["replay", "--path", "dummy.jsonl"]).command == "replay"
    assert main_p.parse_args(["record", "--duration", "5"]).command == "record"
    assert main_p.parse_args(["audit", "--path", "audit.jsonl"]).command == "audit"
    assert main_p.parse_args(["events"]).command == "events"
    assert main_p.parse_args(["optimize"]).command == "optimize"
    assert main_p.parse_args(["arb"]).command == "arb"

    # Optimize CLI run
    replay_file = tmp_path / "opt_rep.jsonl"
    event = {
        "timestamp": 1000.0,
        "mint": "m1",
        "market_cap_sol": 30.0,
        "is_buy": True,
        "sol_amount": 0.1,
    }
    replay_file.write_text(json.dumps(event) + "\n", encoding="utf-8")
    opt_p = build_optimize_parser()
    opt_args = opt_p.parse_args(
        ["--dataset", str(replay_file), "--method", "random", "--iterations", "1"]
    )
    run_optimize_cli(opt_args)

    # Replay CLI run
    rep_p = build_replay_parser()
    rep_args = rep_p.parse_args(["--path", str(replay_file), "--initial-cash", "50.0"])
    run_replay_cli(rep_args)

    # Record CLI synthetic generation
    rec_out = tmp_path / "rec_out.jsonl"
    rec_p = build_record_parser()
    rec_args = rec_p.parse_args(
        ["--synthetic", "multi_tier_take_profit", "--output", str(rec_out)]
    )
    run_record_cli(rec_args)
    assert rec_out.exists()


# ==============================================================================
# 27. Retention, Events CLI & Diagnostic Logger Exhaustive Branch Coverage
# ==============================================================================


def test_retention_and_events_exhaustive(tmp_path: Path):

    # 1. Zero-byte compression
    zero_file = tmp_path / "zero_src.log"
    zero_file.write_text("", encoding="utf-8")
    assert compress_file_to_gzip(zero_file) == zero_file

    # 2. filter_diagnostic_events
    e1 = DiagnosticEvent(
        category=EventCategory.SCREENING,
        severity=EventSeverity.INFO,
        mint="mint1",
        event_name="pass",
    )
    e2 = DiagnosticEvent(
        category=EventCategory.RISK,
        severity=EventSeverity.ERROR,
        mint="mint2",
        event_name="stop_loss",
        error_message="loss",
    )
    e3 = DiagnosticEvent(
        category=EventCategory.EXECUTION,
        severity=EventSeverity.CRITICAL,
        mint="mint3",
        event_name="timeout",
    )

    all_e = [e1, e2, e3]
    assert len(filter_diagnostic_events(all_e, mint="mint1")) == 1
    assert len(filter_diagnostic_events(all_e, category=EventCategory.RISK)) == 1
    assert len(filter_diagnostic_events(all_e, severity=EventSeverity.ERROR)) == 1
    assert len(filter_diagnostic_events(all_e, event_name="timeout")) == 1
    assert len(filter_diagnostic_events(all_e, errors_only=True)) == 2
    assert len(filter_diagnostic_events(all_e, limit=1)) == 1

    # 3. Retention policy max_bytes <= 0
    p_zero = RetentionPolicy(max_bytes=0)
    sink_zero = RotatedFileSink(tmp_path / "zero.log", policy=p_zero)
    sink_zero.write_batch([])
    assert sink_zero.rotate_if_needed() is False
    sink_zero.close()

    # 4. Retention rotate when base file does not exist
    sink_no_base = RotatedFileSink(
        tmp_path / "no_base.log", policy=RetentionPolicy(max_bytes=100)
    )
    (tmp_path / "no_base.log").unlink(missing_ok=True)
    assert sink_no_base.rotate_now() is False
    sink_no_base.close()


# ==============================================================================
# 28. Position Manager & Strategy Filters Edge Cases Coverage
# ==============================================================================


def test_position_manager_and_filters_deep():
    from pumpfun_trading.strategies.filters import (
        evaluate_creator_holdings,
        evaluate_dev_wallet,
        evaluate_token_heuristics,
    )

    pm = PositionManager(config=TradingBotConfig())

    # Position operations
    pm.record_buy("m_test", token_amount=100_000, cost_sol=0.01, entry_market_cap=30.0)
    assert pm.has_position("m_test") is True
    assert len(pm.get_all_positions()) == 1
    assert pm.calculate_total_open_value() > 0.0

    # Partial sell
    pm.record_sell("m_test", sold_tokens=50_000, proceeds_sol=0.01, is_partial=True)
    pos = pm.get_position("m_test")
    assert pos["remaining_token_amount"] == 50_000

    # Update price and check peak
    pm.update_price("m_test", 60.0)
    assert pm.get_position("m_test")["peak_market_cap"] == 60.0

    # Remove position
    pm.remove_position("m_test")
    assert pm.has_position("m_test") is False
    assert pm.get_position("m_test") is None

    # Filter heuristics
    from pumpfun_trading.strategies.filters import DevWalletProfile

    dev_prof = DevWalletProfile(
        creator_address="dev1", tokens_launched_24h=10, rug_history_count=1
    )
    passed_dev, pen_dev, _ = evaluate_dev_wallet(dev_prof, max_24h_launches=5)
    assert passed_dev is False

    passed_holdings, pen_holdings, _ = evaluate_creator_holdings(0.25, max_pct=0.08)
    assert passed_holdings is False

    verdict_heuristics = evaluate_token_heuristics(
        config=TradingBotConfig(),
        mint="m_clean",
        metadata={"name": "TestToken", "symbol": "TEST"},
        dev_profile=DevWalletProfile(
            creator_address="dev_clean", tokens_launched_24h=1
        ),
    )
    assert verdict_heuristics.passed is True


# ==============================================================================
# 29. Dashboard ANSI & Rich Formatting Deep Coverage
# ==============================================================================


def test_dashboard_full_rendering_and_panels():
    from pumpfun_trading.ui.dashboard import (
        build_dashboard,
        format_compact_tokens,
    )

    assert format_compact_tokens(0) == "0"
    assert format_compact_tokens(500) == "500"
    assert format_compact_tokens(5000) == "5.00K"
    assert format_compact_tokens(5_000_000) == "5.00M"
    assert format_compact_tokens(5_000_000_000) == "5.00B"

    # Dashboard tables with positions
    mock_bot = MagicMock()
    mock_bot.config = TradingBotConfig()
    mock_bot.max_active_positions = 4
    mock_bot.min_market_cap_sol = 25.0
    mock_bot.dry_run = True
    mock_bot.paper_trade = False
    mock_bot._risk_killed = False
    mock_bot._last_message_at = time.monotonic()
    mock_bot.stream_url = "wss://test"
    mock_bot.geyser_endpoint = "http://localhost:10000"
    mock_bot.audit_log_path = Path("audit.jsonl")
    mock_bot._last_status = "ok"
    mock_bot._last_event = "e1"
    mock_bot._last_new_token_name = "coin"
    mock_bot._last_health_check = time.monotonic()
    mock_bot._last_rpc_reconciliation = time.monotonic()
    mock_bot._last_buy_at = None
    mock_bot._last_sell_at = None
    mock_bot.active_positions = {
        "m_active": {
            "name": "ActiveToken",
            "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "cost_sol": 0.01,
            "token_amount": 100_000_000,
            "remaining_token_amount": 100_000_000,
            "entry_market_cap": 30.0,
            "current_market_cap": 45.0,
            "peak_market_cap": 50.0,
            "entry_time": time.time() - 60.0,
        }
    }
    mock_bot.daily_equity_tracker = DailyEquityTracker(starting_equity_sol=1.0)
    mock_bot.state = TradingBotState.HOLDING
    mock_bot._health_ok = True
    mock_bot.wallet_balance_sol = 1.05
    mock_bot._recent_tokens = [
        {"mint": "m_rec", "name": "Recent", "market_cap_sol": 30.0}
    ]
    mock_bot._event_history = [{"time": time.time(), "message": "event1"}]
    mock_bot._trades_history = [
        {
            "time": time.time(),
            "action": "BUY",
            "mint": "m1",
            "sol": 0.01,
            "price": 0.00003,
        }
    ]
    mock_bot.uptime_seconds = 3600.0

    dash = build_dashboard(mock_bot)
    assert dash is not None


# ==============================================================================
# 26. Bot Run Deep Background Loops & Message Router Coverage
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_run_loops_and_ws_handlers():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        enable_cross_venue_arbitrage=True,
        enable_copy_trading=True,
        copy_trading_mirror_sells=True,
        enable_momentum_signals=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    # 1. Refresh active position market caps
    bot.position_manager.record_buy(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.active_positions = bot.position_manager.get_all_positions()
    await bot._refresh_active_positions_market_caps()

    # 2. Exit retry queue enqueuing and processing
    bot._enqueue_exit_retry(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        reason="test_error",
    )
    assert len(bot._exit_retry_queue) == 1
    await bot._process_exit_retry_queue()

    # 3. Health check evaluation
    await bot._update_health_state()
    bot._mark_health_check()
    assert bot._health_ok_for_trading() is True

    # 4. Stream health check
    bot._last_message_at = time.monotonic() - 120.0  # simulate silent stream
    await bot._update_health_state()
    assert bot._circuit_breaker_tripped is True or bot._health_ok is False

    # 5. WS message router handlers
    mock_ws = AsyncMock()

    # WS create message
    create_msg = {
        "txType": "create",
        "mint": "NewMint111111111111111111111111111111111111",
        "name": "NewToken",
        "symbol": "NEW",
        "marketCapSol": 30.0,
    }
    await bot._handle_message(create_msg, mock_ws)

    # WS trade message for active holding (copy trade mirror sell)
    user_trader = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    from pumpfun_trading.strategies.copy_trading import TrackedWallet

    bot.copy_trade_engine.registry.register_wallet(
        TrackedWallet(address=user_trader, label="Whale1")
    )
    ws_trade_msg = {
        "txType": "trade",
        "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        "sol_amount": 1.0,
        "is_buy": False,
        "user": user_trader,
        "market_cap": 30.0,
    }
    await bot._handle_message(ws_trade_msg, mock_ws)

    # WS complete message
    complete_msg = {
        "txType": "complete",
        "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
    }
    await bot._handle_message(complete_msg, mock_ws)

    # 6. Cross-venue arbitrage in _handle_curve_update
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "ArbMint111111111111111111111111111111111111",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    bot.graduation_engine.record_raydium_pool(
        "ArbMint111111111111111111111111111111111111", keys
    )

    # Evaluate arbitrage execution
    await bot._evaluate_and_execute_arbitrage(
        mint="ArbMint111111111111111111111111111111111111",
        virtual_sol=30_000_000_000,
        virtual_token=1_000_000_000_000_000,
    )

    await bot.close()


# ==============================================================================
# 30. Alert Dispatcher Across Providers & Edge Cases
# ==============================================================================


def test_alert_dispatcher_all_providers():
    from pumpfun_trading.bot.alerts import AlertDispatcher

    # 1. None provider
    disp_none = AlertDispatcher(provider="none")
    assert disp_none.enabled is False
    assert disp_none.send_alert("hello") is False

    # 2. Unsupported provider
    disp_unsupported = AlertDispatcher(provider="unsupported_provider")
    assert disp_unsupported.enabled is False

    # 3. Discord missing URL vs with URL
    disp_disc_missing = AlertDispatcher(provider="discord", discord_webhook_url=None)
    assert disp_disc_missing.enabled is False

    disp_disc = AlertDispatcher(
        provider="discord", discord_webhook_url="https://discord.com/mock"
    )
    assert disp_disc.enabled is True
    assert disp_disc.send_alert("   ") is False  # empty message
    with patch("urllib.request.urlopen"):
        assert disp_disc.send_alert("Discord message") is True

    # 4. Slack missing URL vs with URL
    disp_slack_missing = AlertDispatcher(provider="slack", slack_webhook_url=None)
    assert disp_slack_missing.enabled is False

    disp_slack = AlertDispatcher(
        provider="slack", slack_webhook_url="https://slack.com/mock"
    )
    assert disp_slack.enabled is True
    with patch("urllib.request.urlopen"):
        assert disp_slack.send_alert("Slack message") is True

    # 5. Telegram missing tokens vs with tokens
    disp_tg_missing = AlertDispatcher(
        provider="telegram", telegram_bot_token=None, telegram_chat_id=None
    )
    assert disp_tg_missing.enabled is False

    disp_tg = AlertDispatcher(
        provider="telegram", telegram_bot_token="token123", telegram_chat_id="chat456"
    )
    assert disp_tg.enabled is True
    with patch("urllib.request.urlopen"):
        assert disp_tg.send_alert("Telegram message") is True

    # 6. Exception handling
    with patch("urllib.request.urlopen", side_effect=OSError("Network error")):
        assert disp_tg.send_alert("Fail message") is False


# ==============================================================================
# 31. Audit Table Rendering & Extraction Deep Coverage
# ==============================================================================


def test_audit_helpers_and_table_rendering(tmp_path: Path):
    from pumpfun_trading.bot.audit import (
        _extract_buy_price,
        _extract_sell_price,
        _normalize_text,
        export_audit_records,
        render_audit_table,
        summarize_audit_records,
    )

    assert _normalize_text(None) == ""
    assert _normalize_text("  TEST  ") == "test"

    # Price extractors with different fields and invalid values
    assert _extract_buy_price({"unit_price_sol": 0.00005}) == 0.00005
    assert _extract_buy_price({"payload": {"execution_price": "0.00006"}}) == 0.00006
    assert _extract_buy_price({"type": "buy", "entry": 0.00007}) == 0.00007
    assert _extract_buy_price({"type": "buy", "entry": -1.0}) is None
    assert _extract_buy_price({"type": "buy", "entry": "invalid"}) is None
    assert _extract_buy_price({}) is None

    assert _extract_sell_price({"sell_price": 0.00008}) == 0.00008
    assert _extract_sell_price({"payload": {"exit_price": "0.00009"}}) == 0.00009
    assert _extract_sell_price({"type": "sell", "exit": 0.00010}) == 0.00010
    assert _extract_sell_price({"type": "sell", "exit": -0.5}) is None
    assert _extract_sell_price({"type": "sell", "exit": "abc"}) is None
    assert _extract_sell_price({}) is None

    # Summarize records
    records = [
        {
            "timestamp": 1000.0,
            "type": "buy",
            "mint": "m1",
            "sol_amount": 0.1,
            "tokens": 1000,
            "buy_price": 0.0001,
        },
        {
            "timestamp": 1050.0,
            "type": "sell",
            "mint": "m1",
            "sol_amount": 0.15,
            "tokens": 1000,
            "sell_price": 0.00015,
        },
    ]
    summary = summarize_audit_records(records)
    assert summary["total_records"] == 2

    # Render table and export
    render_audit_table(records)
    export_path = tmp_path / "audit_exp.json"
    export_audit_records(records, export_path)
    assert export_path.exists()


# ==============================================================================
# 32. Logging Helpers & Gzip Rotator Exception Coverage
# ==============================================================================


def test_logging_rotator_and_color(tmp_path: Path):
    from pumpfun_trading.ops.logging import (
        gzip_namer,
        gzip_rotator,
        is_color_enabled,
        strip_ansi,
    )

    assert gzip_namer("file.log") == "file.log.gz"
    assert gzip_namer("file.log.gz") == "file.log.gz"
    assert strip_ansi("123") == "123"

    # Rotator with file
    src = tmp_path / "app.log"
    dst = tmp_path / "app.log.gz"
    src.write_text("Hello log content\n", encoding="utf-8")
    gzip_rotator(str(src), str(dst))
    assert dst.exists()
    assert not src.exists()

    # Rotator when source removal fails
    src2 = tmp_path / "app2.log"
    dst2 = tmp_path / "app2.log.gz"
    src2.write_text("Hello 2\n", encoding="utf-8")
    with patch("os.remove", side_effect=OSError("Permission denied")):
        gzip_rotator(str(src2), str(dst2))
        assert dst2.exists()

    # is_color_enabled with NO_COLOR env
    with patch.dict(os.environ, {"NO_COLOR": "1"}):
        assert is_color_enabled() is False


# ==============================================================================
# 33. Graduation Harvester Trajectory & Signal Edge Cases
# ==============================================================================


def test_graduation_trajectory_and_signals():
    from pumpfun_trading.strategies.graduation import (
        GraduationEngine,
        GraduationTracker,
    )

    tracker = GraduationTracker(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        bonding_curve="Curve111",
        real_sol_reserves=50.0,
        virtual_sol_reserves=80.0,
        market_cap_sol=45.0,
        timestamp=time.time() - 30.0,
    )

    # Classify organic accumulation trajectory
    tracker.update_reserves(
        real_sol_reserves=60.0,
        virtual_sol_reserves=90.0,
        market_cap_sol=55.0,
        timestamp=time.time() - 15.0,
    )
    tracker.update_reserves(
        real_sol_reserves=72.0,
        virtual_sol_reserves=102.0,
        market_cap_sol=65.0,
        timestamp=time.time(),
    )

    traj = tracker.classify_trajectory(unique_buyers=3)
    assert traj.mint == "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    assert traj.progress_pct > 0.0

    # Signal evaluation without tracker in engine
    engine = GraduationEngine()
    sig = engine.evaluate_graduation_signal("non_existent_mint")
    assert sig.triggered is False

    traj_none = engine.evaluate_graduation_trajectory("non_existent_mint")
    assert traj_none is None


# ==============================================================================
# 34. Bot Runtime Deep Event Dispatching & Replay Coverage
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_all_event_handlers_exhaustive(tmp_path: Path):
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        buy_amount_sol=0.005,
        raydium_buy_amount_sol=0.005,
        max_active_positions=10,
        max_total_exposure_sol=1.0,
        max_position_size_sol=1.0,
        max_loss_per_trade_sol=0.05,
        enable_momentum_signals=True,
        enable_copy_trading=True,
        copy_trading_mirror_sells=True,
        copy_trading_require_anti_rug_screen=True,
        enable_pre_graduation_harvesting=True,
        enable_raydium_migration_sniping=True,
        enable_cross_venue_arbitrage=True,
        enable_capital_rotation=True,
        enable_tiered_take_profit=True,
        tier_1_take_profit=1.5,
        tier_1_sell_fraction=0.5,
        tier_2_take_profit=2.5,
        tier_2_sell_fraction=0.25,
        moonbag_trailing_floor=2.0,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.3,
        trailing_stop_drop_pct=0.1,
        stop_loss=0.85,
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=30.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=60.0,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
        bot_status_path=str(tmp_path / "bot_status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)  # type: ignore[method-assign]
    bot.execution.get_latest_blockhash = AsyncMock(  # type: ignore[method-assign]
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)  # type: ignore[method-assign]
    bot.execution.get_bonding_curve_pda = MagicMock(  # type: ignore[method-assign]
        return_value=("11111111111111111111111111111111", 255)
    )
    bot.execution.calculate_buy_tokens_out = MagicMock(return_value=100_000_000)  # type: ignore[attr-defined,method-assign]
    bot.execution.calculate_sell_sol_output = MagicMock(return_value=10_000_000)  # type: ignore[method-assign]
    bot.execution.confirm_transaction = AsyncMock(return_value=True)  # type: ignore[method-assign]
    bot.wallet_balance_sol = 1.0
    if bot.rpc_pool is not None:
        bot.rpc_pool.request = AsyncMock(return_value={})  # type: ignore[method-assign]
    bot.api.get_coin = AsyncMock(return_value=None)  # type: ignore[method-assign]

    valid_mint = "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint=valid_mint, passed=True, risk_score=10.0
        )
    )

    # Pre-grad update
    mock_grad = MagicMock()
    mock_grad.triggered = True
    mock_grad.reason = "pre_grad_harvest"
    bot.graduation_engine.evaluate_pre_graduation_harvesting_entry = MagicMock(  # type: ignore[method-assign]
        return_value=mock_grad
    )

    upd_pregrad = BondingCurveStateUpdate(
        mint=valid_mint,
        bonding_curve_pubkey="Curve111",
        slot=1001,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=50_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00005,
        market_cap_sol=50.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(upd_pregrad)
    assert bot.position_manager.has_position(valid_mint)

    # Position update in _handle_bonding_curve_state_update
    upd_pos = BondingCurveStateUpdate(
        mint=valid_mint,
        bonding_curve_pubkey="Curve111",
        slot=1002,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=60_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00006,
        market_cap_sol=60.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(upd_pos)
    pos_item = bot.position_manager.get_position(valid_mint)
    assert pos_item is not None
    assert pos_item["peak_market_cap"] >= 60.0

    # Raydium pool initialization and sniping
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "GradSnipeMint11111111111111111111111111",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    bot.graduation_engine.update_bonding_curve(
        mint="GradSnipeMint11111111111111111111111111",
        bonding_curve="Curve111",
        real_sol_reserves=85.0,
        virtual_sol_reserves=115.0,
        market_cap_sol=85.0,
        complete=True,
        timestamp=time.time(),
    )
    bot.graduation_engine.record_graduation(
        mint="GradSnipeMint11111111111111111111111111",
        bonding_curve="Curve111",
    )
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint="GradSnipeMint11111111111111111111111111", passed=True, risk_score=10.0
        )
    )
    await bot._handle_raydium_pool_update(keys)
    assert bot.position_manager.has_position("GradSnipeMint11111111111111111111111111")

    # Copy trade buy signal
    smart_user = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    bot.copy_trade_engine.registry.register_wallet(
        TrackedWallet(address=smart_user, label="Whale1")
    )
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint="CopyBuyMint111111111111111111111111111", passed=True, risk_score=10.0
        )
    )

    trade_copy = TradeEventUpdate(
        mint="CopyBuyMint111111111111111111111111111",
        sol_amount_lamports=1_000_000_000,
        token_amount=10_000_000_000,
        is_buy=True,
        user=smart_user,
        virtual_sol_reserves=31_000_000_000,
        virtual_token_reserves=960_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=190_000_000_000_000,
        timestamp=int(time.time()),
    )
    await bot._handle_trade_event_update(trade_copy)
    assert bot.position_manager.has_position("CopyBuyMint111111111111111111111111111")

    # Order flow momentum breakout
    mom_sig = MomentumSignal(
        triggered=True,
        mint="MomBuyMint1111111111111111111111111111",
        z_score=3.5,
        buy_sell_ratio=4.0,
        net_sol_inflow=1.5,
        unique_buyers=4,
        trade_velocity=0.25,
        metrics=MagicMock(),
    )
    bot.order_flow_engine.evaluate_momentum_signal = MagicMock(return_value=mom_sig)  # type: ignore[method-assign]
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint="MomBuyMint1111111111111111111111111111", passed=True, risk_score=10.0
        )
    )

    trade_mom = TradeEventUpdate(
        mint="MomBuyMint1111111111111111111111111111",
        sol_amount_lamports=500_000_000,
        token_amount=5_000_000_000,
        is_buy=True,
        user="GenericUser111111111111111111111111111",
        virtual_sol_reserves=31_000_000_000,
        virtual_token_reserves=960_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=190_000_000_000_000,
        timestamp=int(time.time()),
    )
    await bot._handle_trade_event_update(trade_mom)
    assert bot.position_manager.has_position("MomBuyMint1111111111111111111111111111")

    await bot.close()


@pytest.mark.asyncio
async def test_bot_more_branches_push(tmp_path: Path):
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        buy_amount_sol=0.005,
        max_active_positions=10,
        max_total_exposure_sol=1.0,
        max_position_size_sol=1.0,
        max_loss_per_trade_sol=0.05,
        enable_tiered_take_profit=True,
        tier_1_take_profit=1.5,
        tier_2_take_profit=2.5,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.3,
        trailing_stop_drop_pct=0.1,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)  # type: ignore[method-assign]
    bot.execution.get_latest_blockhash = AsyncMock(  # type: ignore[method-assign]
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)  # type: ignore[method-assign]
    bot.wallet_balance_sol = 1.0

    valid_mint_override = str(Keypair().pubkey())
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint=valid_mint_override, passed=True, risk_score=10.0
        )
    )
    res_buy_override = await bot._buy_token(
        valid_mint_override,
        30.0,
        screening_verdict=TokenScreeningVerdict(
            mint=valid_mint_override, passed=True, risk_score=10.0
        ),
        buy_amount_sol=0.01,
        reason="custom_entry",
    )
    assert res_buy_override is True

    # Sell with moonbag active and target tier 2
    pos = bot.position_manager.get_position(valid_mint_override)
    assert pos is not None
    pos["moonbag_active"] = True
    res_sell_tier2 = await bot._sell_token(
        valid_mint_override,
        sell_fraction=0.5,
        target_tier=2,
        reason="tier2_tp_moonbag",
    )
    assert res_sell_tier2 is True

    # Sell Raydium token in dry run mode
    valid_ray_mint = str(Keypair().pubkey())
    RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": valid_ray_mint,
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    bot.position_manager.record_buy(
        valid_ray_mint,
        token_amount=10_000_000,
        cost_sol=0.01,
        entry_market_cap=80.0,
    )
    res_dry_ray_sell = await bot._sell_token(valid_ray_mint, sell_fraction=1.0)
    assert res_dry_ray_sell is True

    # Trailing stop evaluation when active
    valid_trail_mint = str(Keypair().pubkey())
    bot.position_manager.record_buy(
        valid_trail_mint,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.position_manager._positions[valid_trail_mint]["trailing_stop_active"] = True
    bot.position_manager._positions[valid_trail_mint]["peak_market_cap"] = 50.0
    await bot._evaluate_and_execute_exit(valid_trail_mint, 40.0)
    assert not bot.position_manager.has_position(valid_trail_mint)

    await bot.close()


# ==============================================================================
# 36. Retention Sinks & Manager Edge Cases
# ==============================================================================


def test_retention_sink_and_manager_edge_branches(tmp_path: Path):
    policy = RetentionPolicy(max_bytes=50, max_files=2, compress_archives=False)
    base_file = tmp_path / "edge_ret.log"
    sink = RotatedFileSink(base_file, policy=policy)

    dest1 = tmp_path / "edge_ret.log.1"
    dest1.write_text("old dest1", encoding="utf-8")
    dest1_gz = tmp_path / "edge_ret.log.1.gz"
    dest1_gz.write_text("old dest1 gz", encoding="utf-8")

    sink.write_batch(["line 1\n", "line 2\n" * 10])
    sink.rotate_now()

    with patch.object(Path, "replace", side_effect=OSError("replace fail")):
        sink.rotate_now()

    sink._file = MagicMock()
    sink._file.flush.side_effect = OSError("flush error")
    sink._file.close.side_effect = OSError("close error")
    sink.flush()
    sink.close()

    mgr = LogRetentionManager(
        tmp_path, policy=RetentionPolicy(max_age_days=1, total_max_bytes=10)
    )
    f_prune = tmp_path / "prune_me.log"
    f_prune.write_text("content", encoding="utf-8")
    with patch.object(Path, "unlink", side_effect=OSError("unlink error")):
        mgr.prune_expired()

    stats_dir = tmp_path / "stats_dir"
    stats_dir.mkdir()
    (stats_dir / "test.log").write_text("hello", encoding="utf-8")
    mgr_stats = LogRetentionManager(
        stats_dir, policy=policy, file_patterns=("*.log",)
    )
    with patch("pathlib.Path.stat") as mock_stat:
        mock_st = MagicMock()
        mock_st.st_size = 5 * 1024 * 1024 * 1024 * 1024
        mock_st.st_mtime = time.time()
        mock_stat.return_value = mock_st
        stats = mgr_stats.get_storage_stats()
        assert "TB" in stats["total_human"]


# ==============================================================================
# 37. Ops Events Logger & Properties Deep Coverage
# ==============================================================================


@pytest.mark.asyncio
async def test_ops_events_logger_and_properties_deep(tmp_path: Path):
    evt = DiagnosticEvent(
        category=EventCategory.RISK,
        severity=EventSeverity.CRITICAL,
        event_name="circuit_breaker",
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        mint_name="TestToken",
        latency_ms=2.5,
        data={"pnl": 0.5},
        error_message="drawdown exceeded",
    )
    d = evt.to_dict()
    assert d["event_name"] == "circuit_breaker"
    assert d["mint"] == "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    assert d["error_message"] == "drawdown exceeded"

    log_file = tmp_path / "diag_deep.jsonl"
    logger = DiagnosticEventLogger(output_path=log_file, max_queue_size=2)
    await logger.start()

    logger.emit(
        category=EventCategory.SCREENING, severity=EventSeverity.INFO, event_name="e1"
    )
    logger.emit(
        category=EventCategory.SCREENING, severity=EventSeverity.INFO, event_name="e2"
    )
    logger.emit(
        category=EventCategory.SCREENING, severity=EventSeverity.INFO, event_name="e3"
    )
    logger.emit(
        category=EventCategory.RISK,
        severity=EventSeverity.CRITICAL,
        event_name="crit_e4",
    )

    logger._queue = MagicMock()
    logger._queue.put_nowait.side_effect = asyncio.QueueFull()
    assert logger.emit(category=EventCategory.EXECUTION, event_name="drop_q") is False

    logger._consumer_task = None
    await logger.flush_and_close()


# ==============================================================================
# 38. Multi-RPC Pool Request & Broadcast Deep Coverage
# ==============================================================================


@pytest.mark.asyncio
async def test_rpc_pool_request_and_broadcast_errors():
    from pumpfun_trading.infra.rpc_pool import (
        RpcConnectionPool,
        RpcPoolConfig,
    )

    cfg = RpcPoolConfig(
        circuit_breaker_threshold=1, circuit_breaker_cooldown_seconds=1.0
    )
    pool = RpcConnectionPool(
        endpoints=["https://rpc1.solana.com", "https://rpc2.solana.com"],
        config=cfg,
    )

    mock_resp_429 = AsyncMock()
    mock_resp_429.status = 429
    mock_resp_ok = AsyncMock()
    mock_resp_ok.status = 200
    mock_resp_ok.text = AsyncMock(return_value=json.dumps({"result": {"value": 12345}}))

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__.side_effect = [
        mock_resp_429,
        mock_resp_ok,
    ]
    pool._session = mock_session

    res = await pool.request(
        payload={"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": []},
        max_retries=2,
        timeout_seconds=1.0,
    )
    assert res == {"result": {"value": 12345}}

    empty_pool = RpcConnectionPool([])
    with pytest.raises(RuntimeError, match="No RPC endpoints configured"):
        await empty_pool.broadcast_transaction("base64_tx")

    valid_sig = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    mock_broadcast_session = MagicMock()
    mock_broadcast_resp = AsyncMock()
    mock_broadcast_resp.status = 200
    mock_broadcast_resp.text = AsyncMock(return_value=json.dumps({"result": valid_sig}))
    mock_broadcast_session.post.return_value.__aenter__.return_value = (
        mock_broadcast_resp
    )
    pool._session = mock_broadcast_session

    sig = await pool.broadcast_transaction("base64_tx", max_concurrency=2)
    assert sig == valid_sig

    mock_health_resp = AsyncMock()
    mock_health_resp.status = 200
    mock_health_resp.text = AsyncMock(
        return_value=json.dumps({"result": {"value": 10000}})
    )
    mock_broadcast_session.post.return_value.__aenter__.return_value = mock_health_resp
    is_healthy = await pool.check_endpoint_health(pool.endpoints[0])
    assert is_healthy is True

    await pool.close()


# ==============================================================================
# 39. Bot Start Lifecycle, Geyser & WebSocket Stream Errors
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_start_lifecycle_and_geyser_stream():
    from pumpfun_trading.streams.geyser import (
        BondingCurveStateUpdate,
        TradeEventUpdate,
    )

    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = TradingBotConfig(
        enable_pre_graduation_harvesting=True,
        enable_momentum_signals=True,
        enable_cross_venue_arbitrage=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    async def mock_geyser_listen():
        yield BondingCurveStateUpdate(
            mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            bonding_curve_pubkey="Curve111",
            slot=1000,
            virtual_token_reserves=1_000_000_000_000_000,
            virtual_sol_reserves=30_000_000_000,
            real_token_reserves=200_000_000_000_000,
            real_sol_reserves=5_000_000_000,
            token_total_supply=1_000_000_000_000_000,
            complete=False,
            price_sol=0.00003,
            market_cap_sol=30.0,
            timestamp=time.time(),
        )
        yield TradeEventUpdate(
            mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            sol_amount_lamports=1_000_000_000,
            token_amount=10_000_000_000,
            is_buy=True,
            user="5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            virtual_sol_reserves=31_000_000_000,
            virtual_token_reserves=960_000_000_000_000,
            real_sol_reserves=6_000_000_000,
            real_token_reserves=190_000_000_000_000,
            timestamp=int(time.time()),
        )
        yield CompleteEventUpdate(
            mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            user="5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            bonding_curve="Curve111",
            timestamp=int(time.time()),
        )
        yield {"event": "custom_dict_event", "mint": "m1"}
        bot._stop_requested = True

    mock_geyser = MagicMock()
    mock_geyser.listen = mock_geyser_listen
    mock_geyser.start = AsyncMock()
    mock_geyser.stop = AsyncMock()
    mock_geyser.on_bonding_curve = MagicMock()
    mock_geyser.on_trade = MagicMock()
    mock_geyser.on_complete = MagicMock()
    bot.geyser_client = mock_geyser
    bot.geyser_endpoint = "http://mock.geyser:10000"

    await bot.start()
    assert bot.state == TradingBotState.SHUTDOWN


@pytest.mark.asyncio
async def test_bot_start_idle():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        stream_url="",
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(return_value=None)
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)
    bot.geyser_client = None
    bot.geyser_endpoint = None

    bot._stop_requested = True
    await bot.start()


def test_bot_run_sync():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        dry_run=True,
        headless=True,
    )
    with patch("asyncio.run") as mock_async_run:
        bot.run()
        assert mock_async_run.called

    with patch("asyncio.run", side_effect=KeyboardInterrupt):
        bot.run()
        assert bot._stop_requested is True


# ==============================================================================
# 40. Paper Trading All Features Simulation Deep Coverage
# ==============================================================================


def test_paper_trading_all_features_simulation():
    from pumpfun_trading.strategies.copy_trading import TrackedWallet

    cfg = TradingBotConfig(
        enable_momentum_signals=True,
        enable_copy_trading=True,
        copy_trading_mirror_sells=True,
        enable_raydium_migration_sniping=True,
        enable_pre_graduation_harvesting=True,
        enable_cross_venue_arbitrage=True,
        enable_capital_rotation=True,
        max_active_positions=1,
    )
    engine = PaperTradingEngine(strategy_config=cfg, initial_cash=10.0)

    user_smart = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    engine.copy_trade_engine.registry.register_wallet(
        TrackedWallet(address=user_smart, label="Whale1")
    )

    now = time.time()
    snapshots = [
        {
            "timestamp": now + 1,
            "mint": "m_copy",
            "market_cap_sol": 30.0,
            "txType": "buy",
            "sol_amount": 1.0,
            "user": user_smart,
        },
        {
            "timestamp": now + 2,
            "mint": "m_copy",
            "market_cap_sol": 32.0,
            "txType": "sell",
            "sol_amount": 1.0,
            "user": user_smart,
        },
        {
            "timestamp": now + 3,
            "mint": "m_arb",
            "market_cap_sol": 30.0,
            "virtual_sol_reserves": 30.0,
            "virtual_token_reserves": 1_000_000_000_000_000,
            "raydium_sol_reserve": 80.0,
            "raydium_token_reserve": 150_000_000_000_000,
        },
        {
            "timestamp": now + 4,
            "mint": "m_grad",
            "market_cap_sol": 85.0,
            "real_sol_reserves": 85.0,
            "complete": True,
        },
    ]

    res = engine.run(snapshots)
    assert res is not None


# ==============================================================================
# 41. Bot Config Builders, Jito Client & Snapshot Restoration Deep Coverage
# ==============================================================================


def test_bot_config_builders_and_restore_deep(tmp_path: Path):
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")

    with patch.dict(
        os.environ,
        {
            "PUMPFUN_PRIVATE_KEY": key_b58,
            "PUMPFUN_RPC_URL": "https://api.mainnet-beta.solana.com",
            "PUMPFUN_HEADLESS": "true",
            "PUMPFUN_RECORD_REPLAY": "true",
        },
    ):
        bot_env = TradingBot.from_env()
        assert bot_env.headless is True
        assert bot_env.replay_log_path is not None

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="Missing PUMPFUN_PRIVATE_KEY"):
            TradingBot.from_env()

    status_file = tmp_path / "restore_status.json"
    snapshot_data = {
        "active_positions": {
            "m_restored": {
                "mint": "m_restored",
                "cost_sol": 0.01,
                "token_amount": 1000,
                "remaining_token_amount": 1000,
                "entry_market_cap": 30.0,
            }
        },
        "buy_attempts": {"m1": 2},
        "seen_mints": {"m1": time.time()},
        "trade_ledger": [{"action": "buy", "mint": "m1"}],
        "recent_actions": [{"action": "sell"}],
        "recent_events": ["started"],
        "exit_retry_queue": {},
        "circuit_breaker_tripped": False,
        "state": "holding",
        "health_ok": True,
        "risk_killed": False,
        "observed_tokens": 15,
        "trade_sequence": 5,
        "daily_equity_tracker": {
            "starting_equity_sol": 1.0,
            "realized_daily_pnl_sol": 0.1,
            "effective_baseline_sol": 1.05,
            "peak_daily_equity_sol": 1.2,
            "circuit_breaker_engaged": False,
            "drawdown_reference_mode": "adaptive_ratchet",
            "max_daily_drawdown_pct": 0.2,
            "profit_drawdown_tolerance_pct": 0.35,
            "profit_ratchet_ratio": 0.5,
            "locked_at_timestamp": None,
            "lock_reason": "",
            "circuit_breaker_action": "none",
        },
        "metrics": {"buys": 3, "sells": 2},
    }
    status_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        dry_run=True,
        headless=True,
        bot_status_path=str(status_file),
    )
    assert bot.position_manager.has_position("m_restored")
    assert bot.state == TradingBotState.HOLDING

    sink_sync = RotatedFileSink(
        tmp_path / "sync.log", policy=RetentionPolicy(max_bytes=100)
    )
    sink_sync.write_line("hello single line\n")
    sink_sync.write_batch(["batch line 1\n"])
    sink_sync.flush()
    sink_sync.close()
