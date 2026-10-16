"""Readable live dashboard for dynamic container resource scaling.

Reads the monitor's scaling_results.csv and displays CPU usage and pod count
in separate, aligned panels. The chart refreshes while keeping a recent time
window in view, so old runs and long gaps do not compress current activity.

Run from this directory:
    python live_chart.py

Environment variables:
    SCALING_CSV_FILE        Optional path to scaling_results.csv
    CHART_WINDOW_MINUTES    Recent minutes to show (default: 15)
    CHART_REFRESH_SECONDS   Refresh interval (default: 5)
"""

import csv
import os
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


# Resolve the CSV relative to this script, not the terminal's current folder.
DEFAULT_CSV = Path(__file__).resolve().with_name("scaling_results.csv")
CSV_FILE = Path(os.getenv("SCALING_CSV_FILE", str(DEFAULT_CSV)))
WINDOW_MINUTES = max(1, int(os.getenv("CHART_WINDOW_MINUTES", "15")))
REFRESH_SECONDS = max(1, float(os.getenv("CHART_REFRESH_SECONDS", "5")))
MAX_POINTS = 500


def read_data():
    """Read valid records, tolerate partial rows, and sort by timestamp."""
    records = []

    try:
        with CSV_FILE.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file, skipinitialspace=True)

            if not reader.fieldnames:
                return [], [], []

            # Strip spaces from names and cell values (some CSVs have both).
            reader.fieldnames = [
                name.strip() if name else "" for name in reader.fieldnames
            ]
            required = {"timestamp", "total_cpu_millicores", "pod_count"}
            missing = required.difference(reader.fieldnames)
            if missing:
                raise ValueError(
                    f"CSV is missing required column(s): {', '.join(sorted(missing))}"
                )

            for row in reader:
                try:
                    timestamp_text = (row.get("timestamp") or "").strip()
                    cpu_text = (row.get("total_cpu_millicores") or "").strip()
                    pods_text = (row.get("pod_count") or "").strip()
                    if not (timestamp_text and cpu_text and pods_text):
                        continue

                    timestamp = datetime.fromisoformat(timestamp_text)
                    cpu = float(cpu_text)
                    pods = int(float(pods_text))
                    if cpu < 0 or pods < 0:
                        continue
                    records.append((timestamp, cpu, pods))
                except (TypeError, ValueError, AttributeError):
                    # Ignore incomplete rows if the monitor is writing the CSV.
                    continue

    except FileNotFoundError:
        print(f"Waiting for CSV file: {CSV_FILE}")
        return [], [], []
    except (OSError, ValueError) as exc:
        print(f"Could not read chart data: {exc}")
        return [], [], []

    # Sorting avoids a backward-moving time axis if older runs were appended.
    records.sort(key=lambda item: item[0])
    if not records:
        return [], [], []

    latest_timestamp = records[-1][0]
    cutoff = latest_timestamp - timedelta(minutes=WINDOW_MINUTES)
    recent = [record for record in records if record[0] >= cutoff]

    # Bound drawing work for very large CSVs while retaining the latest point.
    if len(recent) > MAX_POINTS:
        step = (len(recent) - 1) / (MAX_POINTS - 1)
        recent = [recent[round(index * step)] for index in range(MAX_POINTS - 1)]
        latest = records[-1]
        if recent[-1] != latest:
            recent.append(latest)
