# Security policy

## Supported versions

| Version | Supported |
|---------|-----------|
| The latest `0.4.x` release (trading-pump, the trading-core module); from `v0.4.0` on, plain `vX.Y.Z` | :white_check_mark: |
| `v0.4.0rc1` to `v0.4.0rc5` (the last pre-releases) | :white_check_mark: until `v0.4.0` is tagged; runs registered on them keep their version |
| 0.3.x and older (pumpfun-trading, `pumpbot`) | :x: retired |

Fixes go into a new PATCH release (`v0.4.1`), never into a re-tagged
version ([`docs/dev/RELEASE-GATE.md` §6](docs/dev/RELEASE-GATE.md#6-versioning-policy)).

## Reporting a vulnerability

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
