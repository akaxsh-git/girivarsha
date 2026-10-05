# scripts/

One-off/dev utility scripts (DB seeding, data download, etc.), added as each phase needs them.

- `seed_pilot_region.py` (Phase 2) — seeds the real, sourced Mandakini valley pilot-region villages and the 2013 Kedarnath historical event. Run once against a freshly-migrated database: `cd backend && source .venv/bin/activate && python ../scripts/seed_pilot_region.py`. Refuses to run twice against a non-empty `villages` table (see the script for why, and how to reseed).
