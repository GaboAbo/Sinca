"""Load SINCA measurements from sinca.db into tidy pandas DataFrames."""

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "sinca.db"


def connect():
    return sqlite3.connect(DB_PATH)


def stations():
    with connect() as db:
        return pd.read_sql_query("SELECT id, name FROM stations", db)


def daily_pollutant(code):
    """Daily series for a pollutant code (e.g. 'PM25', 'PM10', 'O3'), one
    row per station/date, preferring validated measurements."""
    sql = """
        SELECT st.id AS station_id, st.name AS station, m.ts AS date, m.value
        FROM measurements m
        JOIN series s ON s.id = m.series_id
        JOIN stations st ON st.id = s.station_id
        WHERE s.code = ? AND s.freq = 'diario'
    """
    with connect() as db:
        df = pd.read_sql_query(sql, db, params=(code,))
    df["date"] = pd.to_datetime(df["date"].str[:10])
    return df


def hourly_weather(param_code):
    """Hourly meteorological series ('TEMP', 'RHUM', 'WSPD')."""
    sql = """
        SELECT st.id AS station_id, st.name AS station, m.ts AS ts, m.value
        FROM measurements m
        JOIN series s ON s.id = m.series_id
        JOIN stations st ON st.id = s.station_id
        WHERE s.code = ? AND s.kind = 'Met'
    """
    with connect() as db:
        df = pd.read_sql_query(sql, db, params=(param_code,))
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def daily_weather(param_code):
    """Hourly weather aggregated to daily mean per station."""
    df = hourly_weather(param_code)
    df["date"] = df["ts"].dt.floor("D")
    daily = (
        df.groupby(["station_id", "station", "date"], as_index=False)["value"]
        .mean()
        .rename(columns={"value": param_code.lower()})
    )
    return daily


def precomputed_weather():
    """The three daily weather aggregates, computed once.

    Each is a full hourly->daily scan over up to ~1.7M rows: reuse the same
    dict across multiple station_daily_table() calls (one per pollutant)
    instead of recomputing it per call.
    """
    return {
        "temp": daily_weather("TEMP"),
        "rhum": daily_weather("RHUM"),
        "wspd": daily_weather("WSPD"),
    }


def station_daily_table(pollutant="PM25", min_days=365 * 2, weather=None):
    """`pollutant` daily values + weather merged into one row per
    station/date, restricted to stations with at least `min_days` of
    coverage for that pollutant. Pass a dict from precomputed_weather() when
    analyzing several pollutants in one run to avoid redoing the hourly
    aggregation each time."""
    pol = daily_pollutant(pollutant)
    if weather is None:
        weather = precomputed_weather()
    temp = weather["temp"][["station_id", "date", "temp"]]
    rhum = weather["rhum"][["station_id", "date", "rhum"]]
    wspd = weather["wspd"][["station_id", "date", "wspd"]]

    counts = pol.groupby("station_id")["value"].count()
    keep = counts[counts >= min_days].index
    pol = pol[pol["station_id"].isin(keep)]

    merged = (
        pol.merge(temp, on=["station_id", "date"], how="left")
        .merge(rhum, on=["station_id", "date"], how="left")
        .merge(wspd, on=["station_id", "date"], how="left")
    )
    return _clean(merged)


def _clean(df):
    """Drop physically implausible sensor-fault readings.

    A handful of rows carry wind speeds ~1e22 m/s and temperatures near
    -40C (Santiago's RM basin has never recorded below about -8C) -
    instrument faults, not weather. Bounds are generous on purpose so real
    extremes survive; only clear-fault rows are dropped.
    """
    before = len(df)
    df = df[df["wspd"].isna() | df["wspd"].between(0, 30)]
    df = df[df["temp"].isna() | df["temp"].between(-15, 42)]
    df = df[df["rhum"].isna() | df["rhum"].between(0, 100)]
    dropped = before - len(df)
    if dropped:
        print(f"data QC: dropped {dropped} rows with sensor-fault readings")
    return df
