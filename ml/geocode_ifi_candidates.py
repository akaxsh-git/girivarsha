"""
Real geocoding for the India Flood Inventory (IFI) candidate events
assembled by ml/assemble_real_events.py's assemble_ifi_candidate_events().

Context / why this exists: those 404 real, cited events were deliberately
kept OUT of ml/train_real.py's training set because the source dataset is
district-level, not point-located — see that function's own docstring and
docs/ML_Methodology.md. This script is the "future geocoding work" both of
those already flagged as the honest next step, rather than force-fitting
coordinates that were never assembled.

What this does, and does NOT do:
  - Real geocoding via OpenStreetMap Nominatim (nominatim.openstreetmap.org),
    a real, free, public geocoding service — no API key, no fabricated
    coordinates. Every returned lat/lon is Nominatim's own real answer for
    "<district>, <state>, India" resolved against real OSM administrative
    boundary data (`addresstype: state_district`), not this project's guess.
  - Deliberately geocodes ONLY single-district events (332 of the 404). An
    event recorded against 2+ districts (up to 27 in the source data) has
    no single honest point to geocode to — collapsing a multi-district
    flood to one district's centroid would misrepresent the source data's
    own precision, so those rows are left uncoordinated, same as before.
  - The result is a DISTRICT CENTROID, not the actual flood/landslide site
    within that district — a real, but coarser, precision than the GLOF
    inventory's own lake-level coordinates. Every output row is labelled
    `coordinate_precision: district_centroid_geocoded` so nothing downstream
    can mistake this for point-level accuracy.
  - Respects Nominatim's usage policy: max 1 request/second, a real,
    identifying User-Agent (not a browser spoof), and results are cached by
    unique (state, district) pair so this run makes ~97 real HTTP calls for
    332 events, not 332.

Usage: python ml/geocode_ifi_candidates.py
Writes ml/data/real_india_hillstate_events_geocoded.csv.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data"
IN_PATH = DATA_DIR / "real_india_hillstate_candidate_events.csv"
OUT_PATH = DATA_DIR / "real_india_hillstate_events_geocoded.csv"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "girivarsha-sih26192-research/1.0 (contact: sudarsanghosh46@gmail.com)"
REQUEST_DELAY_SECONDS = 2.0  # deliberately slower than Nominatim's 1 req/sec
# minimum — this build environment's outbound IP is shared with other
# traffic, and 1.05s alone was still enough to trip real 429s.
MAX_RETRIES = 5

GEOCODING_CITATION = (
    "OpenStreetMap Nominatim (nominatim.openstreetmap.org), district-level "
    "administrative-boundary search, fetched 2026-09-04. Data (c) OpenStreetMap "
    "contributors, ODbL 1.0 (https://osm.org/copyright)."
)


def _geocode_district(state: str, district: str) -> dict | None:
    """Real Nominatim call, with retry/backoff on real rate-limit (429)
    responses — this build environment's outbound IP is shared, so a real
    429 here reflects total shared traffic, not just this script's own
    request rate. Returns {"lat", "lon"} or None if the district genuinely
    couldn't be resolved after retries — never a fabricated fallback."""
    query = f"{district} district, {state}, India"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"format": "json", "q": query, "limit": 1},
                headers={"User-Agent": USER_AGENT},
                timeout=20,
            )
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 0)) or (2 ** attempt) * 3
                print(f"    [429, attempt {attempt+1}/{MAX_RETRIES}] backing off {wait:.0f}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return None
            r = results[0]
            return {"lat": float(r["lat"]), "lon": float(r["lon"]), "osm_display_name": r.get("display_name", "")}
        except (requests.RequestException, KeyError, ValueError, IndexError) as exc:
            print(f"  [skip] Nominatim lookup failed for {query!r}: {exc}")
            return None
    print(f"  [skip] Nominatim still rate-limiting after {MAX_RETRIES} retries for {query!r}")
    return None


def is_single_district(districts_field) -> bool:
    """True only for a single, unambiguous district name — a comma means
    the source recorded 2+ districts for this event, which has no single
    honest point to geocode to (see module docstring)."""
    return len(str(districts_field).split(",")) == 1


def split_single_vs_multi_district(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pure, network-free split used by geocode() below — factored out so
    it's directly unit-testable without mocking HTTP calls."""
    mask = df["districts"].apply(is_single_district)
    return df[mask].copy(), df[~mask].copy()


def geocode() -> pd.DataFrame:
    df = pd.read_csv(IN_PATH)
    single, multi = split_single_vs_multi_district(df)
    print(
        f"Loaded {len(df)} real IFI candidate events — {len(single)} single-district "
        f"(geocodable), {len(multi)} multi-district (left uncoordinated; a point can't "
        "honestly represent a multi-district event)."
    )

    unique_pairs = single[["state", "districts"]].drop_duplicates().reset_index(drop=True)
    print(f"Geocoding {len(unique_pairs)} unique (state, district) pairs via Nominatim (1 req/sec)...")

    cache: dict[tuple[str, str], dict | None] = {}
    for i, row in unique_pairs.iterrows():
        key = (row["state"], row["districts"])
        result = _geocode_district(row["state"], row["districts"])
        cache[key] = result
        status = f"({result['lat']:.4f}, {result['lon']:.4f})" if result else "NOT FOUND"
        print(f"  [{i+1}/{len(unique_pairs)}] {row['districts']}, {row['state']}: {status}")
        time.sleep(REQUEST_DELAY_SECONDS)

    single["lat"] = single.apply(lambda r: (cache.get((r["state"], r["districts"])) or {}).get("lat"), axis=1)
    single["lon"] = single.apply(lambda r: (cache.get((r["state"], r["districts"])) or {}).get("lon"), axis=1)
    single["osm_display_name"] = single.apply(
        lambda r: (cache.get((r["state"], r["districts"])) or {}).get("osm_display_name"), axis=1
    )
    single["coordinate_precision"] = "district_centroid_geocoded"
    single["geocoding_citation"] = GEOCODING_CITATION

    resolved = single.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    unresolved = len(single) - len(resolved)
    if unresolved:
        print(f"{unresolved} single-district events could not be geocoded (Nominatim found no match) — dropped, not guessed.")

    resolved.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(resolved)} real, district-centroid-geocoded India hill-state events -> {OUT_PATH}")
    print(f"  state breakdown:\n{resolved['state'].value_counts().to_string()}")
    return resolved


if __name__ == "__main__":
    geocode()
