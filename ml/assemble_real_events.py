"""
Real ML training-data assembly (Phase 12 follow-up, user-requested).

Honesty note up front, same spirit as generate_synthetic_training_data.py's
own docstring: this file assembles REAL events from two published, cited,
third-party datasets (see ml/data/raw/README.md for exact sources/DOIs).
It does NOT invent, estimate, or interpolate any event that isn't in one
of those datasets. Where a real dataset's own precision is limited (a
GLOF recorded only to the year, or an India Flood Inventory event with no
coordinates at all), that limitation is carried through honestly in the
output columns (`date_precision`, `has_coordinates`) rather than silently
upgraded to look more precise than the source actually is.

This is deliberately a data-ASSEMBLY step, separate from feature
backfill (ml/backfill_real_weather.py) and training (ml/train_real.py),
so each stage can be inspected/tested independently.

Two output tables:

1. `ml/data/real_glof_events.csv` — the Himalayan-arc subset (India, Nepal,
   Bhutan, Pakistan) of the 609-event global moraine-dammed GLOF
   inventory. Every row has real coordinates, so this is the set that
   ml/backfill_real_weather.py can actually attach real rainfall features
   to and ml/train_real.py can train/evaluate on.

2. `ml/data/real_india_hillstate_candidate_events.csv` — real, IMD-sourced
   flash-flood/landslide/cloudburst/GLOF-tagged events from the India
   Flood Inventory, filtered to India's Himalayan hill states. These have
   NO coordinates in the source data (it's a district-level inventory,
   not point-located) — kept here as a real, cited candidate list for
   future region-onboarding / geocoding work, NOT fed into ML training.
   See docs/ML_Methodology.md for why.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).parent / "data" / "raw"
OUT_DIR = Path(__file__).parent / "data"

GLOF_XLSX = RAW_DIR / "glof_moraine_dammed_v_zenodo15825574.xlsx"
GLOF_CITATION = (
    "Global inventory of moraine-dammed GLOFs (1900-2020), Zenodo record "
    "15825574 (DOI: 10.5281/zenodo.15825574), https://zenodo.org/records/15825574 "
    "— fetched 2026-09-04."
)

IFI_CSV = RAW_DIR / "india_flood_inventory_v3_zenodo16994648.csv"
IFI_CITATION = (
    "India Flood Inventory with Impacts (IFI-Impacts) v3, 1967-2023, Zenodo "
    "record 16994648 (DOI: 10.5281/zenodo.4742142), "
    "https://github.com/hydrosenselab/India-Flood-Inventory — fetched 2026-09-04."
)

# The real, contiguous Himalayan arc most comparable to the two pilot
# valleys already seeded (Mandakini/Kedarnath, Rishiganga-Dhauliganga/
# Chamoli) — not "all of India" (explicitly out of scope, problem
# statement item 2), and not unrelated glacier regions the source dataset
# also covers (Peru, Chile, Kazakhstan, Svalbard, etc.).
HIMALAYA_GLOF_COUNTRIES = {"India", "Nepal", "Bhutan", "Pakistan"}

# India's Himalayan hill states — the states this app's region registry
# (docs/Region_Onboarding.md) already treats as real flash-flood/GLOF-prone
# candidate territory (2 active, 3 planned regions all fall in these).
HIMALAYA_HILL_STATES = {
    "Uttarakhand",
    "Himachal Pradesh",
    "Jammu and Kashmir",
    "Jammu & Kashmir",
    "Sikkim",
    "Arunachal Pradesh",
}

FLASH_FLOOD_KEYWORDS = re.compile(
    r"flash|cloudburst|cloud burst|landslide|glacial|glof|debris|avalanche|mudslide",
    re.IGNORECASE,
)


def _parse_glof_date(raw) -> tuple[str | None, str]:
    """Returns (iso_date_or_None, precision) honestly reflecting what the
    source actually recorded. Never guesses a day/month that isn't there."""
    if isinstance(raw, datetime):
        return raw.date().isoformat(), "exact_date"
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None, "unknown"
    text = str(raw).strip()
    # Plain 4-digit year: "1960", "1998"
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-01-01", "year_only"
    # "Before 1966", "Before 1968*"
    m = re.fullmatch(r"Before (\d{4})\*?", text)
    if m:
        return f"{m.group(1)}-01-01", "year_only_upper_bound"
    # ISO-ish "YYYY/M/D" possibly with a trailing range "-YYYY/M/D"
    m = re.match(r"^(\d{4})/(\d{1,2})(?:/(\d{1,2}))?", text)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        if d:
            try:
                return date(int(y), int(mo), int(d)).isoformat(), "approximate"
            except ValueError:
                return f"{y}-01-01", "year_only"
        return f"{y}-{int(mo):02d}-01", "approximate"
    # Year ranges like "1966-1974", "1990-1991"
    m = re.fullmatch(r"(\d{4})-(\d{4})\*?", text)
    if m:
        return f"{m.group(1)}-01-01", "year_range_lower_bound"
    return None, "unparseable"


def assemble_glof_events() -> pd.DataFrame:
    df = pd.read_excel(GLOF_XLSX)
    sub = df[df["Country"].isin(HIMALAYA_GLOF_COUNTRIES)].copy()

    parsed = sub["Date"].apply(_parse_glof_date)
    sub["event_date"] = [p[0] for p in parsed]
    sub["date_precision"] = [p[1] for p in parsed]

    out = pd.DataFrame(
        {
            "source_id": sub["ID"],
            "country": sub["Country"],
            "location_name": sub["Glacial lake"],
            "event_date": sub["event_date"],
            "date_precision": sub["date_precision"],
            "lat": sub["Latitude"],
            "lon": sub["Longitude"],
            "trigger": sub["Triggers"],
            "deaths": sub["Deaths"],
            "severity_label": sub["Severity"],
            "per_row_reference": sub["References"],
            "dataset": "global_glof_moraine_dammed",
            "dataset_citation": GLOF_CITATION,
        }
    )
    # Real coordinates are non-negotiable for this table — a row with no
    # lat/lon can't be a point event, drop it rather than fabricate one.
    out = out.dropna(subset=["lat", "lon"])
    out = out.reset_index(drop=True)
    out.insert(0, "event_id", [f"glof-{i:03d}" for i in range(len(out))])
    return out


def assemble_ifi_candidate_events() -> pd.DataFrame:
    df = pd.read_csv(IFI_CSV, low_memory=False)
    hill = df[df["State"].isin(HIMALAYA_HILL_STATES)].copy()

    cause = hill["Main Cause"].fillna("")
    flash_relevant = cause.str.contains(FLASH_FLOOD_KEYWORDS, na=False)
    hill = hill[flash_relevant].copy()

    out = pd.DataFrame(
        {
            "state": hill["State"],
            "districts": hill["Districts"],
            "start_date": hill["Start Date"],
            "end_date": hill["End Date"],
            "main_cause": hill["Main Cause"],
            "severity_label": hill["Severity"],
            "human_fatality": hill["Human fatality"],
            "human_displaced": hill["Human Displaced"],
            "has_coordinates": False,
            "source_event_id": hill["UEI"],
            "dataset": "india_flood_inventory_ifi_impacts",
            "dataset_citation": IFI_CITATION,
        }
    )
    out = out.reset_index(drop=True)
    out.insert(0, "event_id", [f"ifi-{i:04d}" for i in range(len(out))])
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    glof = assemble_glof_events()
    glof_path = OUT_DIR / "real_glof_events.csv"
    glof.to_csv(glof_path, index=False)
    print(f"Wrote {len(glof)} real, coordinate-located Himalayan-arc GLOF events -> {glof_path}")
    print(f"  date precision breakdown:\n{glof['date_precision'].value_counts().to_string()}")

    ifi = assemble_ifi_candidate_events()
    ifi_path = OUT_DIR / "real_india_hillstate_candidate_events.csv"
    ifi.to_csv(ifi_path, index=False)
    print(f"\nWrote {len(ifi)} real, cited (but uncoordinated) India hill-state flood/landslide/GLOF events -> {ifi_path}")
    print(f"  state breakdown:\n{ifi['state'].value_counts().to_string()}")


if __name__ == "__main__":
    main()
