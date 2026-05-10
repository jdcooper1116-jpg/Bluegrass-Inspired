# Bluegrass app seed pack

This seed pack was generated from the baseline packet workbook and is intended to give the Bluegrass app a fast statistical foundation without forcing the app to scan the full lottery history before it can render useful views.

## Included files
- `bluegrass_app_seed_runs.csv` — run metadata and provenance
- `bluegrass_app_seed_pairs.csv` — normalized pair analytics with run metadata joined in
- `bluegrass_app_seed_combinations.csv` — normalized combination analytics with run metadata joined in
- `bluegrass_app_priority_shortlist.csv` — derived screening queue for early UI cards and dashboards
- `bluegrass_app_seed_manifest.json` — counts, coverage, and notes

## Best app use
1. Load `runs.csv` into a baseline_runs table.
2. Load `pairs.csv` into a baseline_pairs table.
3. Load `combinations.csv` into a baseline_combinations table.
4. Use `priority_shortlist.csv` for:
   - homepage "baseline watchlist" cards
   - session-specific overdue panels
   - quick filters while the deeper engine loads
5. Keep the lottery engine as the historical source of truth. Treat this packet as a baseline layer and UI acceleration layer.

## Guardrails
- Leading zeroes are preserved in `pair_value` and `combo_value`.
- `baseline_priority_score` is only a screening heuristic built from packet metrics already supplied.
- Do not use this packet alone as the final prediction engine. Blend it with Bluegrass engine results, recent draws, and any future planetary or state-specific logic.
