# 0002: Sensor allowlist and canonical units at ingest

Status: proposed

## Context
Car Scanner records every sensor in its list plus many app-computed extras
(fuel price, distance, averages). The recording cannot be trimmed in the app.
Raw files across three drives held 52-99 distinct names, of which only 25 are
sensors this project uses. Sources also disagree on units (mph, psi, F versus
km/h, kPa, C) and scale (the app's "equivalence ratio" is air-fuel ratio).

## Decision
- Keep a per-source allowlist that maps source names to canonical names.
- Convert every kept reading to one unit system (C, km/h, kPa, g/s, lambda).
- Drop everything else, but count what was dropped so it shows in logs.
- An unexpected unit on an allowlisted sensor raises an error instead of
  guessing, so a changed app setting cannot silently corrupt baselines.
- The raw file stays in S3 untouched, so the allowlist can change later.

## Tradeoffs
- New sensors need an allowlist entry before they appear in analysis.
- The AFR-to-lambda conversion assumes gasoline (stoichiometric 14.7).
