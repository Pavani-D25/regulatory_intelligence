# Phase 11 — Validation

`python -m regtrack.cli report` writes `reports/VALIDATION_REPORT.md`: totals, files by stage, the CLAUDE.md
regression table measured from the database, fill rate per column, required-column thresholds per population,
Qwen double-extraction agreement, open quality flags by rule, the top 20 documents needing a check, and the LLM
backlog. An assessment section (appended by hand) explains every threshold miss and flag rule.

Summary: 15/19 required columns ≥ 95 %; the 4 misses and the Qwen agreement rate depend on the LLM, which was not
reachable during the build (placeholder ngrok URL). No unexplained validator failures.

Fix made in this phase: documents without a ministry header take their issuer from the publishing source
(MoRTH / ARAI / BIS / MoPNG folders and listings; confidence 0.5) — issuer fill 92.6 % → 98.1 %; a re-run of the
affected 178 files wrote zero new rows.
