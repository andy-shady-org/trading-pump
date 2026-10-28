# trading-pump

The Pump.fun / PumpSwap module for [trading-core](https://github.com/andy-shady-org/trading-core):
it follows every coin that graduates from its Pump.fun bonding curve to
PumpSwap, reads the pools on chain, trades one pre-registered lane in paper
with every fee priced in, and records everything for replay. The engine
(risk, circuit breaker, accounting, audit, alerts, dashboard) is
trading-core's.

```bash
pip install -e ../trading-core && pip install -e ".[dev]"
export PUMPFUN_RPC_URL="https://<your-rpc>/?api-key=..."
cp configs/paper.example.json configs/paper.json
trading-core check --config configs/paper.json
trading-core run --config configs/paper.json        # paper trading on live graduations
trading-pump replay --config configs/paper.json --capture data/paper/capture.jsonl --out data/replay-1
```

| Lane | What it trades | Default |
|---|---|---|
| **pumpswap_momentum** (FEAT-76) | A coin still at ≥ 1.2× its first PumpSwap price 60 s after graduating; out at +20%, −15% or 30 minutes | on in `configs/paper.example.json`, paper only |
| graduation capture (FEAT-73) | Nothing: every graduate's pool for 4 h, recorded | always on |

- Every pumpfun-trading lane before it was measured NO-GO in paper (launch
  buying alone on about 25,000 trades); this one replays at +1.1% per trade on the data it came
  from, which is not evidence yet ([docs/STRATEGY.md](docs/STRATEGY.md)).
- Live orders are refused until the lane passes paper
  ([docs/dev/RELEASE-GATE.md](docs/dev/RELEASE-GATE.md)).
- This repository continues **pumpfun-trading**: its full history from
  2026-10-09 and every release tag from `v0.0.1-alpha` to `v0.3.0rc8`; its
  documents are kept in
  [docs/archive/pumpfun-trading](docs/archive/pumpfun-trading/INDEX.md).
- Start with [docs/USER-GUIDE.md](docs/USER-GUIDE.md).

Python 3.11–3.14, 100% branch coverage. Proprietary; private use only (see
`LICENSE`).
