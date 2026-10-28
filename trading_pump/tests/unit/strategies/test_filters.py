import pytest

from trading_pump.strategies import filters as filters_module
from trading_pump.strategies.decision import TradingStrategy
from trading_pump.strategies.filters import (
    DevWalletProfile,
    HolderDistribution,
    ScreeningCache,
    TokenMetadata,
    TokenScreeningVerdict,
    calculate_gini_coefficient,
    evaluate_creator_holdings,
    evaluate_dev_wallet,
    evaluate_holder_distribution,
    evaluate_metadata_socials,
    evaluate_token_heuristics,
    passes_anti_rug_screening,
)
from trading_pump.strategies.presets import resolve_strategy_config
from trading_pump.tests.support.factories import make_config
from trading_pump.tests.support.fakes import FakeClock


def test_token_metadata_parsing():
    # Empty or invalid input
    empty_meta = TokenMetadata.from_dict({})
    assert empty_meta.name == ""
    assert empty_meta.social_links_count() == 0
    assert not empty_meta.has_valid_socials(min_count=1)

    non_dict_meta = TokenMetadata.from_dict("invalid")  # type: ignore
    assert non_dict_meta.name == ""

    # Direct social keys
    direct_data = {
        "name": "SuperCoin",
        "symbol": "SUP",
        "description": "Awesome meme token",
        "image_uri": "https://pump.fun/images/sup.png",
        "metadata_uri": "https://ipfs.io/ipfs/Qm123",
        "twitter": "https://x.com/SuperCoinSol",
        "telegram": "https://t.me/SuperCoinPortal",
        "website": "https://supercoin.xyz",
        "discord": "https://discord.gg/supercoin",
    }
    meta = TokenMetadata.from_dict(direct_data)
    assert meta.name == "SuperCoin"
    assert meta.symbol == "SUP"
    assert meta.twitter == "https://x.com/SuperCoinSol"
    assert meta.telegram == "https://t.me/SuperCoinPortal"
    assert meta.website == "https://supercoin.xyz"
    assert meta.discord == "https://discord.gg/supercoin"
    assert meta.social_links_count() == 4
    assert meta.has_valid_socials(min_count=1)
    assert meta.has_valid_socials(min_count=3)

    # Nested extensions / links / socials dictionary
    nested_data = {
        "name": "NestedCoin",
        "extensions": {
            "x": "https://twitter.com/nested_sol",
            "tg": "https://t.me/nested_tg",
            "web": "https://nested.io",
        },
    }
    nested_meta = TokenMetadata.from_dict(nested_data)
    assert nested_meta.social_links_count() == 3

    # Regex extraction from description text
    text_data = {
        "name": "RegexCoin",
        "description": "Check us out at https://x.com/regex_sol and join https://t.me/regex_portal or visit https://regexcoin.org",
    }
    extracted_meta = TokenMetadata.from_dict(text_data)
    assert extracted_meta.twitter is not None and "regex_sol" in extracted_meta.twitter
    assert (
        extracted_meta.telegram is not None
        and "regex_portal" in extracted_meta.telegram
    )
    assert (
        extracted_meta.website is not None and "regexcoin.org" in extracted_meta.website
    )
    assert extracted_meta.social_links_count() == 3


def test_dev_wallet_profiling():
    # Empty or default profile
    empty_profile = DevWalletProfile()
    assert not empty_profile.is_serial_launcher(max_24h=5)

    passed, penalty, reasons = evaluate_dev_wallet(None)
    assert passed
    assert penalty == 0.0
    assert len(reasons) == 0

    clean_dev = DevWalletProfile(
        creator_address="Dev11111111111111111111111111111111111111111",
        tokens_launched_24h=1,
        total_tokens_launched=2,
        rug_history_count=0,
    )
    assert not clean_dev.is_serial_launcher(max_24h=5)
    passed, penalty, reasons = evaluate_dev_wallet(clean_dev, max_24h_launches=5)
    assert passed
    assert penalty == 0.0
    assert len(reasons) == 0

    # Serial launcher exceeding 24h limit
    serial_dev = DevWalletProfile(
        creator_address="Dev22222222222222222222222222222222222222222",
        tokens_launched_24h=8,
        total_tokens_launched=20,
        rug_history_count=0,
    )
    assert serial_dev.is_serial_launcher(max_24h=5)
    passed, penalty, reasons = evaluate_dev_wallet(serial_dev, max_24h_launches=5)
    assert not passed
    assert penalty > 0.0
    assert any("Serial launcher" in r for r in reasons)

    # Confirmed rugger
    rugger_dev = DevWalletProfile(
        creator_address="Dev33333333333333333333333333333333333333333",
        tokens_launched_24h=2,
        total_tokens_launched=5,
        rug_history_count=2,
    )
    assert rugger_dev.is_serial_launcher(max_24h=5)
    passed, penalty, reasons = evaluate_dev_wallet(rugger_dev, max_24h_launches=5)
    assert not passed
    assert penalty >= 50.0
    assert any("previous confirmed rug" in r for r in reasons)


def test_gini_coefficient_calculation():
    # Empty or single balance
    assert calculate_gini_coefficient([]) == 0.0
    assert calculate_gini_coefficient([1000]) == 1.0
    assert calculate_gini_coefficient([0, 0, 0]) == 0.0
    assert calculate_gini_coefficient([-10, -5]) == 0.0

    # Perfectly equal distribution
    equal_gini = calculate_gini_coefficient([100, 100, 100, 100, 100])
    assert equal_gini == 0.0

    # Skewed distribution
    skewed_gini = calculate_gini_coefficient([1, 1, 1, 1, 1000])
    assert skewed_gini > 0.75
    assert skewed_gini <= 1.0


def test_holder_distribution_evaluation():
    total_supply = 1_000_000_000_000_000
    curve_pda = "BondingCurve11111111111111111111111111111111"

    # Default/empty distribution
    empty_dist = HolderDistribution()
    assert empty_dist.compute_top5_non_curve_pct() == 0.0
    passed, penalty, reasons = evaluate_holder_distribution(None)
    assert passed
    assert penalty == 0.0

    # Zero total supply edge case
    zero_supply_dist = HolderDistribution(total_supply=0, top_holders=[("A", 100)])
    assert zero_supply_dist.compute_top5_non_curve_pct() == 0.0

    # Well-distributed holders
    distributed = HolderDistribution(
        total_supply=total_supply,
        creator_initial_balance=30_000_000_000_000,  # 3%
        bonding_curve_address=curve_pda,
        top_holders=[
            (curve_pda, 800_000_000_000_000),  # 80% in curve
            ("Wallet1", 20_000_000_000_000),  # 2%
            ("Wallet2", 15_000_000_000_000),  # 1.5%
            ("Wallet3", 10_000_000_000_000),  # 1.0%
            ("Wallet4", 10_000_000_000_000),  # 1.0%
            ("Wallet5", 10_000_000_000_000),  # 1.0%
        ],
    )
    assert distributed.creator_initial_pct == pytest.approx(0.03, rel=1e-3)
    top5_pct = distributed.compute_top5_non_curve_pct()
    assert top5_pct == pytest.approx(0.065, rel=1e-3)  # 6.5% non-curve

    passed, penalty, reasons = evaluate_holder_distribution(
        distributed,
        max_top5_pct=0.15,
        max_gini=0.85,
    )
    assert passed
    assert penalty == 0.0
    assert len(reasons) == 0

    # Extreme inequality Gini > 0.95 (requires large holder count with single whale)
    extreme_gini_dist = HolderDistribution(
        total_supply=total_supply,
        bonding_curve_address=curve_pda,
        top_holders=[
            (curve_pda, 800_000_000_000_000),
            ("Whale", 140_000_000_000_000),  # 14% (under 15% top 5 cap)
            *[(f"W{i}", 1) for i in range(25)],
        ],
    )
    passed, penalty, reasons = evaluate_holder_distribution(
        extreme_gini_dist,
        max_top5_pct=0.15,
        max_gini=0.80,
    )
    assert not passed
    assert penalty > 0.0
    assert any("High holder inequality" in r for r in reasons)

    # Concentrated holders (top 5 holding 25% of supply)
    concentrated = HolderDistribution(
        total_supply=total_supply,
        creator_initial_balance=100_000_000_000_000,
        bonding_curve_address=curve_pda,
        top_holders=[
            (curve_pda, 700_000_000_000_000),
            ("Whale1", 100_000_000_000_000),  # 10%
            ("Whale2", 60_000_000_000_000),  # 6%
            ("Whale3", 40_000_000_000_000),  # 4%
            ("Whale4", 30_000_000_000_000),  # 3%
            ("Whale5", 20_000_000_000_000),  # 2%
        ],
    )
    assert concentrated.compute_top5_non_curve_pct() == pytest.approx(0.25, rel=1e-3)
    passed, penalty, reasons = evaluate_holder_distribution(
        concentrated,
        max_top5_pct=0.15,
        max_gini=0.85,
    )
    assert not passed
    assert penalty > 0.0
    assert any("Top 5 non-curve wallets" in r for r in reasons)


def test_creator_holding_cap_evaluation():
    # Safe holding (<10%)
    passed, penalty, reasons = evaluate_creator_holdings(0.04, max_pct=0.10)
    assert passed
    assert penalty == 0.0
    assert len(reasons) == 0

    # Zero or negative
    passed, penalty, reasons = evaluate_creator_holdings(0.0, max_pct=0.10)
    assert passed

    # Excessive holding (>10%)
    passed, penalty, reasons = evaluate_creator_holdings(0.18, max_pct=0.10)
    assert not passed
    assert penalty >= 30.0
    assert any("Creator initial holding" in r for r in reasons)


def test_metadata_socials_evaluation():
    # Require social links False
    passed, penalty, reasons = evaluate_metadata_socials(
        None, require_social_links=False
    )
    assert passed
    assert penalty == 0.0

    # Require social links True, but metadata is None
    passed, penalty, reasons = evaluate_metadata_socials(
        None, require_social_links=True
    )
    assert not passed
    assert penalty > 0.0

    # Insufficient socials
    single_link_meta = TokenMetadata(twitter="https://x.com/SolToken")
    passed, penalty, reasons = evaluate_metadata_socials(
        single_link_meta, min_social_links_count=2, require_social_links=True
    )
    assert not passed
    assert penalty > 0.0
    assert any("Insufficient social links" in r for r in reasons)

    # Valid socials
    multi_link_meta = TokenMetadata(
        twitter="https://x.com/SolToken",
        telegram="https://t.me/SolTokenPortal",
        website="https://soltoken.xyz",
    )
    passed, penalty, reasons = evaluate_metadata_socials(
        multi_link_meta, min_social_links_count=2, require_social_links=True
    )
    assert passed
    assert penalty == 0.0


def test_screening_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    clock.install(monkeypatch, filters_module)
    cache = ScreeningCache(default_ttl=1.0)
    assert cache.size() == 0

    verdict = TokenScreeningVerdict(mint="Mint1", passed=True, risk_score=10.0)
    cache.set("Mint1", verdict, ttl=0.1)
    cache.set("MintExpired", verdict, ttl=0.05)
    assert cache.size() == 2
    assert cache.get("Mint1") == verdict

    # Expiry
    clock.advance(0.15)
    assert cache.evict_expired() == 2
    assert cache.get("Mint1") is None
    assert cache.evict_expired() == 0

    # Re-insert and clear
    cache.set("Mint2", verdict, ttl=10.0)
    assert cache.size() == 1
    cache.clear()
    assert cache.size() == 0


def test_full_heuristic_screening_pipeline():
    config = resolve_strategy_config("balanced")
    mint = "TestMint11111111111111111111111111111111111"
    cache = ScreeningCache(default_ttl=60.0)

    # Clean token passing all criteria
    clean_meta = TokenMetadata(
        twitter="https://x.com/CleanMint",
        telegram="https://t.me/CleanMint",
        website="https://cleanmint.io",
    )
    clean_dev = DevWalletProfile(
        creator_address="DevClean",
        tokens_launched_24h=1,
        rug_history_count=0,
    )
    clean_holders = HolderDistribution(
        total_supply=1_000_000_000,
        creator_initial_balance=30_000_000,  # 3%
        top_holders=[
            ("DevClean", 30_000_000),
            ("User1", 10_000_000),
            ("User2", 10_000_000),
        ],
    )

    verdict = evaluate_token_heuristics(
        config,
        mint,
        metadata=clean_meta,
        dev_profile=clean_dev,
        holder_distribution=clean_holders,
        cache=cache,
    )
    assert verdict.passed
    assert verdict.risk_score == 0.0
    assert verdict.is_clean
    assert len(verdict.reasons) == 0

    # Cached lookup
    cached_verdict = evaluate_token_heuristics(config, mint, cache=cache)
    assert cached_verdict == verdict

    # Toxic token: Serial rugger with 20% creator holding
    toxic_mint = "ToxicMint222222222222222222222222222222222"
    toxic_dev = DevWalletProfile(
        creator_address="DevScam",
        tokens_launched_24h=10,
        rug_history_count=1,
    )
    toxic_holders = HolderDistribution(
        total_supply=1_000_000_000,
        creator_initial_balance=200_000_000,  # 20%
        top_holders=[("DevScam", 200_000_000)],
    )

    toxic_verdict = evaluate_token_heuristics(
        config,
        toxic_mint,
        metadata=None,
        dev_profile=toxic_dev,
        holder_distribution=toxic_holders,
        cache=cache,
    )
    assert not toxic_verdict.passed
    assert toxic_verdict.risk_score >= 50.0
    assert not toxic_verdict.is_clean
    assert toxic_verdict.flags.get("dev_serial_launcher") is True
    assert toxic_verdict.flags.get("creator_excess_holding") is True

    # Check convenience function
    assert passes_anti_rug_screening(
        config,
        mint,
        metadata=clean_meta,
        dev_profile=clean_dev,
        holder_distribution=clean_holders,
        cache=cache,
    )
    assert not passes_anti_rug_screening(
        config,
        toxic_mint,
        metadata=None,
        dev_profile=toxic_dev,
        holder_distribution=toxic_holders,
        cache=cache,
    )


def test_disabled_anti_rug_filters():
    config = resolve_strategy_config(
        "balanced",
        overrides={"enable_anti_rug_filters": False},
    )

    verdict = evaluate_token_heuristics(
        config,
        "AnyMint",
        metadata=None,
        use_cache=False,
    )
    assert verdict.passed
    assert verdict.risk_score == 0.0
    assert "disabled" in verdict.reasons[0].lower()


def test_trading_strategy_screen_token_integration():
    config = resolve_strategy_config("conservative")
    assert config.enable_anti_rug_filters is True
    assert config.max_creator_initial_holding_pct == 0.05
    assert config.min_social_links_count == 2

    strategy = TradingStrategy(config)
    verdict = strategy.screen_token(
        "ConservativeTestMint",
        metadata={
            "twitter": "https://x.com/SafeToken",
            "telegram": "https://t.me/SafeToken",
        },
        dev_profile=DevWalletProfile(creator_address="SafeDev", tokens_launched_24h=1),
        holder_distribution=HolderDistribution(creator_initial_pct=0.02),
        use_cache=False,
    )
    assert verdict.passed

    # Summary includes anti-rug keys
    summary = strategy.summary()
    assert summary["enable_anti_rug_filters"] is True
    assert summary["max_creator_initial_holding_pct"] == 0.05
    assert summary["max_top5_holder_concentration_pct"] == 0.10
    assert summary["max_gini_coefficient"] == 0.80

    # token_is_eligible with screening verdict
    eligible = strategy.is_eligible_for_buy(
        market_cap_sol=35.0,
        mint_seen_recently=False,
        buy_attempts=0,
        screening_verdict=verdict,
    )
    assert eligible

    failed_verdict = TokenScreeningVerdict(
        mint="BadMint", passed=False, risk_score=80.0
    )
    ineligible = strategy.is_eligible_for_buy(
        market_cap_sol=35.0,
        mint_seen_recently=False,
        buy_attempts=0,
        screening_verdict=failed_verdict,
    )
    assert not ineligible


@pytest.mark.regression("BUG-77")
def test_screening_cache_is_bounded():
    """BUG-77: the screening cache evicts the oldest entry at capacity."""
    cache = ScreeningCache(default_ttl=60.0, max_entries=2)
    verdict = TokenScreeningVerdict(mint="m", passed=True, risk_score=0.0)
    for mint in ("a", "b", "c"):
        cache.set(mint, verdict)
    assert cache.size() == 2
    assert cache.get("a") is None and cache.get("c") is verdict
    cache.set("d", verdict, ttl=-1.0)
    cache.set("e", verdict)
    assert cache.size() == 2


@pytest.mark.regression("BUG-56")
def test_gini_above_configured_cap_is_hard_reject():
    # BUG-56: 0.85 < G <= 0.95 used to be a soft penalty only
    holders = [("whale", 1_000_000)] + [(f"w{i}", 1) for i in range(9)]
    dist = HolderDistribution(top_holders=holders)
    assert 0.85 < dist.compute_gini_coefficient() <= 0.95
    passed, _, reasons = evaluate_holder_distribution(dist, max_gini=0.85)
    assert passed is False
    assert any("Gini" in r for r in reasons)


@pytest.mark.regression("BUG-57")
def test_missing_dev_and_holder_data_fails_closed():
    # BUG-57
    config = make_config(
        dry_run=False, enable_anti_rug_filters=True, require_social_links=False
    )
    verdict = evaluate_token_heuristics(config, "NoDataMint", use_cache=False)
    assert verdict.passed is False
    assert verdict.flags["missing_dev_data"] is True
    assert verdict.flags["missing_holder_data"] is True

    partial = evaluate_token_heuristics(
        config,
        "PartialMint",
        dev_profile=DevWalletProfile(creator_address="Dev1"),
        use_cache=False,
    )
    assert partial.passed is True
    assert partial.flags["missing_holder_data"] is True


def _holders(accounts: int) -> HolderDistribution:
    curve = "CurveAccount1111111111111111111111111111111"
    return HolderDistribution(
        total_supply=1_000_000_000,
        creator_initial_balance=1_000_000,
        bonding_curve_address=curve,
        top_holders=[(curve, 900_000_000)]
        + [(f"Wallet{i}", 1_000_000) for i in range(max(0, accounts - 1))],
    )


@pytest.mark.parametrize(
    ("min_holder_count", "accounts", "passes"),
    [
        (0, 2, True),  # off by default
        (6, 5, False),
        (6, 6, True),
        (6, 20, True),
        (6, 0, False),  # no holder data is not "enough holders"
    ],
)
def test_min_holder_count_rejects_tokens_below_the_threshold(
    min_holder_count: int, accounts: int, passes: bool
) -> None:
    config = make_config(
        min_holder_count=min_holder_count, max_acceptable_risk_score=100.0
    )
    verdict = evaluate_token_heuristics(
        config,
        f"HolderMint{min_holder_count}x{accounts}",
        metadata=TokenMetadata(twitter="https://x.com/t"),
        dev_profile=DevWalletProfile(creator_address="Dev", tokens_launched_24h=1),
        holder_distribution=_holders(accounts) if accounts else None,
        use_cache=False,
    )

    assert verdict.passed is passes
    rejected = any(r.startswith("Too few holders") for r in verdict.reasons)
    assert rejected is (min_holder_count > 0 and not passes)
    assert bool(verdict.flags.get("too_few_holders")) is rejected


def test_early_holder_cluster_leaves_out_the_curve_and_the_creator() -> None:
    supply = 1_000_000_000_000_000
    holders = HolderDistribution(
        total_supply=supply,
        creator_initial_balance=50_000_000_000_000,  # 5%
        bonding_curve_address="Curve",
        top_holders=[
            ("Curve", 800_000_000_000_000),
            ("CreatorAta", 50_100_000_000_000),  # within 1% of the initial buy
            ("Sniper1", 30_000_000_000_000),
            ("Sniper2", 20_000_000_000_000),
            ("Dust", 5_000_000_000_000),  # 0.5%: below the 1% line
        ],
    )

    assert holders.early_holder_cluster() == {
        "early_holders": 2,
        "early_holder_pct": 0.05,
    }
    assert holders.early_holder_cluster(min_share=0.001)["early_holders"] == 3


def test_early_holder_cluster_falls_back_to_the_creator_share() -> None:
    supply = 1_000_000
    by_pct = HolderDistribution(
        total_supply=supply,
        creator_initial_pct=0.1,
        top_holders=[("A", 100_000), ("B", 200_000)],
    )
    assert by_pct.early_holder_cluster() == {
        "early_holders": 1,
        "early_holder_pct": 0.2,
    }
    # No account near the creator's balance: nothing is left out.
    unmatched = HolderDistribution(
        total_supply=supply,
        creator_initial_balance=500_000,
        top_holders=[("A", 100_000)],
    )
    assert unmatched.early_holder_cluster()["early_holders"] == 1
    empty_supply = HolderDistribution(total_supply=0, top_holders=[("A", 1)])
    assert empty_supply.early_holder_cluster() == {
        "early_holders": 0,
        "early_holder_pct": 0.0,
    }


def test_bundle_metrics_needs_holder_data() -> None:
    from trading_pump.strategies.filters import bundle_metrics

    verdict = TokenScreeningVerdict(mint="m", passed=True, risk_score=0.0)
    assert bundle_metrics(verdict) == {}
    assert bundle_metrics(None) == {}
    verdict.holder_distribution = HolderDistribution(
        total_supply=100, top_holders=[("A", 10)]
    )
    assert bundle_metrics(verdict) == {"early_holders": 1, "early_holder_pct": 0.1}
