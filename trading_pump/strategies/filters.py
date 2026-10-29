from __future__ import annotations

import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trading_pump.strategies.cluster import ClusterAnalysisVerdict

# Regex patterns for social links
_TWITTER_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,50})/?",
    re.IGNORECASE,
)
_TELEGRAM_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{3,50})/?",
    re.IGNORECASE,
)
_WEBSITE_PATTERN = re.compile(
    r"https?://(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/[^\s]*)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ScreeningSettings:
    """The anti-rug screen's thresholds (FEAT-04, FEAT-26).

    The same keys and defaults the pumpbot strategy config had, so a screen
    tuned there reads the same here. ``enable_anti_rug_filters`` false passes
    every token with risk score 0.
    """

    enable_anti_rug_filters: bool = True
    max_dev_24h_launches: int = 5
    max_creator_initial_holding_pct: float = 0.10
    max_top5_holder_concentration_pct: float = 0.15
    max_gini_coefficient: float = 0.85
    require_social_links: bool = False
    # Reject a token outright when no holder data could be read (BUG-107).
    require_holder_data: bool = False
    # Reject a token with fewer holder accounts than this at screening (0 = off).
    # Counts the accounts getTokenLargestAccounts returned (max 20).
    min_holder_count: int = 0
    min_social_links_count: int = 1
    max_acceptable_risk_score: float = 50.0
    screening_cache_ttl_seconds: int = 60
    enable_cluster_analysis: bool = True
    max_cluster_concentration_pct: float = 0.25
    max_single_cluster_pct: float = 0.20
    max_sybil_wash_ratio: float = 0.20
    cluster_trace_depth: int = 2

    @classmethod
    def from_mapping(cls, data: Any) -> ScreeningSettings:
        """Build from a mapping; unknown keys are an error (BUG-125).

        ``preset`` (``conservative`` / ``balanced`` / ``aggressive``) starts
        from that preset's thresholds; the other keys override it.
        """
        values = {
            k: v for k, v in dict(data or {}).items() if not str(k).startswith("_")
        }
        preset = values.pop("preset", None)
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"Unknown screening keys: {', '.join(unknown)}")
        if preset is not None:
            return cls.preset(str(preset), **values)
        return cls(**values)

    @classmethod
    def preset(cls, name: str, **overrides: Any) -> ScreeningSettings:
        """The screening thresholds of a pumpbot strategy preset, plus overrides."""
        key = str(name).strip().lower()
        if key not in SCREENING_PRESETS:
            raise ValueError(
                f"Unknown screening preset {name!r}; "
                f"use one of {', '.join(SCREENING_PRESETS)}"
            )
        return cls(**{**SCREENING_PRESETS[key], **overrides})


# The screening part of pumpbot's strategy presets (strategies/presets.py up
# to v0.3.0rc8), so a screen tuned there (the canary used ``conservative``)
# reads the same here.
SCREENING_PRESETS: dict[str, dict[str, Any]] = {
    "conservative": {
        "enable_anti_rug_filters": True,
        "max_dev_24h_launches": 2,
        "max_creator_initial_holding_pct": 0.05,
        "max_top5_holder_concentration_pct": 0.10,
        "max_gini_coefficient": 0.80,
        "require_social_links": True,
        "min_social_links_count": 2,
        "max_acceptable_risk_score": 30.0,
    },
    "balanced": {
        "enable_anti_rug_filters": True,
        "max_dev_24h_launches": 5,
        "max_creator_initial_holding_pct": 0.10,
        "max_top5_holder_concentration_pct": 0.15,
        "max_gini_coefficient": 0.85,
        "require_social_links": False,
        "min_social_links_count": 0,
        "max_acceptable_risk_score": 50.0,
    },
    "aggressive": {
        "enable_anti_rug_filters": True,
        "max_dev_24h_launches": 8,
        "max_creator_initial_holding_pct": 0.15,
        "max_top5_holder_concentration_pct": 0.25,
        "max_gini_coefficient": 0.90,
        "require_social_links": False,
        "min_social_links_count": 0,
        "max_acceptable_risk_score": 70.0,
    },
}


def _explicit_socials(data: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """Twitter, Telegram, website and Discord as the record names them."""
    twitter = (
        data.get("twitter")
        or data.get("x")
        or data.get("twitter_url")
        or data.get("x_url")
    )
    telegram = (
        data.get("telegram")
        or data.get("tg")
        or data.get("telegram_url")
        or data.get("tg_url")
    )
    website = (
        data.get("website")
        or data.get("web")
        or data.get("website_url")
        or data.get("url")
    )
    discord = data.get("discord") or data.get("discord_url")

    # Check nested extensions / links / social dictionaries if present
    extensions = data.get("extensions") or data.get("links") or data.get("socials")
    if isinstance(extensions, dict):
        twitter = twitter or extensions.get("twitter") or extensions.get("x")
        telegram = telegram or extensions.get("telegram") or extensions.get("tg")
        website = website or extensions.get("website") or extensions.get("web")
        discord = discord or extensions.get("discord")
    return twitter, telegram, website, discord


def _socials_from_description(
    description: str, twitter: Any, telegram: Any, website: Any
) -> tuple[Any, Any, Any]:
    """Links the description mentions fill the ones the record lacks."""
    found = _TWITTER_PATTERN.search(description)
    if not twitter and found:
        twitter = found.group(0)
    found = _TELEGRAM_PATTERN.search(description)
    if not telegram and found:
        telegram = found.group(0)
    if not website:
        website = _description_website(description) or website
    return twitter, telegram, website


_NOT_A_WEBSITE = ("twitter.com", "x.com", "t.me", "telegram.me", "discord")


def _description_website(description: str) -> str | None:
    """The first URL in the description that is not a social link."""
    for match in _WEBSITE_PATTERN.finditer(description):
        candidate_url = match.group(0)
        candidate_lower = candidate_url.lower()
        if not any(domain in candidate_lower for domain in _NOT_A_WEBSITE):
            return candidate_url
    return None


def _clean(value: Any) -> str | None:
    return str(value).strip() if value else None


@dataclass
class TokenMetadata:
    name: str = ""
    symbol: str = ""
    description: str = ""
    image_uri: str = ""
    metadata_uri: str = ""
    twitter: str | None = None
    telegram: str | None = None
    website: str | None = None
    discord: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenMetadata:
        if not isinstance(data, dict):
            return cls()

        name = str(data.get("name") or "").strip()
        symbol = str(data.get("symbol") or "").strip()
        description = str(data.get("description") or "").strip()
        image_uri = str(data.get("image_uri") or data.get("image") or "").strip()
        metadata_uri = str(
            data.get("metadata_uri") or data.get("uri") or data.get("metadataUri") or ""
        ).strip()

        twitter, telegram, website, discord = _explicit_socials(data)
        # Also search in description or raw text if not found explicitly
        if description:
            twitter, telegram, website = _socials_from_description(
                description, twitter, telegram, website
            )

        return cls(
            name=name,
            symbol=symbol,
            description=description,
            image_uri=image_uri,
            metadata_uri=metadata_uri,
            twitter=_clean(twitter),
            telegram=_clean(telegram),
            website=_clean(website),
            discord=_clean(discord),
            raw=data,
        )

    def social_links_count(self) -> int:
        count = 0
        if self.twitter and (
            _TWITTER_PATTERN.search(self.twitter) or len(self.twitter) > 2
        ):
            count += 1
        if self.telegram and (
            _TELEGRAM_PATTERN.search(self.telegram) or len(self.telegram) > 2
        ):
            count += 1
        if self.website and (
            _WEBSITE_PATTERN.search(self.website) or "." in self.website
        ):
            count += 1
        if self.discord and len(self.discord) > 3:
            count += 1
        return count

    def has_valid_socials(self, min_count: int = 1) -> bool:
        return self.social_links_count() >= min_count


@dataclass
class DevWalletProfile:
    creator_address: str = ""
    tokens_launched_24h: int = 0
    total_tokens_launched: int = 0
    rug_history_count: int = 0
    first_launch_timestamp: float | None = None

    def is_serial_launcher(self, max_24h: int = 5) -> bool:
        return self.tokens_launched_24h > max_24h or self.rug_history_count > 0


def calculate_gini_coefficient(balances: Sequence[int | float]) -> float:
    """Calculate the Gini coefficient over non-negative wealth/token balances.

    A Gini of 0.0 expresses maximal equality; 1.0 expresses maximal inequality.
    """
    cleaned = [float(b) for b in balances if b > 0]
    n = len(cleaned)
    if n <= 1:
        return 0.0 if n == 0 else 1.0

    cleaned.sort()
    total = sum(cleaned)  # positive: only positive balances are kept

    # Standard formula: G = sum((2*i - n - 1) * y_i) / (n * sum(y_i))
    weighted_sum = sum((2 * (i + 1) - n - 1) * val for i, val in enumerate(cleaned))
    return float(weighted_sum / (n * total))


@dataclass
class HolderDistribution:
    total_supply: int = 1_000_000_000_000_000
    creator_initial_balance: int = 0
    creator_initial_pct: float = 0.0
    top_holders: list[tuple[str, int]] = field(default_factory=list)
    bonding_curve_address: str | None = None

    def __post_init__(self) -> None:
        if (
            self.creator_initial_pct <= 0.0
            and self.total_supply > 0
            and self.creator_initial_balance > 0
        ):
            self.creator_initial_pct = float(
                self.creator_initial_balance / self.total_supply
            )

    def compute_top5_non_curve_pct(self, bonding_curve_pda: str | None = None) -> float:
        curve_addr = bonding_curve_pda or self.bonding_curve_address
        if curve_addr:
            filtered_holders = [
                (addr, bal) for addr, bal in self.top_holders if addr != curve_addr
            ]
        else:
            filtered_holders = list(self.top_holders)
        # Sort descending by balance
        filtered_holders.sort(key=lambda x: x[1], reverse=True)
        top5 = filtered_holders[:5]
        top5_sum = sum(bal for _, bal in top5)
        if self.total_supply <= 0:
            return 0.0
        return float(top5_sum / self.total_supply)

    def early_holder_cluster(self, min_share: float = 0.01) -> dict[str, float | int]:
        """Bundle proxy (FEAT-61, recorded only): wallets already holding a real
        share of supply when the token is screened, about a second after the
        create, which is mostly the create slot and the next few.

        A bundled launch has many such accounts (20+ wallets taking 30-40% in
        the create slot); an organic one has the creator and a few snipers.
        ``getTokenLargestAccounts`` returns token accounts, not owners, so the
        creator's account is matched by its initial-buy balance and left out,
        as is the bonding curve. ``early_holders`` counts the remaining
        accounts with at least ``min_share`` of supply and
        ``early_holder_pct`` is their combined share.
        """
        curve = self.bonding_curve_address
        balances = [
            int(bal) for addr, bal in self.top_holders if not (curve and addr == curve)
        ]
        creator = int(self.creator_initial_balance or 0)
        if creator <= 0 and self.creator_initial_pct > 0 and self.total_supply > 0:
            creator = int(self.creator_initial_pct * self.total_supply)
        if creator > 0 and balances:
            closest = min(balances, key=lambda bal: abs(bal - creator))
            if abs(closest - creator) <= max(1, creator // 100):
                balances.remove(closest)
        if self.total_supply <= 0:
            return {"early_holders": 0, "early_holder_pct": 0.0}
        threshold = float(min_share) * self.total_supply
        early = [bal for bal in balances if bal >= threshold]
        return {
            "early_holders": len(early),
            "early_holder_pct": round(sum(early) / self.total_supply, 6),
        }

    def compute_gini_coefficient(self, exclude_bonding_curve: bool = True) -> float:
        curve_addr = self.bonding_curve_address
        balances = [
            bal
            for addr, bal in self.top_holders
            if not (exclude_bonding_curve and curve_addr and addr == curve_addr)
        ]
        return calculate_gini_coefficient(balances)


@dataclass
class TokenScreeningVerdict:
    mint: str
    passed: bool
    risk_score: float  # 0.0 (safest) to 100.0 (maximum risk)
    reasons: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)
    dev_profile: DevWalletProfile | None = None
    holder_distribution: HolderDistribution | None = None
    metadata: TokenMetadata | None = None
    cluster_analysis: ClusterAnalysisVerdict | None = None

    @property
    def is_clean(self) -> bool:
        return self.passed and self.risk_score < 20.0


def bundle_metrics(verdict: Any) -> dict[str, float | int]:
    """The FEAT-61 bundle proxy of a screening verdict (empty without holder data)."""
    holders = getattr(verdict, "holder_distribution", None)
    if not isinstance(holders, HolderDistribution) or not holders.top_holders:
        return {}
    return holders.early_holder_cluster()


# Alias for backward-compatible naming
ScreeningVerdict = TokenScreeningVerdict


class ScreeningCache:
    """Thread-safe in-memory TTL cache for token heuristic screening results."""

    def __init__(self, default_ttl: float = 60.0, max_entries: int = 5000):
        self._default_ttl = float(default_ttl)
        self._max_entries = max(1, int(max_entries))
        self._cache: dict[str, tuple[TokenScreeningVerdict, float]] = {}
        self._lock = threading.Lock()

    def get(self, mint: str) -> TokenScreeningVerdict | None:
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(mint)
            if entry is None:
                return None
            verdict, expires_at = entry
            if now > expires_at:
                self._cache.pop(mint, None)
                return None
            return verdict

    def set(
        self,
        mint: str,
        verdict: TokenScreeningVerdict,
        ttl: float | None = None,
    ) -> None:
        effective_ttl = self._default_ttl if ttl is None else float(ttl)
        expires_at = time.monotonic() + effective_ttl
        with self._lock:
            self._cache.pop(mint, None)
            # Bound memory: drop expired entries, then the oldest (BUG-77).
            if len(self._cache) >= self._max_entries:
                now = time.monotonic()
                for key in [k for k, (_, exp) in self._cache.items() if now > exp]:
                    self._cache.pop(key, None)
            while len(self._cache) >= self._max_entries:
                self._cache.pop(next(iter(self._cache)))
            self._cache[mint] = (verdict, expires_at)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def evict_expired(self) -> int:
        now = time.monotonic()
        evicted = 0
        with self._lock:
            expired_keys = [k for k, (_, exp) in self._cache.items() if now > exp]
            for k in expired_keys:
                self._cache.pop(k, None)
                evicted += 1
        return evicted


# Global screening cache instance
_GLOBAL_SCREENING_CACHE = ScreeningCache(default_ttl=60.0)

# Risk points added per missing enrichment source; both missing exceeds the
# default max_acceptable_risk_score (50) so the screen fails closed (BUG-57).
MISSING_SCREENING_DATA_PENALTY = 30.0


def evaluate_dev_wallet(
    profile: DevWalletProfile | None,
    *,
    max_24h_launches: int = 5,
) -> tuple[bool, float, list[str]]:
    """Evaluates creator wallet activity.

    Returns (passed, penalty_score, reasons).
    """
    if profile is None or not profile.creator_address:
        return True, 0.0, []

    reasons: list[str] = []
    penalty = 0.0
    passed = True

    if profile.rug_history_count > 0:
        penalty += 50.0
        reasons.append(
            f"Dev wallet has {profile.rug_history_count} previous confirmed rug(s)"
        )
        passed = False

    if profile.tokens_launched_24h > max_24h_launches:
        excess = profile.tokens_launched_24h - max_24h_launches
        penalty += min(40.0, 25.0 + excess * 5.0)
        reasons.append(
            f"Serial launcher: {profile.tokens_launched_24h} tokens launched in last "
            f"24h (max allowed: {max_24h_launches})"
        )
        passed = False

    return passed, penalty, reasons


def evaluate_creator_holdings(
    creator_initial_pct: float,
    *,
    max_pct: float = 0.10,
) -> tuple[bool, float, list[str]]:
    """Evaluates creator initial purchase allocation in the launch block."""
    if creator_initial_pct <= 0.0:
        return True, 0.0, []

    if creator_initial_pct > max_pct:
        excess = creator_initial_pct - max_pct
        penalty = min(50.0, 30.0 + (excess / max_pct) * 20.0)
        reason = (
            f"Creator initial holding {creator_initial_pct:.1%} exceeds safety cap "
            f"{max_pct:.1%}"
        )
        return False, penalty, [reason]

    return True, 0.0, []


def evaluate_holder_distribution(
    distribution: HolderDistribution | None,
    *,
    max_top5_pct: float = 0.15,
    max_gini: float = 0.85,
    bonding_curve_pda: str | None = None,
) -> tuple[bool, float, list[str]]:
    """Evaluates top holder concentration and wealth inequality."""
    if distribution is None or not distribution.top_holders:
        return True, 0.0, []

    reasons: list[str] = []
    penalty = 0.0
    passed = True

    top5_pct = distribution.compute_top5_non_curve_pct(bonding_curve_pda)
    if top5_pct > max_top5_pct:
        excess = top5_pct - max_top5_pct
        penalty += min(35.0, 20.0 + (excess / max_top5_pct) * 15.0)
        reasons.append(
            f"Top 5 non-curve wallets hold {top5_pct:.1%} of supply (cap: "
            f"{max_top5_pct:.1%})"
        )
        passed = False

    gini = distribution.compute_gini_coefficient(exclude_bonding_curve=True)
    if gini > max_gini and len(distribution.top_holders) >= 5:
        excess_gini = gini - max_gini
        penalty += min(25.0, 15.0 + excess_gini * 20.0)
        reasons.append(
            f"High holder inequality (Gini: {gini:.2f}, max allowed: {max_gini:.2f})"
        )
        # The configured Gini cap is a hard reject (BUG-56)
        passed = False

    return passed, penalty, reasons


def evaluate_metadata_socials(
    metadata: TokenMetadata | None,
    *,
    min_social_links_count: int = 1,
    require_social_links: bool = True,
) -> tuple[bool, float, list[str]]:
    """Evaluates presence and validity of social presence (Twitter, TG, Website)."""
    if not require_social_links:
        return True, 0.0, []

    if metadata is None:
        penalty = 20.0 if require_social_links else 0.0
        return not require_social_links, penalty, ["No token metadata or socials found"]

    social_count = metadata.social_links_count()
    if social_count < min_social_links_count:
        penalty = 20.0 + (min_social_links_count - social_count) * 5.0
        reason = (
            f"Insufficient social links: found {social_count}, required at least "
            f"{min_social_links_count}"
        )
        return False, penalty, [reason]

    return True, 0.0, []


def evaluate_cluster_heuristics(
    cluster_analysis: ClusterAnalysisVerdict | None,
    *,
    max_cluster_concentration_pct: float = 0.25,
    max_single_cluster_pct: float = 0.20,
    max_sybil_wash_ratio: float = 0.20,
) -> tuple[bool, float, list[str], dict[str, Any]]:
    """Evaluates multi-wallet insider cluster concentration and sybil wash volume."""
    if cluster_analysis is None:
        return True, 0.0, [], {}

    reasons: list[str] = []
    flags: dict[str, Any] = {}
    penalty = 0.0
    passed = True

    concentration = cluster_analysis.cluster_concentration_index
    if concentration >= max_cluster_concentration_pct:
        excess = concentration - max_cluster_concentration_pct
        p = min(50.0, 30.0 + (excess / max(0.01, max_cluster_concentration_pct)) * 20.0)
        penalty += p
        reasons.append(
            f"Insider cluster concentration {concentration:.1%} exceeds limit "
            f"{max_cluster_concentration_pct:.1%}"
        )
        flags["insider_cluster_detected"] = True
        passed = False
    elif concentration > 0.10:
        penalty += concentration * 30.0
        reasons.append(
            f"Moderate insider cluster concentration: {concentration:.1%} of supply "
            "in linked wallets"
        )

    max_single = cluster_analysis.max_single_cluster_fraction
    if max_single >= max_single_cluster_pct:
        excess_single = max_single - max_single_cluster_pct
        p_single = min(
            40.0, 25.0 + (excess_single / max(0.01, max_single_cluster_pct)) * 15.0
        )
        penalty += p_single
        reasons.append(
            f"Dominant single funding cluster holds {max_single:.1%} of supply (cap: "
            f"{max_single_cluster_pct:.1%})"
        )
        flags["dominant_cluster_detected"] = True
        passed = False

    if cluster_analysis.is_sybil_wash:
        wash_ratio = cluster_analysis.wash_volume_ratio
        if wash_ratio >= max_sybil_wash_ratio:
            penalty += min(60.0, 35.0 + wash_ratio * 30.0)
            reasons.append(
                f"Sybil wash-trading confirmed: {wash_ratio:.1%} volume churn exceeds "
                f"threshold {max_sybil_wash_ratio:.1%}"
            )
            flags["sybil_wash_detected"] = True
            passed = False
        else:
            penalty += wash_ratio * 25.0

    return passed, penalty, reasons, flags


def evaluate_token_heuristics(
    config: ScreeningSettings,
    mint: str,
    *,
    metadata: TokenMetadata | dict[str, Any] | None = None,
    dev_profile: DevWalletProfile | None = None,
    holder_distribution: HolderDistribution | None = None,
    bonding_curve_pda: str | None = None,
    cluster_analysis: ClusterAnalysisVerdict | None = None,
    cache: ScreeningCache | None = None,
    use_cache: bool = True,
) -> TokenScreeningVerdict:
    """Evaluates comprehensive anti-rug, honeypot, and dev-dump heuristics."""
    active_cache = cache or _GLOBAL_SCREENING_CACHE
    if use_cache:
        cached = active_cache.get(mint)
        if cached is not None:
            return cached

    parsed_metadata = (
        metadata
        if isinstance(metadata, TokenMetadata)
        else TokenMetadata.from_dict(metadata) if isinstance(metadata, dict) else None
    )

    if not config.enable_anti_rug_filters:
        verdict = TokenScreeningVerdict(
            mint=mint,
            passed=True,
            risk_score=0.0,
            reasons=["Anti-rug filters disabled in strategy configuration"],
            timestamp=time.monotonic(),
            dev_profile=dev_profile,
            holder_distribution=holder_distribution,
            metadata=parsed_metadata,
            cluster_analysis=cluster_analysis,
        )
    else:
        verdict = _screen(
            config,
            mint,
            metadata=parsed_metadata,
            dev_profile=dev_profile,
            holder_distribution=holder_distribution,
            bonding_curve_pda=bonding_curve_pda,
            cluster_analysis=cluster_analysis,
        )

    if use_cache:
        active_cache.set(mint, verdict, ttl=config.screening_cache_ttl_seconds)

    return verdict


@dataclass
class _Score:
    """The running result of one screen."""

    total: float = 0.0
    reasons: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    hard_failed: bool = False

    def add(
        self,
        passed: bool,
        penalty: float,
        reasons: list[str],
        flag: str | None = None,
    ) -> None:
        """One check's result; a failed check is a hard reject."""
        self.total += penalty
        self.reasons.extend(reasons)
        if not passed:
            if flag is not None:
                self.flags[flag] = True
            self.hard_failed = True


def _screen(
    config: ScreeningSettings,
    mint: str,
    *,
    metadata: TokenMetadata | None,
    dev_profile: DevWalletProfile | None,
    holder_distribution: HolderDistribution | None,
    bonding_curve_pda: str | None,
    cluster_analysis: ClusterAnalysisVerdict | None,
) -> TokenScreeningVerdict:
    score = _Score()
    _missing_data(config, dev_profile, holder_distribution, score)

    # 1. Dev wallet profiling
    score.add(
        *evaluate_dev_wallet(dev_profile, max_24h_launches=config.max_dev_24h_launches),
        flag="dev_serial_launcher",
    )

    # 2. Creator initial holding allocation
    creator_pct = (
        holder_distribution.creator_initial_pct if holder_distribution else 0.0
    )
    score.add(
        *evaluate_creator_holdings(
            creator_pct, max_pct=config.max_creator_initial_holding_pct
        ),
        flag="creator_excess_holding",
    )

    # 3. Top holder concentration & Gini coefficient
    score.add(
        *evaluate_holder_distribution(
            holder_distribution,
            max_top5_pct=config.max_top5_holder_concentration_pct,
            max_gini=config.max_gini_coefficient,
            bonding_curve_pda=bonding_curve_pda,
        ),
        flag="high_holder_concentration",
    )

    # 4. Metadata and socials verification; only fails when
    # require_social_links is on: a hard reject.
    score.add(
        *evaluate_metadata_socials(
            metadata,
            min_social_links_count=config.min_social_links_count,
            require_social_links=config.require_social_links,
        ),
        flag="missing_socials",
    )

    # 5. On-Chain Funding Cluster Graph & Sybil Wash-Trading (FEAT-26)
    if config.enable_cluster_analysis and cluster_analysis is not None:
        cluster_pass, cluster_penalty, cluster_reasons, cluster_flags = (
            evaluate_cluster_heuristics(
                cluster_analysis,
                max_cluster_concentration_pct=config.max_cluster_concentration_pct,
                max_single_cluster_pct=config.max_single_cluster_pct,
                max_sybil_wash_ratio=config.max_sybil_wash_ratio,
            )
        )
        score.flags.update(cluster_flags)
        score.add(cluster_pass, cluster_penalty, cluster_reasons)

    # Normalize total risk score (0.0 to 100.0)
    normalized_risk_score = min(100.0, max(0.0, score.total))
    passed = not score.hard_failed and (
        normalized_risk_score <= config.max_acceptable_risk_score
    )

    if not passed and normalized_risk_score > config.max_acceptable_risk_score:
        score.reasons.append(
            f"Composite risk score {normalized_risk_score:.1f} exceeds threshold "
            f"{config.max_acceptable_risk_score:.1f}"
        )

    return TokenScreeningVerdict(
        mint=mint,
        passed=passed,
        risk_score=normalized_risk_score,
        reasons=score.reasons,
        flags=score.flags,
        timestamp=time.monotonic(),
        dev_profile=dev_profile,
        holder_distribution=holder_distribution,
        metadata=metadata,
        cluster_analysis=cluster_analysis,
    )


def _missing_data(
    config: ScreeningSettings,
    dev_profile: DevWalletProfile | None,
    holder_distribution: HolderDistribution | None,
    score: _Score,
) -> None:
    """Missing enrichment data must not read as a clean pass (BUG-57)."""
    if dev_profile is None or not dev_profile.creator_address:
        score.total += MISSING_SCREENING_DATA_PENALTY
        score.reasons.append("Dev wallet data unavailable")
        score.flags["missing_dev_data"] = True
    if holder_distribution is None or not holder_distribution.top_holders:
        score.total += MISSING_SCREENING_DATA_PENALTY
        score.reasons.append("Holder distribution data unavailable")
        score.flags["missing_holder_data"] = True
        if config.require_holder_data:
            # Without holders the top-5 and Gini checks cannot run (BUG-107).
            score.hard_failed = True
    min_holders = int(config.min_holder_count)
    holder_count = len(holder_distribution.top_holders) if holder_distribution else 0
    if min_holders > 0 and holder_count < min_holders:
        # In the 24 h capture, tokens with more than 5 holder accounts at
        # screening were the only group that was net positive after costs.
        score.reasons.append(
            f"Too few holders: {holder_count} holder accounts (min {min_holders})"
        )
        score.flags["too_few_holders"] = True
        score.hard_failed = True


def passes_anti_rug_screening(
    config: ScreeningSettings,
    mint: str,
    *,
    metadata: TokenMetadata | dict[str, Any] | None = None,
    dev_profile: DevWalletProfile | None = None,
    holder_distribution: HolderDistribution | None = None,
    bonding_curve_pda: str | None = None,
    cluster_analysis: ClusterAnalysisVerdict | None = None,
    cache: ScreeningCache | None = None,
) -> bool:
    """Convenience helper returning True if token passes all anti-rug checks."""
    verdict = evaluate_token_heuristics(
        config,
        mint,
        metadata=metadata,
        dev_profile=dev_profile,
        holder_distribution=holder_distribution,
        bonding_curve_pda=bonding_curve_pda,
        cluster_analysis=cluster_analysis,
        cache=cache,
    )
    return verdict.passed


__all__ = [
    "DevWalletProfile",
    "HolderDistribution",
    "ScreeningCache",
    "SCREENING_PRESETS",
    "ScreeningSettings",
    "ScreeningVerdict",
    "TokenMetadata",
    "TokenScreeningVerdict",
    "bundle_metrics",
    "calculate_gini_coefficient",
    "evaluate_cluster_heuristics",
    "evaluate_creator_holdings",
    "evaluate_dev_wallet",
    "evaluate_holder_distribution",
    "evaluate_metadata_socials",
    "evaluate_token_heuristics",
    "passes_anti_rug_screening",
]
