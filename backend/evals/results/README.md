# Eval Results

Each eval run writes two files here:

- `run-<UTC_ISO>.json` — full machine-readable record (per-topic scores, costs, trace).
- `run-<UTC_ISO>.md` — human-readable scorecard.

Run files are gitignored. To preserve a baseline for comparison, rename it
(e.g. `baseline-sonnet-only.json`) and commit it explicitly.
