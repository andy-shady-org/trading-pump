"""On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector (FEAT-26).

This module provides graph-based wallet relationship mapping, root funding origin
tracing, insider cluster concentration indexing (0.0 to 1.0), and sybil wash-trading
pattern detection for Pump.fun token liquidity.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Sequence

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WalletNode:
    """Represents a wallet node within the funding graph."""

    address: str
    parent_address: str | None = None
    root_ancestor: str | None = None
    depth: int = 0
    token_balance: int = 0
    supply_fraction: float = 0.0
    is_creator: bool = False
    is_top_holder: bool = False
    sol_funded: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "parent_address": self.parent_address,
            "root_ancestor": self.root_ancestor,
            "depth": self.depth,
            "token_balance": self.token_balance,
            "supply_fraction": self.supply_fraction,
            "is_creator": self.is_creator,
            "is_top_holder": self.is_top_holder,
            "sol_funded": self.sol_funded,
        }


@dataclass(slots=True)
class FundingCluster:
    """Represents a cluster of wallets sharing a common funding origin."""

    root_funder: str
    wallets: list[str] = field(default_factory=list)
    total_token_balance: int = 0
    cluster_supply_fraction: float = 0.0
    max_depth: int = 0
    total_sol_funded: float = 0.0
    has_creator: bool = False
    is_syndicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_funder": self.root_funder,
            "wallets": list(self.wallets),
            "total_token_balance": self.total_token_balance,
            "cluster_supply_fraction": self.cluster_supply_fraction,
            "max_depth": self.max_depth,
            "total_sol_funded": self.total_sol_funded,
            "has_creator": self.has_creator,
            "is_syndicate": self.is_syndicate,
        }


class FundingClusterGraph:
    """Graph structure mapping funding flows and computing cluster concentration."""

    def __init__(self, total_supply: int = 1_000_000_000_000_000) -> None:
        self.total_supply = max(1, total_supply)
        self.nodes: dict[str, WalletNode] = {}
        # Directed graph: funder -> list of funded recipients with SOL amount
        self.adj_list: dict[str, list[tuple[str, float]]] = defaultdict(list)
        # Reverse mapping: recipient -> funder
        self.parent_map: dict[str, str] = {}
        self.fund_amounts: dict[tuple[str, str], float] = {}

    def add_wallet(
        self,
        address: str,
        *,
        token_balance: int = 0,
        is_creator: bool = False,
        is_top_holder: bool = False,
    ) -> WalletNode:
        """Add or update a wallet node."""
        cleaned = address.strip()
        if not cleaned:
            raise ValueError("Wallet address cannot be empty")

        supply_frac = (
            float(token_balance / self.total_supply) if self.total_supply > 0 else 0.0
        )
        if cleaned in self.nodes:
            node = self.nodes[cleaned]
            node.token_balance = token_balance
            node.supply_fraction = supply_frac
            node.is_creator = node.is_creator or is_creator
            node.is_top_holder = node.is_top_holder or is_top_holder
            return node

        node = WalletNode(
            address=cleaned,
            token_balance=token_balance,
            supply_fraction=supply_frac,
            is_creator=is_creator,
            is_top_holder=is_top_holder,
        )
        self.nodes[cleaned] = node
        return node

    def add_funding_link(
        self,
        child_wallet: str,
        funder_wallet: str,
        *,
        sol_amount: float = 0.0,
    ) -> None:
        """Record a directed funding link: funder_wallet -> child_wallet."""
        child = child_wallet.strip()
        funder = funder_wallet.strip()
        if not child or not funder or child == funder:
            return

        if child not in self.nodes:
            self.add_wallet(child)
        if funder not in self.nodes:
            self.add_wallet(funder)

        self.adj_list[funder].append((child, float(sol_amount)))
        self.parent_map[child] = funder
        self.fund_amounts[(funder, child)] = float(sol_amount)

        # Update node metadata
        self.nodes[child].parent_address = funder
        self.nodes[child].sol_funded = float(sol_amount)

    def find_root_ancestor(self, address: str, max_depth: int = 10) -> tuple[str, int]:
        """Traverse upstream funding links to find the root funding origin."""
        curr = address.strip()
        visited: set[str] = {curr}
        depth = 0

        while curr in self.parent_map and depth < max_depth:
            parent = self.parent_map[curr]
            if parent in visited:
                # Cycle detected
                break
            visited.add(parent)
            curr = parent
            depth += 1

        return curr, depth

    def compute_clusters(self, max_depth: int = 10) -> list[FundingCluster]:
        """Compute all connected funding clusters and their aggregated supply fractions."""
        # 1. Resolve root ancestor and depth for all registered nodes
        root_to_wallets: dict[str, list[str]] = defaultdict(list)
        for addr, node in self.nodes.items():
            root, depth = self.find_root_ancestor(addr, max_depth=max_depth)
            node.root_ancestor = root
            node.depth = depth
            root_to_wallets[root].append(addr)

        # 2. Build FundingCluster objects
        clusters: list[FundingCluster] = []
        for root, wallets in root_to_wallets.items():
            total_bal = sum(self.nodes[w].token_balance for w in wallets)
            supply_frac = (
                float(total_bal / self.total_supply) if self.total_supply > 0 else 0.0
            )
            max_d = max(self.nodes[w].depth for w in wallets)
            total_sol = sum(self.nodes[w].sol_funded for w in wallets)
            has_creator = any(self.nodes[w].is_creator for w in wallets)
            holder_count = sum(
                1
                for w in wallets
                if self.nodes[w].token_balance > 0
                or self.nodes[w].is_top_holder
                or self.nodes[w].is_creator
            )
            is_syndicate = (holder_count >= 2 and supply_frac >= 0.05) or (
                has_creator and holder_count >= 2
            )

            cluster = FundingCluster(
                root_funder=root,
                wallets=wallets,
                total_token_balance=total_bal,
                cluster_supply_fraction=supply_frac,
                max_depth=max_d,
                total_sol_funded=total_sol,
                has_creator=has_creator,
                is_syndicate=is_syndicate,
            )
            clusters.append(cluster)

        # Sort clusters by supply fraction descending
        clusters.sort(key=lambda c: c.cluster_supply_fraction, reverse=True)
        return clusters

    def calculate_cluster_concentration_index(
        self,
        clusters: Sequence[FundingCluster] | None = None,
        *,
        min_cluster_wallets: int = 2,
    ) -> float:
        """Calculate the Insider Cluster Concentration Index (0.0 to 1.0).

        Measures what fraction of the total token supply is held by multi-wallet
        clusters (clusters with >= min_cluster_wallets token holders or creator-linked clusters).
        """
        active_clusters = clusters if clusters is not None else self.compute_clusters()
        clustered_supply = 0.0
        for c in active_clusters:
            holder_count = sum(
                1
                for w in c.wallets
                if self.nodes.get(w)
                and (
                    self.nodes[w].token_balance > 0
                    or self.nodes[w].is_top_holder
                    or self.nodes[w].is_creator
                )
            )
            if holder_count >= min_cluster_wallets:
                clustered_supply += c.cluster_supply_fraction

        return float(min(1.0, max(0.0, clustered_supply)))

    def get_max_single_cluster_fraction(
        self,
        clusters: Sequence[FundingCluster] | None = None,
    ) -> float:
        """Return the maximum supply fraction held by any single multi-wallet cluster."""
        active_clusters = clusters if clusters is not None else self.compute_clusters()
        multi_holder_clusters = [
            c
            for c in active_clusters
            if sum(
                1
                for w in c.wallets
                if self.nodes.get(w)
                and (
                    self.nodes[w].token_balance > 0
                    or self.nodes[w].is_top_holder
                    or self.nodes[w].is_creator
                )
            )
            >= 2
        ]
        if not multi_holder_clusters:
            return 0.0
        return float(max(c.cluster_supply_fraction for c in multi_holder_clusters))


@dataclass(slots=True)
class SybilWashVerdict:
    """Detailed verdict from sybil wash-trading and circular flow detection."""

    is_wash_trading: bool
    wash_volume_sol: float
    total_volume_sol: float
    wash_volume_ratio: float
    sybil_trade_count: int
    sybil_wallets: list[str] = field(default_factory=list)
    detected_cycles_count: int = 0
    reasons: list[str] = field(default_factory=list)
    risk_penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_wash_trading": self.is_wash_trading,
            "wash_volume_sol": self.wash_volume_sol,
            "total_volume_sol": self.total_volume_sol,
            "wash_volume_ratio": self.wash_volume_ratio,
            "sybil_trade_count": self.sybil_trade_count,
            "sybil_wallets": list(self.sybil_wallets),
            "detected_cycles_count": self.detected_cycles_count,
            "reasons": list(self.reasons),
            "risk_penalty": self.risk_penalty,
        }


class SybilWashTradingDetector:
    """Analyzes trade streams on a bonding curve for circular and sybil wash-trading patterns."""

    def __init__(
        self,
        *,
        max_wash_ratio: float = 0.20,
        min_cycle_length: int = 2,
        max_cycle_length: int = 6,
        time_window_seconds: float = 300.0,
    ) -> None:
        self.max_wash_ratio = float(max_wash_ratio)
        self.min_cycle_length = int(min_cycle_length)
        self.max_cycle_length = int(max_cycle_length)
        self.time_window_seconds = float(time_window_seconds)

    def analyze_trades(
        self,
        trades: Sequence[dict[str, Any]],
        *,
        cluster_graph: FundingClusterGraph | None = None,
        now: float | None = None,
    ) -> SybilWashVerdict:
        """Analyze a sequence of trade events for sybil wash-trading patterns."""
        if not trades:
            return SybilWashVerdict(
                is_wash_trading=False,
                wash_volume_sol=0.0,
                total_volume_sol=0.0,
                wash_volume_ratio=0.0,
                sybil_trade_count=0,
                sybil_wallets=[],
                detected_cycles_count=0,
                reasons=[],
                risk_penalty=0.0,
            )

        current_time = float(now if now is not None else time.time())
        cutoff_time = current_time - self.time_window_seconds

        # Filter trades within analysis window
        recent_trades: list[dict[str, Any]] = []
        for t in trades:
            ts = float(t.get("timestamp") or current_time)
            if ts >= cutoff_time:
                recent_trades.append(t)

        if not recent_trades:
            recent_trades = list(trades)

        total_sol_volume = sum(
            float(t.get("sol_amount") or t.get("amount_sol") or 0.0)
            for t in recent_trades
        )

        sybil_wallets: set[str] = set()
        sybil_trade_indices: set[int] = set()
        detected_cycles = 0
        reasons: list[str] = []

        # 1. Clustered wallet coordination check
        if cluster_graph is not None:
            clusters = cluster_graph.compute_clusters()
            syndicate_wallets = {
                w for c in clusters if len(c.wallets) >= 2 for w in c.wallets
            }
            if syndicate_wallets:
                # Check for rapid buy-sell micro swaps between syndicate members
                for i, t in enumerate(recent_trades):
                    user = str(t.get("user") or t.get("wallet_address") or "").strip()
                    if user in syndicate_wallets:
                        sybil_wallets.add(user)
                        sybil_trade_indices.add(i)

        # 2. Cyclic buy/sell pattern detection (e.g. A buys -> B buys -> A sells -> B sells)
        wallet_sequence = [
            (
                str(t.get("user") or t.get("wallet_address") or "").strip(),
                bool(t.get("is_buy", True)),
                float(t.get("sol_amount") or t.get("amount_sol") or 0.0),
                float(t.get("timestamp") or 0.0),
            )
            for t in recent_trades
        ]

        # Detect alternating ping-pong trades between pairs of wallets
        pair_trade_counts: dict[tuple[str, str], int] = defaultdict(int)
        for i in range(len(wallet_sequence) - 1):
            w1, buy1, amt1, _ = wallet_sequence[i]
            w2, buy2, amt2, _ = wallet_sequence[i + 1]
            if w1 and w2 and w1 != w2:
                pair = (w1, w2) if w1 < w2 else (w2, w1)
                pair_trade_counts[pair] += 1
                if pair_trade_counts[pair] >= 3:
                    # Alternating ping-pong detected
                    sybil_wallets.add(w1)
                    sybil_wallets.add(w2)
                    sybil_trade_indices.add(i)
                    sybil_trade_indices.add(i + 1)
                    detected_cycles += 1

        # 3. Detect rapid round-trip churn: Same wallet buying and selling repeatedly with near zero profit
        wallet_actions: dict[str, list[tuple[int, bool, float]]] = defaultdict(list)
        for idx, (w, is_buy, amt, _) in enumerate(wallet_sequence):
            if w:
                wallet_actions[w].append((idx, is_buy, amt))

        for w, actions in wallet_actions.items():
            if len(actions) >= 4:
                buys = sum(1 for _, is_buy, _ in actions if is_buy)
                sells = sum(1 for _, is_buy, _ in actions if not is_buy)
                if buys >= 2 and sells >= 2:
                    # Rapid churning detected
                    sybil_wallets.add(w)
                    for idx, _, _ in actions:
                        sybil_trade_indices.add(idx)
                    detected_cycles += 1

        # Compute wash volume
        wash_volume_sol = sum(
            float(
                recent_trades[i].get("sol_amount")
                or recent_trades[i].get("amount_sol")
                or 0.0
            )
            for i in sybil_trade_indices
        )

        wash_ratio = (
            float(wash_volume_sol / total_sol_volume) if total_sol_volume > 0.0 else 0.0
        )
        is_wash = (wash_ratio >= self.max_wash_ratio and len(sybil_wallets) >= 2) or (
            detected_cycles >= 2 and wash_ratio >= 0.15
        )

        penalty = 0.0
        if is_wash:
            penalty = min(60.0, 30.0 + wash_ratio * 40.0)
            reasons.append(
                f"Sybil wash-trading detected: {wash_ratio:.1%} of volume is coordinated across {len(sybil_wallets)} wallets ({detected_cycles} cycles)"
            )
        elif wash_ratio > 0.10:
            penalty = wash_ratio * 20.0
            reasons.append(
                f"Elevated wash trading activity: {wash_ratio:.1%} volume churn detected"
            )

        return SybilWashVerdict(
            is_wash_trading=is_wash,
            wash_volume_sol=wash_volume_sol,
            total_volume_sol=total_sol_volume,
            wash_volume_ratio=wash_ratio,
            sybil_trade_count=len(sybil_trade_indices),
            sybil_wallets=sorted(sybil_wallets),
            detected_cycles_count=detected_cycles,
            reasons=reasons,
            risk_penalty=penalty,
        )


@dataclass(slots=True)
class ClusterAnalysisVerdict:
    """Composite screening verdict for funding clusters and sybil volume."""

    mint: str
    passed: bool
    risk_score: float  # 0.0 (safe) to 100.0 (high risk)
    cluster_concentration_index: float  # 0.0 to 1.0
    max_single_cluster_fraction: float  # 0.0 to 1.0
    total_clustered_wallets: int
    clusters: list[FundingCluster] = field(default_factory=list)
    is_sybil_wash: bool = False
    wash_volume_ratio: float = 0.0
    sybil_verdict: SybilWashVerdict | None = None
    reasons: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "passed": self.passed,
            "risk_score": self.risk_score,
            "cluster_concentration_index": self.cluster_concentration_index,
            "max_single_cluster_fraction": self.max_single_cluster_fraction,
            "total_clustered_wallets": self.total_clustered_wallets,
            "clusters": [c.to_dict() for c in self.clusters],
            "is_sybil_wash": self.is_sybil_wash,
            "wash_volume_ratio": self.wash_volume_ratio,
            "sybil_verdict": (
                self.sybil_verdict.to_dict() if self.sybil_verdict else None
            ),
            "reasons": list(self.reasons),
            "flags": dict(self.flags),
            "timestamp": self.timestamp,
        }


class FundingClusterAnalyzer:
    """Orchestrates funding graph building and multi-factor cluster risk evaluation."""

    def __init__(
        self,
        *,
        max_cluster_concentration_pct: float = 0.25,
        max_single_cluster_pct: float = 0.20,
        max_sybil_wash_ratio: float = 0.20,
        cluster_trace_depth: int = 2,
    ) -> None:
        self.max_cluster_concentration_pct = float(max_cluster_concentration_pct)
        self.max_single_cluster_pct = float(max_single_cluster_pct)
        self.max_sybil_wash_ratio = float(max_sybil_wash_ratio)
        self.cluster_trace_depth = int(cluster_trace_depth)
        self.wash_detector = SybilWashTradingDetector(
            max_wash_ratio=self.max_sybil_wash_ratio
        )

    def build_graph(
        self,
        top_holders: Sequence[tuple[str, int]] | None = None,
        *,
        creator_wallet: str | None = None,
        creator_balance: int = 0,
        total_supply: int = 1_000_000_000_000_000,
        funding_links: Sequence[tuple[str, str, float]] | None = None,
    ) -> FundingClusterGraph:
        """Construct a FundingClusterGraph from top holders, creator, and funding edges."""
        graph = FundingClusterGraph(total_supply=total_supply)

        if creator_wallet:
            graph.add_wallet(
                creator_wallet,
                token_balance=creator_balance,
                is_creator=True,
            )

        if top_holders:
            for addr, bal in top_holders:
                if addr:
                    is_creator = bool(creator_wallet and addr == creator_wallet)
                    graph.add_wallet(
                        addr,
                        token_balance=bal,
                        is_creator=is_creator,
                        is_top_holder=True,
                    )

        if funding_links:
            for child, funder, sol in funding_links:
                if child and funder:
                    graph.add_funding_link(child, funder, sol_amount=sol)

        return graph

    def evaluate(
        self,
        mint: str,
        graph: FundingClusterGraph,
        *,
        trades: Sequence[dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> ClusterAnalysisVerdict:
        """Evaluate cluster concentration and wash trading for a token."""
        clusters = graph.compute_clusters(max_depth=self.cluster_trace_depth)
        concentration_index = graph.calculate_cluster_concentration_index(clusters)
        max_single_fraction = graph.get_max_single_cluster_fraction(clusters)

        # Multi-wallet clusters (clusters linking >= 2 token-holding wallets / creator)
        multi_wallet_clusters = [
            c
            for c in clusters
            if sum(
                1
                for w in c.wallets
                if graph.nodes.get(w)
                and (
                    graph.nodes[w].token_balance > 0
                    or graph.nodes[w].is_top_holder
                    or graph.nodes[w].is_creator
                )
            )
            >= 2
        ]
        total_clustered_wallets = sum(len(c.wallets) for c in multi_wallet_clusters)

        # Sybil wash evaluation
        sybil_verdict: SybilWashVerdict | None = None
        if trades:
            sybil_verdict = self.wash_detector.analyze_trades(
                trades, cluster_graph=graph, now=now
            )

        reasons: list[str] = []
        flags: dict[str, Any] = {}
        risk_score = 0.0
        hard_failed = False

        # 1. Total cluster concentration evaluation
        if concentration_index >= self.max_cluster_concentration_pct:
            excess = concentration_index - self.max_cluster_concentration_pct
            penalty = min(
                50.0,
                30.0 + (excess / max(0.01, self.max_cluster_concentration_pct)) * 20.0,
            )
            risk_score += penalty
            reasons.append(
                f"Insider cluster concentration {concentration_index:.1%} exceeds limit {self.max_cluster_concentration_pct:.1%} ({len(multi_wallet_clusters)} syndicate clusters detected)"
            )
            flags["insider_cluster_detected"] = True
            hard_failed = True
        elif concentration_index > 0.10:
            risk_score += concentration_index * 30.0
            reasons.append(
                f"Moderate insider cluster concentration: {concentration_index:.1%} of supply in linked wallets"
            )

        # 2. Single dominant cluster evaluation
        if max_single_fraction >= self.max_single_cluster_pct:
            excess_single = max_single_fraction - self.max_single_cluster_pct
            penalty_single = min(
                40.0,
                25.0 + (excess_single / max(0.01, self.max_single_cluster_pct)) * 15.0,
            )
            risk_score += penalty_single
            reasons.append(
                f"Dominant single funding cluster holds {max_single_fraction:.1%} of supply (cap: {self.max_single_cluster_pct:.1%})"
            )
            flags["dominant_cluster_detected"] = True
            hard_failed = True

        # 3. Sybil wash trading evaluation
        is_sybil_wash = False
        wash_ratio = 0.0
        if sybil_verdict is not None:
            is_sybil_wash = sybil_verdict.is_wash_trading
            wash_ratio = sybil_verdict.wash_volume_ratio
            risk_score += sybil_verdict.risk_penalty
            if sybil_verdict.reasons:
                reasons.extend(sybil_verdict.reasons)
            if is_sybil_wash:
                flags["sybil_wash_detected"] = True
                hard_failed = True

        normalized_risk_score = min(100.0, max(0.0, risk_score))
        passed = not hard_failed and normalized_risk_score < 50.0

        return ClusterAnalysisVerdict(
            mint=mint,
            passed=passed,
            risk_score=normalized_risk_score,
            cluster_concentration_index=concentration_index,
            max_single_cluster_fraction=max_single_fraction,
            total_clustered_wallets=total_clustered_wallets,
            clusters=clusters,
            is_sybil_wash=is_sybil_wash,
            wash_volume_ratio=wash_ratio,
            sybil_verdict=sybil_verdict,
            reasons=reasons,
            flags=flags,
            timestamp=time.monotonic(),
        )


__all__ = [
    "ClusterAnalysisVerdict",
    "FundingCluster",
    "FundingClusterAnalyzer",
    "FundingClusterGraph",
    "SybilWashTradingDetector",
    "SybilWashVerdict",
    "WalletNode",
]
