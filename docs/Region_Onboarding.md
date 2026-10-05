# Region Onboarding

How a real Himalayan valley moves from `status: "planned"` to `status: "active"` in the region registry (`GET /regions`, `backend/app/models/orm.py::Region`). This is the real checklist — not aspirational — because Mandakini Valley and the Chamoli Disaster Valley have both actually been taken through it (see `scripts/seed_pilot_region.py` and `scripts/seed_chamoli_valley.py`).

## Why this exists

Before Phase 11, Girivarsha's schema, API, and frontend all implicitly assumed exactly one pilot valley. That doesn't scale to "all flash-flood-prone villages in northern India" — a real ask, but one that can't be honestly satisfied by inventing coordinates for thousands of villages. The region registry is the deliberate middle path: a real architecture that can *hold* many valleys, populated only as far as real sourcing work has actually gone. A `planned` region proves the data model scales to a place; it never claims village-level coverage that doesn't exist yet. See `docs/Data_Sources.md`'s "Rules this repo follows" — this onboarding process is how that rule stays true as the registry grows.

## Step 0 — is this a real, well-documented flash-flood/landslide-prone valley?

Before writing any code, confirm the candidate valley has:

- A real, citable historical flash-flood, landslide, or GLOF event (news coverage, a government/NDMA report, a peer-reviewed reconnaissance report, or at minimum a solid Wikipedia article with sources). No event history, no region row — a valley without a documented disaster doesn't yet have anything to seed.
- A real river/drainage system with a documented or inferable upstream→downstream order (a Wikipedia river article naming the villages/towns it passes is normally enough).

If this bar isn't met yet, the valley isn't ready to become even a `planned` region — just note it as a candidate and move on.

## Step 1 — add it as a `planned` region (cheap, honest, do this first)

This alone is real, useful work: it proves the registry scales, and it's a citable placeholder for later sourcing effort. Add an entry to `REGIONS` in `scripts/seed_regions.py`:

```python
dict(
    name="<Real valley name>",
    states="<Indian state(s)>",
    description="<what/where it is, and the real disaster that makes it relevant, one or two sentences>",
    status="planned",
    catchment_name=None,   # no catchment/villages seeded yet
    provenance="<Wikipedia or other citation for the event>, fetched <date>. No village-level data sourced yet — see docs/Region_Onboarding.md.",
),
```

Re-run `python scripts/seed_regions.py`. `GET /regions` will now list it honestly: real name, real state, real cited event, `village_count: 0`. Stop here unless you're doing the full village-sourcing pass below — a `planned` entry is a legitimate, complete piece of work on its own.

## Step 2 — full sourcing pass (to reach `active`)

This is what actually happened for Chamoli — use `scripts/seed_chamoli_valley.py` as the reference template, and `docs/Data_Sources.md`'s "Second pilot valley" section as the reference for how it should be written up afterward.

1. **Pick 4-8 real villages/settlements** along the valley's real river course, upstream to downstream, that are actually named in your sources (the historical-event report, the river's Wikipedia article, or district administrative data). Do not invent village names or positions to fill a round number.
2. **Source each village's elevation and coordinates**, and honestly tag `coordinate_precision`:
   - `surveyed` — the source states an exact coordinate (a Wikipedia infobox, a GPS reading in an engineering report, official survey data).
   - `approximate` — elevation is sourced but coordinates were interpolated along the documented river path between two `surveyed` anchor points (the same method used for 4 of Mandakini's 6 villages — see `docs/Data_Sources.md`). Never present an interpolated point as `surveyed`.
   - If neither elevation nor position can be sourced at all for a place you want to include, leave it out rather than guess.
3. **Write a `provenance` string per village** — the actual citation (URL + what it states), not a generic "sourced from Wikipedia." Flag any specific caveat inline (see Joshimath's entry in `scripts/seed_chamoli_valley.py` for the pattern: a real, concrete data-quality problem stated plainly rather than smoothed over).
4. **Seed at least one real historical event**, tied to the village where it's best documented, with `severity` and a real `source_citation`. A region with zero historical events can still be `active` (village data is real either way), but it won't be useful to the risk engine's historical-susceptibility component or to any future ML training set until it has one.
5. **Leave `population` null** unless you can verify a real per-settlement figure — same rule as Chamoli. A plausible-looking guess is worse than an honest gap.
6. **Write the seed script** (copy `scripts/seed_chamoli_valley.py`'s structure): one `MicroCatchment` row (`source=DataSource.DERIVED`, with its own `provenance` explaining the topology source), one `Village` row per settlement (`source=DataSource.REAL`), one `HistoricalEvent` row per real event. Make it idempotent (check for an existing catchment by name and refuse to double-seed, as the template does).
7. **Run the seed script**, then update (or add) the region's row in `scripts/seed_regions.py`: flip `status` to `"active"` and set `catchment_name` to the new catchment's name so `seed_regions.py` links it. Re-run `seed_regions.py`.
8. **Verify via the API**, not just the DB: `GET /regions` shows the new region `active` with the right `village_count`; `GET /villages?region_id=<id>` returns exactly the new villages; `GET /risk/map?region_id=<id>` computes real scores for all of them without error; `GET /risk/{id}` for at least one village returns a sane `lead_time_note` (check whether the elevation-order upstream proxy picked a sensible village — if it picked something topologically backwards, as it did for Joshimath, document that explicitly rather than silently adjusting the data to hide it).
9. **Write it up in `docs/Data_Sources.md`** using the Chamoli section as the template: a table of villages with elevation/precision/source, the historical event, and any known limitation discovered along the way.
10. **Add backend tests** mirroring `tests/backend/test_regions.py`'s Chamoli-scoped assertions (village count, region scoping, no cross-region leakage, the historical event's citation) so this region's data stays correct as the codebase evolves.
11. **Run the full test suite** (`pytest tests/backend tests/gis tests/ml`) and the frontend suite (`npm run build`, `npx vitest run`) before considering the region done.

## What NOT to do

- Don't fabricate coordinates, elevations, or population figures to hit a round village count.
- Don't silently "clean up" a real data quirk (like Joshimath's elevation) to make an algorithm's output look more sensible than the underlying data actually supports — document it instead.
- Don't mark a region `active` with fewer than roughly 3-4 real villages — below that there's not enough topology for the "upstream" proxy or lead-time estimate to mean anything, and it's honestly still closer to `planned`.
- Don't skip the historical event if one exists and is findable — a region with real villages but zero event history is a strictly weaker version of what Mandakini and Chamoli both are.

## Known architectural gap this doesn't fix

Sensors (`GET /sensors`) and alerts (`GET /alerts`) have no server-side `?region_id=` filter yet — see `docs/Limitations.md`'s Phase 11 section. Onboarding a new region's IoT sensors, if that ever happens, will need that filter added; today the frontend only scopes them client-side against the selected region's village IDs.
