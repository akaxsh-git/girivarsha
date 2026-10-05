# Raw source: Himalaya glacial lake inventory (2020 snapshot)

**Zhang, G., T. Bolch, T. Yao, D. R. Rounce, W. Chen, G. Veh, O. King, S. K. Allen, M. Wang,
and W. Wang (2023), "Underestimated mass loss from lake-terminating glaciers in the greater
Himalaya", Nature Geoscience, DOI: [10.1038/s41561-023-01150-1](https://doi.org/10.1038/s41561-023-01150-1).**

Data: figshare article [21708590](https://figshare.com/articles/dataset/Glacial_lake_inventory_1990_2000_2010_2015_and_2020_in_the_greater_Himalaya/21708590),
file `Glacial_Lake_Inventory.zip`, downloaded 2026-09-04 via
`https://ndownloader.figshare.com/files/39643498`.

The original dataset ships 5 real snapshots (1990/2000/2010/2015/2020); **only the 2020
snapshot is kept here** (the other four were deleted to keep this repository lean — they're
not used by anything in this project, but are one figshare download away if a future change
needs the time series). 9,208 real, individually satellite-mapped (Landsat) glacial lakes
across the Hindu Kush-Himalaya as of 2020, each with area, elevation, perimeter, lake type,
and parent-glacier RGI ID.

`scripts/prepare_glacial_lake_data.py` reads this shapefile and writes the lightweight,
India-Himalaya-filtered CSV actually used at runtime: `data/derived/real_himalaya_glacial_lakes.csv`.
See `docs/Data_Sources.md` and `docs/GIS_Methodology.md` for how this feeds
`backend/app/services/glacial_lake_proximity.py`.
