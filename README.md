# Sinca-ETL

## English

Extracts historical air-quality and meteorological data from Chile's [SINCA](https://sinca.mma.gob.cl)
monitoring network (`sinca.py`) into a local SQLite database (`sinca.db`, tracked via Git LFS),
then analyzes it (`analysis/`) to produce pollution trends, weather correlations, station
comparisons, a next-day forecast model, and anomaly detection, written out as
`analysis/results.json`. Exploratory work and plots live in `sinca.ipynb`.

- `sinca.py` — scrapes station/dataset metadata and downloads raw CSV series from SINCA.
- `analysis/data.py` — loads `sinca.db` into tidy pandas DataFrames.
- `analysis/compute.py` — runs the statistics/ML pipeline and writes `results.json`.
- `sinca.ipynb` — exploratory analysis notebook.

See `analysis/README.md` for details on the data and compute modules.

## Español

Extrae datos históricos de calidad del aire y meteorología de la red [SINCA](https://sinca.mma.gob.cl)
de Chile (`sinca.py`) hacia una base de datos SQLite local (`sinca.db`, versionada con Git LFS),
y luego los analiza (`analysis/`) para generar tendencias de contaminación, correlaciones con
el clima, comparaciones entre estaciones, un modelo de pronóstico a un día y detección de
anomalías, exportado a `analysis/results.json`. El trabajo exploratorio y los gráficos están
en `sinca.ipynb`.

- `sinca.py` — extrae metadatos de estaciones/datasets y descarga las series CSV crudas de SINCA.
- `analysis/data.py` — carga `sinca.db` en DataFrames de pandas listos para analizar.
- `analysis/compute.py` — ejecuta el pipeline estadístico/ML y escribe `results.json`.
- `sinca.ipynb` — notebook de análisis exploratorio.

Ver `analysis/README.md` para el detalle de los módulos de datos y cómputo.
