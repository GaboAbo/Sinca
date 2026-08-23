# Sinca-ETL

## Setup

Requires [uv](https://docs.astral.sh/uv/) and [git-lfs](https://git-lfs.com) (for `sinca.db`).

```bash
git lfs install
uv sync                          # install dependencies
uv run python -m analysis.compute # run the analysis pipeline -> analysis/results.json
uv run jupyter lab                # open sinca.ipynb
```

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

## 日本語

チリの[SINCA](https://sinca.mma.gob.cl)大気質・気象観測網から過去データを取得し(`sinca.py`)、
ローカルのSQLiteデータベース(`sinca.db`、Git LFSで管理)に保存します。その後 `analysis/` で
データを分析し、汚染トレンド、気象との相関、観測所の比較、翌日予測モデル、異常検知を計算して
`analysis/results.json` に出力します。探索的な分析とグラフは `sinca.ipynb` にあります。

- `sinca.py` — SINCAから観測所・データセットのメタデータを取得し、生のCSVデータをダウンロードします。
- `analysis/data.py` — `sinca.db` を読み込み、pandasのDataFrameに整形します。
- `analysis/compute.py` — 統計・機械学習パイプラインを実行し、`results.json` を書き出します。
- `sinca.ipynb` — 探索的分析用ノートブック。

詳細は `analysis/README.md` を参照してください。

## Credits

`sinca.py` and `analysis/` (`data.py`, `compute.py`) were built with [Claude Code](https://claude.com/claude-code). The exploratory data analysis in `sinca.ipynb` is the author's own work.
