#!/usr/bin/env python3
"""Extract historical air-quality and meteorological data from Chile's SINCA network.

SINCA (sinca.mma.gob.cl) runs on Airviro. Each station page links its datasets
through apub.htmlindico2.cgi; the raw time series behind them is served as
semicolon-delimited CSV by apub.tsindico2.cgi. This module scrapes the station
page to discover datasets, then downloads and normalizes the series
(YYMMDD dates -> ISO, comma decimals -> floats).

Usage:
  python3 sinca.py stations <region>        # e.g. M, V, RM regions: I..XV, M
  python3 sinca.py datasets <station_id>    # e.g. 273 (Parque O'Higgins)
  python3 sinca.py fetch <station_id> <code> [--freq horario|diario]
                   [--from YYYY-MM-DD] [--to YYYY-MM-DD] [-o out.csv]
"""

import argparse
import csv
import html
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime

BASE = "https://sinca.mma.gob.cl"

# Parameter codes used in SINCA macropaths (verified against station pages).
CODES = {
    "0001": "SO2", "0002": "NO", "0003": "NO2", "0004": "CO",
    "0008": "O3", "0NOX": "NOx", "CORG": "organic C", "CTOT": "total C",
    "PM10": "PM10", "PM25": "PM2.5", "PM1D": "PM10 discrete",
    "PM2D": "PM2.5 discrete", "TEMP": "temperature", "RHUM": "rel. humidity",
    "WSPD": "wind speed", "WDIR": "wind direction",
}
TS_ENDPOINT = BASE + "/cgi-bin/APUB-MMA/apub.tsindico2.cgi"
UA = {"User-Agent": "Mozilla/5.0 (weather-app research script)"}


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _yymmdd_to_iso(yymmdd):
    yy = int(yymmdd[:2])
    year = 1900 + yy if yy >= 90 else 2000 + yy
    return f"{year:04d}-{yymmdd[2:4]}-{yymmdd[4:6]}"


def _iso_to_yymmdd(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%y%m%d")


def list_stations(region_id):
    """Return [(station_id, name)] for a region (I, II, ... XV, M, RM)."""
    page = _get(f"{BASE}/index.php/region/index/id/{region_id}")
    seen, out = set(), []
    for sid, name in re.findall(
        r'href="/index\.php/estacion/index/id/(\d+)"[^>]*>([^<]+)<', page
    ):
        if sid not in seen:
            seen.add(sid)
            out.append((sid, html.unescape(name).strip()))
    return out


def station_datasets(station_id):
    """Discover datasets on a station page.

    Returns list of dicts: code (e.g. PM25, TEMP), kind (Cal/Met), freq,
    macropath, macro, and the available from/to dates (ISO).
    """
    page = _get(f"{BASE}/index.php/estacion/index/id/{station_id}")
    out = []
    for m in re.finditer(
        r'apub\.htmlindico2\.cgi\?page=pageFrame&amp;header=[^&]*&amp;'
        r'macropath=(?P<path>[^&]+)&amp;macro=(?P<macro>[^&]+)&amp;'
        r'from=(?P<from>\d{6})&amp;to=(?P<to>\d{6})',
        page,
    ):
        path = m.group("path")
        macro = m.group("macro")
        code = path.rsplit("/", 1)[-1]
        kind = "Met" if "/Met/" in path else "Cal"
        freq = macro.split(".")[1] if "." in macro else macro
        out.append(
            {
                "code": code,
                "kind": kind,
                "freq": freq,
                "macropath": path,
                "macro": macro,
                "from": _yymmdd_to_iso(m.group("from")),
                "to": _yymmdd_to_iso(m.group("to")),
            }
        )
    return out


def fetch_series(macropath, macro, date_from, date_to):
    """Download one time series; yields dicts with ISO datetime and float values.

    Columns for air quality: validated / preliminary / unvalidated registers.
    Meteorological series have a single unnamed value column.
    """
    params = {
        "outtype": "xcl",
        "macro": f"{macropath}//{macro}.ic",
        "from": _iso_to_yymmdd(date_from),
        "to": _iso_to_yymmdd(date_to),
        "path": "/usr/airviro/data/CONAMA/",
        "lang": "esp",
    }
    raw = _get(TS_ENDPOINT + "?" + urllib.parse.urlencode(params))
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("FECHA"):
        raise RuntimeError(f"Unexpected response from SINCA: {raw[:200]!r}")
    for line in lines[1:]:
        cells = line.split(";")
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        if not cells[-1].strip():  # lines end with a trailing separator
            cells.pop()
        values = [c.strip() for c in cells[2:]]
        # Air-quality series carry 3 columns (validated/preliminary/unvalidated
        # registers); meteorological series carry a single value column.
        names = (
            ["validated", "preliminary", "unvalidated"]
            if len(values) == 3
            else [f"value{i or ''}" for i in range(len(values))]
        )
        row = {
            "date": _yymmdd_to_iso(cells[0]),
            "time": f"{cells[1][:2]}:{cells[1][2:]}" if cells[1] else "00:00",
        }
        for name, cell in zip(names, values):
            row[name] = float(cell.replace(",", ".")) if cell else None
        yield row


def _cmd_fetch(args):
    datasets = station_datasets(args.station_id)
    matches = [d for d in datasets if d["code"] == args.code and args.freq in d["macro"]]
    if not matches:
        codes = sorted({(d["code"], d["freq"]) for d in datasets})
        sys.exit(f"No dataset {args.code}/{args.freq} at station {args.station_id}. "
                 f"Available: {codes}")
    ds = matches[0]
    date_from = args.date_from or ds["from"]
    date_to = args.date_to or ds["to"]
    rows = list(fetch_series(ds["macropath"], ds["macro"], date_from, date_to))
    if not rows:
        sys.exit("No data returned for that range.")
    out = open(args.output, "w", newline="") if args.output else sys.stdout
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    if args.output:
        out.close()
        print(f"{len(rows)} rows -> {args.output} "
              f"({ds['code']} {ds['freq']}, {date_from}..{date_to})")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser("stations", help="list stations in a region")
    p_st.add_argument("region_id")

    p_ds = sub.add_parser("datasets", help="list datasets at a station")
    p_ds.add_argument("station_id")

    p_f = sub.add_parser("fetch", help="download a time series as CSV")
    p_f.add_argument("station_id")
    p_f.add_argument("code", help="parameter code, e.g. PM25 PM10 0003 TEMP RHUM")
    p_f.add_argument("--freq", default="horario", help="horario (hourly) or diario (daily)")
    p_f.add_argument("--from", dest="date_from", help="YYYY-MM-DD (default: full range)")
    p_f.add_argument("--to", dest="date_to", help="YYYY-MM-DD (default: full range)")
    p_f.add_argument("-o", "--output", help="output CSV path (default: stdout)")

    args = p.parse_args()
    if args.cmd == "stations":
        for sid, name in list_stations(args.region_id):
            print(f"{sid}\t{name}")
    elif args.cmd == "datasets":
        for d in station_datasets(args.station_id):
            label = CODES.get(d["code"], "?")
            print(f"{d['code']:>6} ({label:<14}) {d['kind']} {d['freq']:<11} "
                  f"{d['from']} .. {d['to']}")
    else:
        _cmd_fetch(args)


if __name__ == "__main__":
    main()
