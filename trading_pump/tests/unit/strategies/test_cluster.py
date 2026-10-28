"""Unit and integration tests for On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector (FEAT-26)."""

import time

import pytest

from trading_pump.strategies.cluster import (
    ClusterAnalysisVerdict,
    FundingCluster,
    FundingClusterAnalyzer,
    FundingClusterGraph,
    SybilWashTradingDetector,
    SybilWashVerdict,
    WalletNode,
)
from trading_pump.strategies.filters import (
    DevWalletProfile,
    HolderDistribution,
    evaluate_cluster_heuristics,
    evaluate_token_heuristics,
    passes_anti_rug_screening,
)
from trading_pump.tests.support.factories import make_screening


def test_wallet_node_and_funding_cluster_data_models():
    node = WalletNode(
        address="WalletA11111111111111111111111111111111111",
        parent_address="Funder111111111111111111111111111111111111",
        root_ancestor="Root11111111111111111111111111111111111111",
        depth=2,
        token_balance=100_000_000_000_000,
        supply_fraction=0.10,
        is_creator=True,
        is_top_holder=True,
        sol_funded=1.5,
    )
    d = node.to_dict()
    assert d["address"] == "WalletA11111111111111111111111111111111111"
    assert d["depth"] == 2
    assert d["is_creator"] is True
    assert d["sol_funded"] == 1.5

    cluster = FundingCluster(
        root_funder="Root11111111111111111111111111111111111111",
        wallets=["WalletA", "WalletB"],
        total_token_balance=250_000_000_000_000,
        cluster_supply_fraction=0.25,
        max_depth=2,
        total_sol_funded=3.0,
        has_creator=True,
        is_syndicate=True,
    )
    cd = cluster.to_dict()
    assert cd["root_funder"] == "Root11111111111111111111111111111111111111"
    assert cd["cluster_supply_fraction"] == 0.25
    assert cd["is_syndicate"] is True


def test_funding_cluster_graph_building_and_ancestor_resolution():
    graph = FundingClusterGraph(total_supply=1_000_000_000_000_000)

    # Add wallets
    graph.add_wallet("W_A", token_balance=100_000_000_000_000, is_top_holder=True)
    graph.add_wallet("W_B", token_balance=150_000_000_000_000, is_top_holder=True)
    graph.add_wallet("W_C", token_balance=50_000_000_000_000, is_top_holder=True)
    graph.add_wallet(
        "W_Independent", token_balance=80_000_000_000_000, is_top_holder=True
    )

    # Add tree: Root_1 -> Splitter_1 -> W_A & W_B
    graph.add_funding_link("W_A", "Splitter_1", sol_amount=1.0)
    graph.add_funding_link("W_B", "Splitter_1", sol_amount=1.5)
    graph.add_funding_link("Splitter_1", "Root_1", sol_amount=3.0)

    # Independent wallet funded by distinct root
    graph.add_funding_link("W_Independent", "ExchangeHotWallet_1", sol_amount=5.0)

    # Test root resolution
    root_a, depth_a = graph.find_root_ancestor("W_A")
    assert root_a == "Root_1"
    assert depth_a == 2

    root_b, depth_b = graph.find_root_ancestor("W_B")
    assert root_b == "Root_1"
    assert depth_b == 2

    root_indep, depth_indep = graph.find_root_ancestor("W_Independent")
    assert root_indep == "ExchangeHotWallet_1"
    assert depth_indep == 1

    # Compute clusters
    clusters = graph.compute_clusters()
    assert len(clusters) >= 2

    # Cluster 1 (Root_1) contains W_A, W_B, Splitter_1
    root1_cluster = next(c for c in clusters if c.root_funder == "Root_1")
    assert "W_A" in root1_cluster.wallets
    assert "W_B" in root1_cluster.wallets
    assert root1_cluster.total_token_balance == 250_000_000_000_000
    assert root1_cluster.cluster_supply_fraction == pytest.approx(0.25)
    assert root1_cluster.is_syndicate is True

    # Concentration Index: multi-wallet clusters total supply
    conc_idx = graph.calculate_cluster_concentration_index(clusters)
    assert conc_idx == pytest.approx(0.25)

    max_single = graph.get_max_single_cluster_fraction(clusters)
    assert max_single == pytest.approx(0.25)


def test_funding_cluster_graph_cycle_protection():
    graph = FundingClusterGraph(total_supply=1_000_000_000_000_000)
    # Circular funding: W_1 -> W_2 -> W_3 -> W_1
    graph.add_funding_link("W_2", "W_1", sol_amount=1.0)
    graph.add_funding_link("W_3", "W_2", sol_amount=1.0)
    graph.add_funding_link("W_1", "W_3", sol_amount=1.0)

    root, depth = graph.find_root_ancestor("W_2", max_depth=10)
    assert root in {"W_1", "W_2", "W_3"}
    assert depth <= 10


def test_sybil_wash_trading_detector_circular_and_pingpong():
    detector = SybilWashTradingDetector(max_wash_ratio=0.20, time_window_seconds=300.0)

    # Empty trade list
    verdict_empty = detector.analyze_trades([])
    assert verdict_empty.is_wash_trading is False
    assert verdict_empty.wash_volume_sol == 0.0

    # Organic non-wash trades
    organic_trades = [
        {"user": "Buyer_1", "is_buy": True, "sol_amount": 0.5, "timestamp": 100.0},
        {"user": "Buyer_2", "is_buy": True, "sol_amount": 0.8, "timestamp": 110.0},
        {"user": "Buyer_3", "is_buy": True, "sol_amount": 0.3, "timestamp": 120.0},
        {"user": "Buyer_4", "is_buy": False, "sol_amount": 0.2, "timestamp": 130.0},
    ]
    verdict_org = detector.analyze_trades(organic_trades, now=150.0)
    assert verdict_org.is_wash_trading is False
    assert verdict_org.wash_volume_ratio == 0.0

    # Coordinated ping-pong wash trading between Sybil_A and Sybil_B
    wash_trades = [
        {"user": "Sybil_A", "is_buy": True, "sol_amount": 1.0, "timestamp": 100.0},
        {"user": "Sybil_B", "is_buy": False, "sol_amount": 1.0, "timestamp": 105.0},
        {"user": "Sybil_A", "is_buy": True, "sol_amount": 1.0, "timestamp": 110.0},
        {"user": "Sybil_B", "is_buy": False, "sol_amount": 1.0, "timestamp": 115.0},
        {"user": "Sybil_A", "is_buy": True, "sol_amount": 1.0, "timestamp": 120.0},
        {"user": "Sybil_B", "is_buy": False, "sol_amount": 1.0, "timestamp": 125.0},
        {"user": "Organic_1", "is_buy": True, "sol_amount": 0.5, "timestamp": 130.0},
    ]
    verdict_wash = detector.analyze_trades(wash_trades, now=150.0)
    assert verdict_wash.is_wash_trading is True
    assert "Sybil_A" in verdict_wash.sybil_wallets
    assert "Sybil_B" in verdict_wash.sybil_wallets
    assert verdict_wash.wash_volume_ratio > 0.50
    assert verdict_wash.risk_penalty > 30.0
    assert len(verdict_wash.reasons) > 0


def test_sybil_wash_trading_detector_single_wallet_churn():
    detector = SybilWashTradingDetector(max_wash_ratio=0.20, time_window_seconds=300.0)

    # Churner repeatedly buys and sells
    churn_trades = [
        {"user": "Churner_1", "is_buy": True, "sol_amount": 0.5, "timestamp": 100.0},
        {"user": "Churner_1", "is_buy": False, "sol_amount": 0.5, "timestamp": 105.0},
        {"user": "Churner_1", "is_buy": True, "sol_amount": 0.5, "timestamp": 110.0},
        {"user": "Churner_1", "is_buy": False, "sol_amount": 0.5, "timestamp": 115.0},
        {"user": "Organic_1", "is_buy": True, "sol_amount": 1.0, "timestamp": 120.0},
    ]
    verdict = detector.analyze_trades(churn_trades, now=130.0)
    assert "Churner_1" in verdict.sybil_wallets
    assert verdict.wash_volume_sol == pytest.approx(2.0)
    assert verdict.wash_volume_ratio == pytest.approx(2.0 / 3.0)


def test_funding_cluster_analyzer_evaluation_and_verdict():
    analyzer = FundingClusterAnalyzer(
        max_cluster_concentration_pct=0.25,
        max_single_cluster_pct=0.20,
        max_sybil_wash_ratio=0.20,
    )

    # Case 1: Clean distribution with zero multi-wallet clusters
    top_holders_clean = [
        ("Holder_1", 30_000_000_000_000),
        ("Holder_2", 25_000_000_000_000),
        ("Holder_3", 20_000_000_000_000),
    ]
    graph_clean = analyzer.build_graph(
        top_holders=top_holders_clean,
        creator_wallet="Creator_1",
        creator_balance=10_000_000_000_000,
        funding_links=[
            ("Holder_1", "Binance_Hot", 1.0),
            ("Holder_2", "Coinbase_Hot", 1.0),
            ("Holder_3", "Kraken_Hot", 1.0),
        ],
    )
    verdict_clean = analyzer.evaluate("CleanMint111", graph_clean)
    assert verdict_clean.passed is True
    assert verdict_clean.risk_score == 0.0
    assert verdict_clean.cluster_concentration_index == 0.0
    assert not verdict_clean.flags.get("insider_cluster_detected")

    # Case 2: Multi-wallet syndicate controlling 35% of supply
    top_holders_syndicate = [
        ("Syndicate_1", 150_000_000_000_000),  # 15%
        ("Syndicate_2", 120_000_000_000_000),  # 12%
        ("Syndicate_3", 80_000_000_000_000),  # 8%
        ("Organic_1", 20_000_000_000_000),
    ]
    funding_links_syndicate = [
        ("Syndicate_1", "FunderRoot", 2.0),
        ("Syndicate_2", "FunderRoot", 2.0),
        ("Syndicate_3", "FunderRoot", 2.0),
    ]
    graph_syndicate = analyzer.build_graph(
        top_holders=top_holders_syndicate,
        creator_wallet="Creator_2",
        creator_balance=10_000_000_000_000,
        funding_links=funding_links_syndicate,
    )
    verdict_syndicate = analyzer.evaluate("SyndicateMint222", graph_syndicate)
    assert verdict_syndicate.passed is False
    assert verdict_syndicate.cluster_concentration_index == pytest.approx(0.35)
    assert verdict_syndicate.flags.get("insider_cluster_detected") is True
    assert verdict_syndicate.flags.get("dominant_cluster_detected") is True
    assert verdict_syndicate.risk_score >= 50.0

    verdict_dict = verdict_syndicate.to_dict()
    assert verdict_dict["mint"] == "SyndicateMint222"
    assert len(verdict_dict["clusters"]) >= 1


def test_evaluate_cluster_heuristics_and_filters_integration():
    config = make_screening(
        enable_cluster_analysis=True,
        max_cluster_concentration_pct=0.25,
        max_single_cluster_pct=0.20,
        max_sybil_wash_ratio=0.20,
    )

    analyzer = FundingClusterAnalyzer(
        max_cluster_concentration_pct=config.max_cluster_concentration_pct,
        max_single_cluster_pct=config.max_single_cluster_pct,
        max_sybil_wash_ratio=config.max_sybil_wash_ratio,
    )

    # 1. Clean token screening
    graph_clean = analyzer.build_graph(
        top_holders=[("H1", 20_000_000_000_000), ("H2", 20_000_000_000_000)],
        creator_wallet="DevClean",
        creator_balance=10_000_000_000_000,
    )
    cluster_verdict_clean = analyzer.evaluate("MintClean", graph_clean)

    screening_clean = evaluate_token_heuristics(
        config,
        "MintClean",
        dev_profile=DevWalletProfile("DevClean", tokens_launched_24h=1),
        holder_distribution=HolderDistribution(
            total_supply=1_000_000_000_000_000, top_holders=[("H1", 20_000_000_000_000)]
        ),
        cluster_analysis=cluster_verdict_clean,
    )
    assert screening_clean.passed is True
    assert screening_clean.risk_score < 20.0
    assert (
        passes_anti_rug_screening(
            config, "MintClean", cluster_analysis=cluster_verdict_clean
        )
        is True
    )

    # 2. Syndicate rejection screening
    graph_bad = analyzer.build_graph(
        top_holders=[("H1", 200_000_000_000_000), ("H2", 150_000_000_000_000)],
        creator_wallet="DevBad",
        creator_balance=10_000_000_000_000,
        funding_links=[("H1", "MasterFunder", 2.0), ("H2", "MasterFunder", 2.0)],
    )
    cluster_verdict_bad = analyzer.evaluate("MintBad", graph_bad)

    screening_bad = evaluate_token_heuristics(
        config,
        "MintBad",
        dev_profile=DevWalletProfile("DevBad", tokens_launched_24h=1),
        holder_distribution=HolderDistribution(
            total_supply=1_000_000_000_000_000,
            top_holders=[("H1", 200_000_000_000_000)],
        ),
        cluster_analysis=cluster_verdict_bad,
    )
    assert screening_bad.passed is False
    assert screening_bad.flags.get("insider_cluster_detected") is True
    assert (
        passes_anti_rug_screening(
            config, "MintBad", cluster_analysis=cluster_verdict_bad
        )
        is False
    )


def test_evaluate_cluster_graph_uses_the_screening_thresholds():
    from trading_pump.strategies.enrichment import evaluate_cluster_graph

    config = make_screening(enable_cluster_analysis=True)

    verdict = evaluate_cluster_graph(
        config,
        "MintDecision111",
        top_holders=[("W1", 100_000_000_000_000), ("W2", 100_000_000_000_000)],
        creator_wallet="Dev111",
        creator_balance=10_000_000_000_000,
        funding_links=[("W1", "BossFunder", 1.0), ("W2", "BossFunder", 1.0)],
    )
    assert verdict.mint == "MintDecision111"
    assert verdict.cluster_concentration_index == pytest.approx(0.20)


async def test_token_enricher_enrich_and_screen_with_cluster_analysis():
    from trading_pump.strategies.enrichment import TokenEnricher

    config = make_screening(
        enable_anti_rug_filters=True,
        enable_cluster_analysis=True,
        max_cluster_concentration_pct=0.25,
    )
    enricher = TokenEnricher(config=config)

    coin_data = {
        "creator": "Creator111",
        "creatorHoldingPct": 0.05,
        "totalSupply": 1_000_000_000_000_000,
        "holders": [
            {"address": "H1", "amount": 150_000_000_000_000},
            {"address": "H2", "amount": 150_000_000_000_000},
        ],
        "funding_links": [
            ("H1", "ClusterRoot", 1.0),
            ("H2", "ClusterRoot", 1.0),
        ],
    }

    verdict = await enricher.enrich_and_screen(
        "MintEnrichCluster", token_data=coin_data
    )
    assert verdict.passed is False
    assert verdict.cluster_analysis is not None
    assert verdict.cluster_analysis.cluster_concentration_index == pytest.approx(0.30)
    assert verdict.flags.get("insider_cluster_detected") is True


def test_cluster_graph_empty_and_invalid_inputs():
    graph = FundingClusterGraph()
    with pytest.raises(ValueError, match="Wallet address cannot be empty"):
        graph.add_wallet("   ")

    # Adding empty link should be safely ignored
    graph.add_funding_link("", "Root")
    graph.add_funding_link("Child", "")
    graph.add_funding_link("Same", "Same")
    assert len(graph.adj_list) == 0


def test_evaluate_cluster_heuristics_detailed_branches():
    # 1. None verdict
    passed, penalty, reasons, flags = evaluate_cluster_heuristics(None)
    assert passed is True
    assert penalty == 0.0

    # 2. Moderate concentration (between 0.10 and 0.25)
    moderate_verdict = ClusterAnalysisVerdict(
        mint="MintMod",
        passed=True,
        risk_score=15.0,
        cluster_concentration_index=0.15,
        max_single_cluster_fraction=0.12,
        total_clustered_wallets=2,
    )
    passed_mod, pen_mod, reasons_mod, _ = evaluate_cluster_heuristics(
        moderate_verdict,
        max_cluster_concentration_pct=0.25,
        max_single_cluster_pct=0.20,
    )
    assert passed_mod is True
    assert pen_mod > 0.0
    assert any("Moderate insider cluster" in r for r in reasons_mod)

    # 3. Sybil wash below threshold vs above threshold
    sybil_soft = SybilWashVerdict(
        is_wash_trading=False,
        wash_volume_sol=0.15,
        total_volume_sol=1.0,
        wash_volume_ratio=0.15,
        sybil_trade_count=2,
        sybil_wallets=["W1", "W2"],
        reasons=["Minor wash"],
    )
    assert sybil_soft.to_dict()["wash_volume_ratio"] == 0.15


@pytest.mark.regression("BUG-79")
def test_empty_wash_window_means_no_wash_activity():
    # BUG-79: stale trades must not be analysed as if they were recent
    detector = SybilWashTradingDetector(time_window_seconds=300.0)
    churn = [
        {"user": "A", "is_buy": i % 2 == 0, "sol_amount": 1.0, "timestamp": 10.0}
        for i in range(8)
    ]
    verdict = detector.analyze_trades(churn, now=1_000_000.0)
    assert verdict.is_wash_trading is False
    assert verdict.total_volume_sol == 0.0


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
