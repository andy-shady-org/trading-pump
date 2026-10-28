# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.4.x (trading-pump, the trading-core module) | :white_check_mark: |
| 0.3.x and older (pumpfun-trading, `pumpbot`) | :x: retired |

## Reporting a Vulnerability

Please do not report security vulnerabilities publicly in GitHub.

Please contact me directly via GitHub.

## Handling secrets

* The wallet key, RPC URLs with keys and the PumpPortal key are environment
  variables only (`docs/ENVIRONMENT.md`), never settings: trading-core hashes
  the settings file into every run's provenance.
* Every URL written to a status file, log, event, alert or capture is
  redacted (trading-core redaction, BUG-102); provider keys are kept out of
  URLs that are shown (BUG-118).
* The test suite deletes every `PUMPFUN_*` and `TRADING_CORE_*` variable
  before each test and blocks the network.
