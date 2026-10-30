# Historical Astra decision experiment

The September 2026 run asks a fresh GPT-6 Astra agent to select portfolios at each of 60 historical cutoffs. Each agent receives one packet, containing only ten trailing price/volume features, market context, and eligibility identifiers. Both the diverse 100-stock cohort and the full current S&P roster use the same dates and accounting as the five-year quantitative comparison.

The main run hides stock names and calendar dates. Six additional fresh agents receive named versions of six selected snapshots. Those paired controls are isolated holding periods, not a continuous five-year portfolio.

## Run order

Use `.venv-prediction-lab/bin/python` from the repository root. The existing source is `.research-artifacts/prediction-wide-2026-09-07`. Always prepare a new output directory for a new experiment; do not overwrite the September 2026 decisions.

1. `scripts/research/prepare_astra_capsules.py --source SOURCE --output NEW_OUTPUT` builds packets and evaluator-only mappings.
2. Store and hash the decision contract before starting agents. Spawn one fresh-context `gpt-6-astra` agent per packet. Restrict it to its assigned packet and the contract; require the defined selection JSON, formula/rationale, and hindsight disclosure.
3. `scripts/research/evaluate_astra_capsules.py status --root OUTPUT` checks counts, membership, IDs, and schema without reading outcome prices.
4. Export observable agent tool calls using `scripts/research/audit_astra_access.py --root OUTPUT --sessions SESSION_DIRECTORY`. Review flags and actual calls. Export the parent task dispatch metadata to `spawn-receipts.json` and document automatically injected context in `context-limitations.json`; both are required before freezing. Stored task bodies may be encrypted. The transcript export excludes private reasoning and system instructions.
5. Once every decision is complete, `scripts/research/evaluate_astra_capsules.py freeze --root OUTPUT` hashes all decisions. Never give agents performance feedback before this step or permit performance-based retries.
6. `scripts/research/evaluate_astra_capsules.py score --root OUTPUT --source SOURCE` replays holdings at 11 and 22 bps per side, checks the original universe and dates, and independently verifies portfolio accounting.
7. `scripts/research/report_astra_capsules.py --root OUTPUT` creates the report, CSV, charts, code snapshot, and manifest.

The actual experiment contract is retained in the artifact directory; preparation alone is not an executed model test. The scripts do not call a broker or configure the paper scheduler.

## Interpretation

The result measures the model's choices using the supplied price/volume information and a fixed top-third, fully invested mandate. It does not measure unrestricted company research, a model actually available in 2021, or an uncontaminated historical investment record. Learned history cannot be erased, and packet-only instructions on a shared filesystem are not an operating-system security boundary.

Current-roster survivorship and revised adjusted-price data are inherited from the source experiment. Historical index membership and vintage news/fundamentals need separate qualification. The named controls can reveal sensitivity to recognizable identities, but cannot isolate hindsight from ordinary response variability. No result establishes future profitability.

The actual run discovered that fresh forks still receive automatic project memory context, including an earlier Chronos baseline result. This is documented in `context-limitations.json` before scoring. Parent spawn metadata confirms fresh Astra tasks; stored message bodies are encrypted, so they do not provide independently readable exact task prompts. The common contract and observable tool inputs are retained. Never describe this run as a clean-room historical simulation.
