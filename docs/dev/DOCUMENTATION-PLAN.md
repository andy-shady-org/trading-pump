# Documentation Plan: Gap Analysis & Material Docs Site

This plan covers two things: the gaps found in the current documentation, and how the docs will be published as a Material Design styled site with **Zensical** (Material for MkDocs as fallback) and embedded in the Web UI at `/docs`. The decision is ADR-007 in [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md). All gap fixes are scheduled in **Sprint 31: Documentation Site & Gap Closure** in [`TODO.md`](TODO.md); the in-app embedding lands in Sprint 35 (FEAT-37).

> Nothing in this plan is built yet. `mkdocs.yml` is outlined in §5 and will be created in Sprint 31.

---

## 1. Current Inventory

| Area | Files |
|---|---|
| Root | `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `AGENTS.md` |
| User & operator (`docs/`) | `USER-GUIDE.md`, `ENVIRONMENTAL-VARIABLES.md`, `CLI-COMMANDS.md`, `STRATEGY.md`, `RISK.md`, `TERMINAL-UI.md`, `WEB-UI.md`, `FEATURES.md`, `REPLAY-ENGINE.md`, `AUDIT-TOOL.md` |
| Developer (`docs/dev/`) | `README.md`, `TODO.md`, `BUGS.md`, `PROPOSED-FEATURES.md`, `RUNBOOK.md`, `RELEASE-GATE.md`, `ARCHITECTURE-DECISIONS.md`, `TESTING.md`, `DOCUMENTATION-PLAN.md` |

---

## 2. Gap Analysis

Every gap is fixed in Sprint 31 unless noted.

| # | Gap | Location | Fix | Sprint |
|---|---|---|---|---|
| D1 | No site config, landing page or navigation | repo root, `docs/` | Add `mkdocs.yml` and `docs/index.md` (§4, §5) | 31 |
| D2 | Diagrams are ASCII art | `TERMINAL-UI.md`, `USER-GUIDE.md`, `STRATEGY.md`, `RISK.md`, others | Convert flow/topology diagrams to Mermaid; keep the terminal screenshot-style layout in `TERMINAL-UI.md` as a `text` block | 31 |
| D3 | No front matter, admonitions or content tabs | all pages | Add YAML front matter (`title`, `description`, `tags`); convert "Note/Warning" paragraphs to admonitions; tabs for operator vs hosted instructions | 31 |
| D4 | `FEAT-12` used twice | `docs/FEATURES.md` (§3 "Execution & On-Chain Solana SDK" and §19 "Core Runtime Decomposition") | Renumber one entry to a free ID and update all references | 31 |
| D5 | Unimplemented FEAT-10 listed as a feature | `docs/FEATURES.md` §13 | Move to "Planned" with a link to `dev/PROPOSED-FEATURES.md` (FEAT-10 umbrella, FEAT-31…37) | 31 |
| D6 | `WEB-UI.md` specified React/Tailwind with no API/auth or multi-tenant spec | `docs/WEB-UI.md` | **Done** in this planning pass (Vuetify MD3, Mermaid, draft API, tenant isolation) | – |
| D7 | 30-day plan framed as "pre-production" although the bot is in production | `docs/dev/NEXT-30-DAYS.md` (removed) | **Done:** retired; paper-pilot procedure, drills and command matrix moved to `RUNBOOK.md`, gates rewritten in `RELEASE-GATE.md` (release gate + live capital gate) | – |
| D8 | Thin runbook (67 lines) | `docs/dev/RUNBOOK.md` | **Partly done:** runtime layout, paper pilot, drills, daily wallet reconciliation, rollback and command reference added. Still to add: key rotation, profit-sweep procedure (manual until FEAT-42), Geyser/Jito outage playbooks, circuit-breaker reset | 31 |
| D9 | Missing architecture overview | – | New `docs/ARCHITECTURE.md`: package map, data flow (stream → strategy → risk → execution), Mermaid diagrams; links ADRs | 31 |
| D10 | Missing deployment guide | – | New `docs/DEPLOYMENT.md`: systemd unit, Docker/compose (FEAT-46), secrets handling, log retention | 31 |
| D11 | Missing troubleshooting / FAQ | – | New `docs/TROUBLESHOOTING.md` built from `BUGS.md` symptoms and common operator errors | 31 |
| D12 | Missing glossary | – | New `docs/GLOSSARY.md` (bonding curve, virtual reserves, PDA, ATA, Jito tip, Gini, moonbag, …) | 31 |
| D13 | No CHANGELOG or versioning policy | – | SemVer policy **done** in `RELEASE-GATE.md` §6; `CHANGELOG.md` (Keep a Changelog) still to create | 25 |
| D14 | No API / SDK reference | – | mkdocstrings pages for `sdk/`, `strategies/`, `streams/`, `execution/`, `api/` | 31 |
| D15 | `README.md` and `USER-GUIDE.md` overlap | `README.md`, `docs/USER-GUIDE.md` | README becomes a short overview + quickstart linking to the site; `USER-GUIDE.md` stays the full onboarding guide | 31 |
| D16 | Stale references in the backlog | `docs/dev/TODO.md` (`docs/REFACTOR.md`, `pumpfun_trading/cli.py`, `pumpfun_trading/filters/`) | **Done** in this planning pass | – |
| D17 | `AGENTS.md` package map missing `infra/`; dev docs list incomplete | `AGENTS.md` | **Done** in this planning pass | – |
| D18 | No test-suite guide | – | **Done**: `docs/dev/TESTING.md` | – |
| D19 | Heading structure not checked for site navigation (every page already has exactly one H1) | all pages | Keep one H1 per page; H2 for sections; fix skipped levels so the generated TOC is clean | 31 |
| D20 | Contextual help anchors for Web UI settings do not exist | `STRATEGY.md`, `RISK.md`, `ENVIRONMENTAL-VARIABLES.md` | Add stable heading IDs (`{#tp-tier-1}` style) for every config field the Web UI links to | 31 |

---

## 3. Tooling Choice

| Option | Status | Use |
|---|---|---|
| **Zensical** | Successor to Material for MkDocs; reads `mkdocs.yml` natively | Primary builder |
| **Material for MkDocs** | Maintenance mode (security fixes until its announced EOL) | Fallback builder; config kept compatible |
| **mkdocstrings[python]** | – | API/SDK reference from docstrings |

Rules: keep `mkdocs.yml` Material-compatible; avoid plugins Zensical does not support yet; build in strict mode in CI so broken links fail the build.

---

## 4. Target Site Navigation

```text
Home                          docs/index.md
Getting Started
  ├── Installation & Quickstart   docs/USER-GUIDE.md (setup sections)
  └── Configuration               docs/ENVIRONMENTAL-VARIABLES.md
User Guide                    docs/USER-GUIDE.md
Strategy & Risk
  ├── Strategy                    docs/STRATEGY.md
  └── Risk                        docs/RISK.md
Tools
  ├── Replay Engine               docs/REPLAY-ENGINE.md
  └── Audit Tool                  docs/AUDIT-TOOL.md
Operations
  ├── Terminal UI                 docs/TERMINAL-UI.md
  ├── Deployment                  docs/DEPLOYMENT.md        (new)
  ├── Runbook                     docs/dev/RUNBOOK.md
  └── Troubleshooting             docs/TROUBLESHOOTING.md   (new)
Web UI                        docs/WEB-UI.md
Reference
  ├── CLI Commands                docs/CLI-COMMANDS.md
  ├── Environment Variables       docs/ENVIRONMENTAL-VARIABLES.md
  ├── Features                    docs/FEATURES.md
  ├── Architecture                docs/ARCHITECTURE.md      (new)
  ├── API / SDK                   docs/reference/*.md       (mkdocstrings, new)
  └── Glossary                    docs/GLOSSARY.md          (new)
Developers
  ├── Portal                      docs/dev/README.md
  ├── Architecture Decisions      docs/dev/ARCHITECTURE-DECISIONS.md
  ├── Testing                     docs/dev/TESTING.md
  ├── Backlog                     docs/dev/TODO.md
  ├── Proposed Features           docs/dev/PROPOSED-FEATURES.md
  ├── Bugs                        docs/dev/BUGS.md
  ├── Release Gate                docs/dev/RELEASE-GATE.md
  └── Documentation Plan          docs/dev/DOCUMENTATION-PLAN.md
```

In the hosted Web UI the **Developers** section can be hidden from `viewer` users by building a second, user-only nav profile.

---

## 5. Planned `mkdocs.yml` Outline (not created yet)

```yaml
site_name: pumpfun-trading
site_url: https://<host>/docs/
repo_url: https://github.com/andy-shady-org/pumpfun-trading
docs_dir: docs
strict: true

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.instant
    - navigation.top
    - search.suggest
    - search.highlight
    - content.code.copy
    - content.tabs.link
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: custom
      toggle: { icon: material/brightness-7, name: Switch to dark mode }
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: custom
      toggle: { icon: material/brightness-4, name: Switch to light mode }

extra_css:
  - assets/md3-tokens.css   # MD3 colour tokens shared with the Vuetify theme

markdown_extensions:
  - admonition
  - attr_list
  - md_in_html
  - tables
  - toc: { permalink: true }
  - pymdownx.details
  - pymdownx.superfences:
      custom_fences:
        - { name: mermaid, class: mermaid, format: !!python/name:pymdownx.superfences.fence_code_format }
  - pymdownx.tabbed: { alternate_style: true }
  - pymdownx.arithmatex: { generic: true }   # STRATEGY.md math
  - pymdownx.highlight
  - pymdownx.inlinehilite

plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          options: { show_source: false, docstring_style: google }

nav: []   # filled from §4
```

---

## 6. Styling Conventions

1. **Front matter** on every page:
   ```yaml
   ---
   title: Risk Management
   description: Position, portfolio and circuit-breaker controls.
   tags: [risk, operator]
   ---
   ```
2. **One H1 per page**, matching `title`; sections start at H2; no skipped levels.
3. **Mermaid instead of ASCII** for flows, topologies, state machines and sequences. Plain `text` blocks only for terminal output.
4. **Admonitions** for callouts: `!!! warning` for capital risk, `!!! danger` for key/secret handling, `!!! note` / `!!! tip` for guidance.
5. **Content tabs** where instructions differ by mode (`=== "Operator (terminal)"` / `=== "Hosted (Web UI)"`) or by OS.
6. **Relative links** between pages (`../RISK.md`), never absolute GitHub URLs; strict build catches breakage.
7. **Stable anchors** for every config field referenced by the Web UI settings page.
8. **Math** with `$…$` / `$$…$$` (arithmatex); units always stated (SOL, lamports, µSOL).
9. **Tables** for parameter references (name, type, default, env var, description).
10. **Material Design 3 palette** via `assets/md3-tokens.css`, generated from the same seed colour as the Vuetify theme, so `/docs` and the dashboard look like one product; light/dark follows the system.

---

## 7. Sprint 31 Checklist

- [ ] D1 site config + landing page
- [ ] D2 Mermaid conversion
- [ ] D3 front matter, admonitions, tabs
- [ ] D4 FEAT-12 duplicate resolved
- [ ] D5 FEAT-10 moved to planned
- [x] D7 NEXT-30-DAYS retired
- [ ] D8 RUNBOOK expansion finished (key rotation, profit sweep, outage playbooks, breaker reset)
- [ ] D9–D12 new pages (architecture, deployment, troubleshooting, glossary)
- [ ] D14 API/SDK reference
- [ ] D15 README / USER-GUIDE de-duplicated
- [ ] D19 heading levels checked
- [ ] D20 stable config anchors
- [ ] Strict build passes in CI (`zensical build` or `mkdocs build --strict`)
