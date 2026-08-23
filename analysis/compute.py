"""Compute trend, weather-correlation, station-comparison, forecasting and
anomaly-detection results for every well-covered pollutant, and write
analysis/results.json for the dashboard/API/notebook to read.

Scope note on the forecast model: it predicts *tomorrow's* value from
*today's* history and *today's* weather (not a real weather forecast), so
it's a same-day-conditions nowcast, not a deployable forecaster.

Scope note on regulatory thresholds: exceedance percentages are only
computed for particulates (PM2.5, PM10), where Chile's and WHO's 24-hour
thresholds use the same averaging window as this dataset's daily means. Gas
standards (O3, NO2, CO, SO2) typically use 1-hour or 8-hour peak windows
that a daily mean can't be fairly compared against, so gases get descriptive
stats only, not exceedance rates.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from analysis import data

OUT = Path(__file__).resolve().parent / "results.json"

# Pollutants analyzed, in display order (particulates first, then gases).
# Codes match sinca.py's CODES / the series.code column in sinca.db.
POLLUTANTS = [
    ("PM25", "PM2.5"),
    ("PM10", "PM10"),
    ("0008", "O3"),
    ("0003", "NO2"),
    ("0004", "CO"),
    ("0001", "SO2"),
    ("0002", "NO"),
    ("0NOX", "NOx"),
]

# See module docstring: only particulates get exceedance thresholds.
# PM2.5: DS 12/2011 (in force across nearly all of this dataset's history,
# tightened to 38 from April 2024); WHO 2021 guideline 15.
# PM10: DS 59/1998 (150, in force across nearly all of this dataset's
# history), tightened to 130 by DS 12/2022; WHO 2021 guideline 45.
PM_THRESHOLDS = {
    "PM25": {"chile_24h_norm": 50.0, "chile_24h_norm_current": 38.0, "who_24h_guideline": 15.0},
    "PM10": {"chile_24h_norm": 150.0, "chile_24h_norm_current": 130.0, "who_24h_guideline": 45.0},
}

# CO is conventionally reported in mg/m³ (its mass concentration is ~1000x
# the others); everything else here is µg/m³. Confirmed against the actual
# magnitudes in this dataset (CO daily means ~1, consistent with mg/m³; the
# others' magnitudes are consistent with µg/m³).
UNITS = {
    "PM25": "µg/m³", "PM10": "µg/m³", "0008": "µg/m³", "0003": "µg/m³",
    "0004": "mg/m³", "0001": "µg/m³", "0002": "µg/m³", "0NOX": "µg/m³",
}


def trends_and_seasonality(df):
    out_trend = {}
    for sid, g in df.groupby("station_id"):
        name = g["station"].iloc[0]
        yearly = g.groupby(g["date"].dt.year)["value"].mean()
        yearly = yearly[yearly.index < 2026]  # drop partial current year
        if len(yearly) < 5:
            continue
        slope, intercept, r, p, se = stats.linregress(yearly.index, yearly.values)
        out_trend[str(sid)] = {
            "name": name,
            "years": yearly.index.tolist(),
            "mean": [round(v, 2) for v in yearly.values],
            "slope_per_year": round(slope, 3),
            "p_value": round(p, 4),
        }

    region = df[df["date"].dt.year < 2026]
    clim = region.groupby(region["date"].dt.month)["value"].agg(["mean", "std", "count"])
    climatology = {
        "month": clim.index.tolist(),
        "mean": [round(v, 2) for v in clim["mean"]],
        "std": [round(v, 2) for v in clim["std"]],
        "n": clim["count"].tolist(),
    }

    dow = region.groupby(region["date"].dt.dayofweek)["value"].mean()
    day_of_week = {"day": dow.index.tolist(), "mean": [round(v, 2) for v in dow.values]}

    return {"by_station": out_trend, "climatology": climatology, "day_of_week": day_of_week}


def weather_correlation(df):
    d = df.dropna(subset=["value", "temp", "rhum", "wspd"])
    if len(d) < 30:
        return None

    corr = {}
    for var in ("temp", "rhum", "wspd"):
        r, p = stats.pearsonr(d[var], d["value"])
        corr[var] = {"r": round(r, 3), "p": round(float(p), 6), "n": int(len(d))}

    wind_bins = pd.qcut(d["wspd"], 5, duplicates="drop")
    wb = d.groupby(wind_bins, observed=True)["value"].agg(["mean", "count"])
    wind_speed_bins = {
        "label": [f"{iv.left:.1f}–{iv.right:.1f}" for iv in wb.index],
        "mean_value": [round(v, 2) for v in wb["mean"]],
        "n": wb["count"].tolist(),
    }

    temp_bins = pd.qcut(d["temp"], 5, duplicates="drop")
    tb = d.groupby(temp_bins, observed=True)["value"].agg(["mean", "count"])
    temp_bins_out = {
        "label": [f"{iv.left:.1f}–{iv.right:.1f}" for iv in tb.index],
        "mean_value": [round(v, 2) for v in tb["mean"]],
        "n": tb["count"].tolist(),
    }

    sample = d.sample(min(600, len(d)), random_state=0)
    scatter = {
        "wspd": [round(v, 2) for v in sample["wspd"]],
        "temp": [round(v, 2) for v in sample["temp"]],
        "value": [round(v, 2) for v in sample["value"]],
    }

    return {
        "correlations": corr,
        "wind_speed_bins": wind_speed_bins,
        "temp_bins": temp_bins_out,
        "scatter_sample": scatter,
    }


def station_comparison(df, code):
    thresholds = PM_THRESHOLDS.get(code)
    rows = []
    for sid, g in df.groupby("station_id"):
        name = g["station"].iloc[0]
        row = {
            "station": name,
            "mean": round(g["value"].mean(), 2),
            "median": round(g["value"].median(), 2),
            "p90": round(g["value"].quantile(0.9), 2),
            "n_days": int(len(g)),
        }
        if thresholds:
            row["pct_gt_chile_norm"] = round((g["value"] > thresholds["chile_24h_norm"]).mean() * 100, 1)
            row["pct_gt_who_guideline"] = round((g["value"] > thresholds["who_24h_guideline"]).mean() * 100, 1)
        rows.append(row)
    rows.sort(key=lambda r: -r["mean"])
    return {"thresholds": thresholds, "stations": rows}


def _make_features(g):
    g = g.sort_values("date").set_index("date")
    f = pd.DataFrame(index=g.index)
    f["lag1"] = g["value"].shift(1)
    f["lag2"] = g["value"].shift(2)
    f["lag7"] = g["value"].shift(7)
    f["roll7"] = g["value"].shift(1).rolling(7).mean()
    f["temp"] = g["temp"]
    f["rhum"] = g["rhum"]
    f["wspd"] = g["wspd"]
    doy = g.index.dayofyear
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    f["dow"] = g.index.dayofweek
    f["target"] = g["value"].shift(-1)
    return f


def forecast_and_anomalies(full_df, label):
    coverage = full_df.dropna(subset=["temp", "rhum", "wspd"]).groupby("station_id").size()
    if coverage.empty:
        return None
    best_sid = coverage.idxmax()
    g = full_df[full_df["station_id"] == best_sid]
    station_name = g["station"].iloc[0]

    feats = _make_features(g).dropna()
    feature_cols = [
        "lag1", "lag2", "lag7", "roll7", "temp", "rhum", "wspd",
        "doy_sin", "doy_cos", "dow",
    ]
    if len(feats) < 200:
        return None

    cutoff = feats.index[int(len(feats) * 0.8)]
    train = feats[feats.index < cutoff]
    test = feats[feats.index >= cutoff]
    if len(train) < 100 or len(test) < 30:
        return None

    X_train, y_train = train[feature_cols], train["target"]
    X_test, y_test = test[feature_cols], test["target"]

    model = RandomForestRegressor(n_estimators=300, max_depth=10, random_state=0, n_jobs=-1)
    model.fit(X_train, y_train)
    pred_rf = model.predict(X_test)
    pred_baseline = test["lag1"].values  # naive persistence forecast

    def metrics(y_true, y_pred):
        return {
            "mae": round(mean_absolute_error(y_true, y_pred), 3),
            "rmse": round(mean_squared_error(y_true, y_pred) ** 0.5, 3),
            "r2": round(r2_score(y_true, y_pred), 3),
        }

    importances = sorted(
        zip(feature_cols, model.feature_importances_), key=lambda t: -t[1]
    )

    sample_idx = np.linspace(0, len(test) - 1, min(300, len(test))).astype(int)
    test_dates = test.index[sample_idx]

    forecast_out = {
        "station": station_name,
        "train_range": [str(train.index.min().date()), str(train.index.max().date())],
        "test_range": [str(test.index.min().date()), str(test.index.max().date())],
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "metrics": {"random_forest": metrics(y_test, pred_rf), "baseline_persistence": metrics(y_test, pred_baseline)},
        "feature_importance": [{"feature": f, "importance": round(float(v), 3)} for f, v in importances],
        "sample": {
            "date": [str(d.date()) for d in test_dates],
            "actual": [round(v, 2) for v in y_test.values[sample_idx]],
            "predicted": [round(v, 2) for v in pred_rf[sample_idx]],
        },
    }

    # Robust rolling anomaly detection (median + MAD) across all stations.
    # The magnitude floor is relative (2x the station's own median) rather
    # than a fixed number, so it works across pollutants at very different
    # scales instead of a threshold tuned for one.
    anomalies = []
    for sid, gg in full_df.groupby("station_id"):
        gg = gg.sort_values("date").set_index("date")
        med = gg["value"].rolling(31, center=True, min_periods=15).median()
        mad = (gg["value"] - med).abs().rolling(31, center=True, min_periods=15).median()
        z = 0.6745 * (gg["value"] - med) / mad.replace(0, np.nan)
        floor = gg["value"].median() * 2
        flagged = gg[(z.abs() > 6) & (gg["value"] > floor)]
        for dt, val in flagged["value"].items():
            anomalies.append(
                {
                    "station": gg["station"].iloc[0],
                    "date": str(dt.date()),
                    "value": round(val, 2),
                    "z": round(float(z.loc[dt]), 1),
                }
            )
    anomalies.sort(key=lambda a: -a["z"])
    forecast_out["anomalies"] = anomalies[:20]

    return forecast_out


def analyze_pollutant(code, label, weather):
    df = data.station_daily_table(code, weather=weather)
    if df.empty:
        return None
    result = {
        "label": label,
        "unit": UNITS[code],
        "n_rows": int(len(df)),
        "n_stations": int(df["station_id"].nunique()),
        "trends": trends_and_seasonality(df),
        "station_comparison": station_comparison(df, code),
        "forecast": forecast_and_anomalies(df, label),
    }
    weather_result = weather_correlation(df)
    if weather_result is not None:
        result["weather"] = weather_result
    return result


def main():
    weather = data.precomputed_weather()

    pollutants = {}
    for code, label in POLLUTANTS:
        print(f"analyzing {label} ({code})...")
        result = analyze_pollutant(code, label, weather)
        if result is not None:
            pollutants[code] = result
            print(f"  {result['n_rows']} rows, {result['n_stations']} stations")

    results = {
        "pollutant_order": [code for code, _ in POLLUTANTS if code in pollutants],
        "pollutants": pollutants,
    }
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
