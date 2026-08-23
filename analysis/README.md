# `analysis`

Turns the raw measurements in `sinca.db` (populated by `sinca.py`) into the
tidy tables and statistical results used by the dashboard/API/notebook.

```
sinca.db --[data.py]--> tidy DataFrames --[compute.py]--> analysis/results.json
```

- **`data.py`** — SQL access layer. Reads `sinca.db` and returns pandas
  DataFrames, one row per station/date (or station/timestamp for hourly
  data). No statistics, just loading, joining, and basic QC.
- **`compute.py`** — Analysis layer. Consumes `data.py`'s tables to compute
  trends, weather correlations, station comparisons, a next-day forecast
  model, and anomaly flags, then writes it all to `results.json`.

Run the pipeline with:

```bash
uv run python -m analysis.compute
```

## `data.py`

Expects `sinca.db` next to the repo root (`DB_PATH` = parent of `analysis/`).
Relevant schema (see `sinca.py` for how it's populated):

- `stations(id, name, region)`
- `series(id, station_id, code, name, kind, freq, ...)` — `kind` is `Cal`
  (air quality) or `Met` (meteorology); `freq` is `diario` (daily) or
  `horario*` (hourly)
- `measurements(series_id, ts, value, status)` — `status` is
  `validated`/`preliminary`/`unvalidated`

### Functions

| Function | Returns | Notes |
|---|---|---|
| `connect()` | `sqlite3.Connection` | Opens `sinca.db`. Use as a context manager. |
| `stations()` | `id, name` | All monitoring stations. |
| `daily_pollutant(code)` | `station_id, station, date, value` | One row per station/date for a pollutant code (`"PM25"`, `"PM10"`, `"0008"` for O3, ...; see `sinca.py`'s `CODES`). Only `freq='diario'` series. |
| `hourly_weather(param_code)` | `station_id, station, ts, value` | Raw hourly meteorology (`"TEMP"`, `"RHUM"`, `"WSPD"`). `kind='Met'` series. |
| `daily_weather(param_code)` | `station_id, station, date, <param>` | `hourly_weather` aggregated to a daily mean per station. Column is named after the lowercased param (`temp`, `rhum`, `wspd`). |
| `precomputed_weather()` | `{"temp": df, "rhum": df, "wspd": df}` | The three `daily_weather()` calls, computed once. Each hourly→daily aggregation scans up to ~1.7M rows, so compute this once and pass it to `station_daily_table()` when analyzing several pollutants in one run — don't call `daily_weather()` again per pollutant. |
| `station_daily_table(pollutant="PM25", min_days=730, weather=None)` | pollutant `value` + `temp`/`rhum`/`wspd`, one row per station/date | Main entry point. Merges a pollutant's daily series with weather, keeping only stations with at least `min_days` of coverage for that pollutant. Pass a `precomputed_weather()` dict via `weather=` to reuse it across pollutants; otherwise it's computed fresh (slow). Runs `_clean()` before returning. |
| `_clean(df)` | filtered `df` | Drops sensor-fault rows: `wspd` outside `[0, 30]` m/s, `temp` outside `[-15, 42]` °C, `rhum` outside `[0, 100]`%. A handful of raw readings are ~1e22 m/s wind speeds or near -40°C temperatures (Santiago's RM basin has never recorded below ~-8°C) — clear instrument faults, not weather. Bounds are generous so real extremes survive. Prints a count of dropped rows when any are dropped. |

## `compute.py`

Computes, for each pollutant in `POLLUTANTS`, the block of results described
below, and writes them all to `analysis/results.json`.

```python
POLLUTANTS = [
    ("PM25", "PM2.5"), ("PM10", "PM10"), ("0008", "O3"), ("0003", "NO2"),
    ("0004", "CO"), ("0001", "SO2"), ("0002", "NO"), ("0NOX", "NOx"),
]
```

Codes match `sinca.py`'s `CODES` / the `series.code` column. `UNITS` records
each pollutant's unit (µg/m³ for all of them except CO, which is mg/m³ —
confirmed against the actual magnitudes in the dataset, not just convention).

### Two documented scope limits

- **Forecast is a nowcast, not a forecaster.** It predicts *tomorrow's*
  value from *today's* history and *today's* weather — not a real weather
  forecast — so it can't be deployed to actually predict the future.
- **Exceedance rates are PM-only.** Chile's and WHO's 24-hour thresholds
  share this dataset's daily-mean averaging window only for particulates
  (PM2.5, PM10). Gas standards (O3, NO2, CO, SO2) use 1-hour/8-hour peak
  windows that a daily mean can't be fairly compared against, so gases get
  descriptive stats only — no `pct_gt_*` fields.

### Pipeline

| Function | Input | Output | What it does |
|---|---|---|---|
| `trends_and_seasonality(df)` | one pollutant's `station_daily_table()` | `by_station`, `climatology`, `day_of_week` | Per-station yearly means + OLS trend line (`scipy.stats.linregress`, dropping the current partial year); region-wide monthly climatology (mean/std/n); region-wide day-of-week means. Stations need ≥5 full years to get a trend line. |
| `weather_correlation(df)` | same | `correlations`, `wind_speed_bins`, `temp_bins`, `scatter_sample` | Pearson r/p of pollutant value vs. temp/rhum/wspd; pollutant mean binned into wind-speed and temperature quintiles (`pd.qcut`); a random 600-row sample for scatter plots. Returns `None` if fewer than 30 rows have complete weather data. |
| `station_comparison(df, code)` | same + pollutant code | `thresholds`, `stations` (mean/median/p90/n_days, + `pct_gt_chile_norm`/`pct_gt_who_guideline` for PM only) | Per-station summary stats, sorted by mean descending. |
| `_make_features(g)` | one station's daily rows | feature `DataFrame` | Builds the forecast model's feature matrix: `lag1/lag2/lag7`, `roll7` (7-day rolling mean of prior values), `temp/rhum/wspd`, cyclical day-of-year (`doy_sin/doy_cos`), day-of-week, and the `target` (next day's value). |
| `forecast_and_anomalies(full_df, label)` | same as above | `forecast` block | Picks the station with the most complete weather coverage, trains a `RandomForestRegressor` (300 trees, max depth 10) on an 80/20 chronological train/test split, and reports MAE/RMSE/R² against a naive persistence (`lag1`) baseline, feature importances, and a downsampled actual-vs-predicted series. Also runs a robust rolling-median/MAD anomaly detector (see below) across *all* stations, not just the chosen one, and attaches the top 20 anomalies by z-score. Returns `None` if there's under 200 complete feature rows, or the resulting train/test split is too small (<100 train / <30 test rows). |
| `analyze_pollutant(code, label, weather)` | pollutant code/label + a `precomputed_weather()` dict | one pollutant's full result block | Orchestrates the above four for a single pollutant. Returns `None` if `station_daily_table()` comes back empty. |
| `main()` | — | writes `analysis/results.json` | Loops `POLLUTANTS`, calls `analyze_pollutant()` for each, and writes `{"pollutant_order": [...], "pollutants": {code: result, ...}}`. |

**Anomaly detection** (inside `forecast_and_anomalies`): per station, a
31-day centered rolling median and MAD (median absolute deviation) give a
robust z-score (`0.6745 * (value - median) / MAD`); a point is flagged if
`|z| > 6` *and* its value exceeds 2x the station's overall median. The 2x
floor is relative rather than a fixed number so the same detector works
across pollutants with very different scales (e.g. CO in mg/m³ vs. PM in
µg/m³).

### Output shape (`results.json`)

```jsonc
{
  "pollutant_order": ["PM25", "PM10", "0008", ...],
  "pollutants": {
    "PM25": {
      "label": "PM2.5", "unit": "µg/m³",
      "n_rows": 12345, "n_stations": 7,
      "trends": { "by_station": {...}, "climatology": {...}, "day_of_week": {...} },
      "station_comparison": { "thresholds": {...}, "stations": [...] },
      "forecast": { "station": "...", "metrics": {...}, "feature_importance": [...], "sample": {...}, "anomalies": [...] },
      "weather": { "correlations": {...}, "wind_speed_bins": {...}, "temp_bins": {...}, "scatter_sample": {...} }
    },
    ...
  }
}
```

`weather` is omitted for a pollutant if it has fewer than 30 rows with
complete temp/rhum/wspd data; `forecast` is `null` if there isn't enough
history to train/test on (see table above).
