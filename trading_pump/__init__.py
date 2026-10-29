"""trading-pump: Pump.fun and PumpSwap on Solana as a trading-core module.

The package continues pumpfun-trading (its history is in this repository):
everything that knows Solana, Pump.fun and PumpSwap lives here, everything
that is the same on every market (risk, the circuit breaker, net-PnL
accounting, the audit trail, alerts, the dashboard) is trading-core's.
"""

__version__ = "0.4.0rc2"

from trading_core.ops.redact import register_public_identifier

from trading_pump.identifiers import is_solana_pubkey

register_public_identifier(is_solana_pubkey)
