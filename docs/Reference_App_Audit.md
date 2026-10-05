# Reference app audit — "Girivarsha Flood Command"

User-requested audit of `https://girivarsha-flood-command-53834287251.asia-southeast1.run.app/`
(a live SPA), done via the built-in browser after WebFetch previously could only see an
empty JS shell. Interacted with it directly: switched states/basins, opened every right-panel
tab (Overview/Sensors/Towns/Shelters/Routes), clicked "Randomize Flood," toggled the surge
overlay, and opened the alert-dispatch modal. This is an honest account of what it actually
does, not a guess from its marketing surface — see recommendations at the end for what's
actually worth porting into Girivarsha (this project) and what isn't.

## What it is

A single-page dashboard covering **17 river basins across 8 states** (Assam, Arunachal
Pradesh, Himachal Pradesh, Uttarakhand, Bihar, Kerala, Odisha, Jammu & Kashmir, West Bengal),
styled as a dark "command center." Per-basin panels: a stage hydrograph chart, catchment
telemetry (area, main river, danger stage, max historical discharge, vulnerable population),
and four tabs — Sensors, Towns, Shelters, Routes.

**Central mechanic: it's a scenario simulator, not a live system, despite saying "SYSTEM
LIVE" / "OSM LIVE" / "DATA FEED LIVE" throughout its own UI.** A prominent "Randomize Flood"
button instantly jumps to a different random basin with a freshly generated scenario (tested
live: one click moved from a Beas River (Himachal Pradesh) scenario to a Siang River
(Arunachal Pradesh) one, with different sensor readings, town names, shelter counts, and
route statuses). The "Surge" toggle draws a flood-extent polygon and changes downstream
route statuses (a route flipped from `AT_RISK` to `CLOSED / FLOODED` when surge was enabled).
Nothing observed here reads from a real, live, verifiable government feed — it's a well-built
demo generator, not a monitoring system, whatever its own badges claim.

## Feature-by-feature findings

**Multi-basin, multi-state breadth (17 basins, 8 states) vs. our 2 active + 3 planned
regions.** Real, useful contrast: their breadth comes from generated placeholder data per
basin, not from real per-village sourcing work. Our narrower footprint is the honest tradeoff
for every village/catchment/event actually being real and cited — see `docs/Region_Onboarding.md`.
Not a feature to copy; the tradeoff itself is the finding.

**"River Clearance" (town-to-river distance) as a per-town metric** — genuinely useful, and
something we don't have. Their Towns tab shows e.g. "Old Manali Riverfront — River Clearance:
0.1 km" alongside elevation and lead time. We could add a REAL version of this (haversine
distance from each seeded village to its catchment's river/stream centerline) once real
river-course geometry exists (currently blocked the same way catchment polygon delineation
is — see `docs/GIS_Methodology.md`). Worth tracking in `docs/Future_Work.md`.

**Named-road route safety status (e.g. "NH-3 Right Bank Riverway — AT_RISK, undermined by
embankment scouring")** — a real feature *idea*: road-segment-level safety status instead of
our village-hop-level `unsafe` flag. But their specific numbers (vertical clearance, scouring
assessment) are almost certainly generated, not sourced from a real road-hazard monitor —
there's no plausible real, free, live data source for "this specific highway segment is being
undermined by scouring right now." Our own evacuation routing already documents (honestly)
that it has no real road network at all (`docs/Limitations.md`). Real OSM road-network data
for these catchments remains blocked by this build environment's network restrictions (same
finding as the DEM/Overpass/OSRM attempts in `docs/GIS_Methodology.md` and `docs/Data_Sources.md`)
— worth retrying from the user's own machine, which has broader network access than this
sandbox, the same pattern already used for the DEM download.

**Shelters with capacity, current occupancy, and a "Control Room" phone number** — this is
the clearest case where their approach conflicts with this project's core rule. A shelter
with an invented capacity, a live-looking occupancy counter, and a specific phone number is
presented with no visible "simulated" label anywhere in the Shelters tab itself — it reads as
real. **This project should not copy that.** If real shelter/relief-camp data becomes
available (e.g. a real District Disaster Management Authority list, cited), it's worth adding
honestly, the same way `docs/Region_Onboarding.md` requires for everything else. Fabricated
capacity numbers and phone numbers are exactly what `docs/Limitations.md` and this project's
standing rules exist to prevent.

**The alert-dispatch modal ("Public Warning Network — Cell Broadcast & CAP Dispatch") is the
one finding worth flagging most clearly.** It drafts a push-notification-style message
formatted as if issued by `[NATIONAL DISASTER MANAGEMENT AUTHORITY – GIRIVARSHA]`, citing
India's real emergency helpline numbers (1070/1077, 112), with "Sound Civil Siren" and
"Transmit Cell Alert" buttons. To their credit, the modal itself is labelled "Simulated Cell
Broadcast Push Notification" — but a mockup that drafts text impersonating a real government
authority (NDMA is real), even labelled simulated, sits close to a line this project's own
standing rules take seriously (never impersonate a real organization; a "prototype decision-
support system, not an official government warning" disclaimer everywhere — see the top of
`README.md`). **Recommendation: do not port this feature.** If an "alert dispatch" concept is
ever wanted, it should be a clearly-labelled mockup with no NDMA-style letterhead and no
button that could be mistaken, even in a demo, for something that actually pages emergency
services.

**Minor, likely-transient UI bug observed twice:** clicking a top-nav state tab sometimes
updated the header dropdown text but left the map/telemetry panel showing the previous
state's data for a beat, and once left the map showing tiled "API KEY REQUIRED" placeholder
text instead of real tiles (their base-map provider needs a key that wasn't loading in that
moment). Both resolved on the next interaction — noted for completeness, not as something to
avoid replicating (we don't use a keyed tile provider).

## Recommendation

Two concrete, honest feature ideas worth pursuing later, both gated on the same real-data
blocker already tracked elsewhere:
1. Real river-course distance per village (needs real river-centerline geometry — same OSM/
   DEM access blocker as catchment polygons).
2. Real road-segment safety status for evacuation routing (needs real OSM road-network data
   — same access blocker, worth retrying from the user's own machine's network).

Everything else distinctive about the reference app (breadth via generated data, invented
shelters, the NDMA-styled alert mockup) is a deliberate design tradeoff this project
shouldn't make — it's the opposite of the real/simulated/derived-tagging discipline this
whole build has followed since Phase 1. Not implementing them is the honest choice, not a
missed opportunity.
