"""trading-pump: Pump.fun and PumpSwap on Solana as a trading-core module.

The package continues pumpfun-trading (its history is in this repository):
everything that knows Pump.fun and PumpSwap lives here; the Solana plumbing
every Solana module shares (the RPC pool, the transaction transport, Jito,
costs, mint decoding, the program-subscribe feed) is trading-solana's, and
everything that is the same on every market (risk, the circuit breaker,
net-PnL accounting, the audit trail, alerts, the dashboard, the capture
writer, the stream loop, the replay harness) is trading-core's.
"""

__version__ = "0.6.0"

# Importing trading-solana registers its Solana public-key test with
# trading-core's redaction, so a mint or wallet in a URL is never masked as
# a key (BUG-102); trading-pump registered its own copy until 0.5.0.
import trading_solana  # noqa: F401
