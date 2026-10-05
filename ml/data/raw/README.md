# Raw source data (Phase 12 follow-up — real ML training-data assembly)

These are unmodified downloads of real, published, third-party datasets. Nothing in this
directory was generated or altered by this project — `ml/assemble_real_events.py` reads
these files and derives the cleaned, cited event inventory under `ml/data/`.

## `glof_moraine_dammed_v_zenodo15825574.xlsx`

**Global inventory of moraine-dammed GLOFs (1900-2020).**
Source: Zenodo record [15825574](https://zenodo.org/records/15825574) (DOI: 10.5281/zenodo.15825574).
Downloaded 2026-09-04 via `https://zenodo.org/api/records/15825574/files/Moraine-dammed%20GLOFs.xlsx/content`.
609 real, individually-sourced glacial lake outburst flood events worldwide, each with
country, lake name, date (precision varies — exact day, month range, or year only, as
originally recorded), longitude/latitude, trigger, deaths, a severity label, and a
per-row academic/institutional reference.

## `india_flood_inventory_v3_zenodo16994648.csv`

**India Flood Inventory with Impacts (IFI-Impacts) v3, 1967-2023.**
Source: Zenodo record [16994648](https://zenodo.org/records/16994648) (DOI: 10.5281/zenodo.4742142,
concept DOI for the hydrosenselab/India-Flood-Inventory project — https://github.com/hydrosenselab/India-Flood-Inventory).
Downloaded 2026-09-04 via `https://zenodo.org/api/records/16994648/files/India_Flood_Inventory_v3.csv/content`.
6,876 real, IMD-sourced flood events across India, 1967-2023, with start/end date, main
cause, affected districts/state, a severity label, and reported human/animal impact.
**No latitude/longitude column is populated in this file** — events are recorded at
district/multi-district granularity, not as point locations. See
`ml/assemble_real_events.py` and `docs/ML_Methodology.md` for how this project handles
that (short answer: it is kept as a real, cited candidate list for future geocoding,
not force-fitted into point-based ML features it doesn't actually have).
