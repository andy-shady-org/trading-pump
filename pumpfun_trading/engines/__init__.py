"""Engine and simulation modules for historical evaluation and paper trading."""

from .generators import RestHistoryExporter, SyntheticReplayGenerator
from .replay import (
    PaperTradingEngine,
    ReplayEngine,
    render_replay_dashboard,
    render_replay_summary,
    render_replay_trades,
    run_replay,
)

__all__ = [
    "PaperTradingEngine",
    "ReplayEngine",
    "SyntheticReplayGenerator",
    "RestHistoryExporter",
    "run_replay",
    "render_replay_summary",
    "render_replay_trades",
    "render_replay_dashboard",
]
