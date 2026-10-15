import csv
import time
import matplotlib.pyplot as plt
from datetime import datetime

CSV_FILE = "scaling_results.csv"

plt.ion()

fig, ax1 = plt.subplots()
ax2 = ax1.twinx()


def read_data():
    timestamps = []
    cpu_values = []
    pod_values = []

    try:
        with open(CSV_FILE, "r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file, skipinitialspace=True)

            # Fix whitespace around CSV column names.
            if reader.fieldnames:
                reader.fieldnames = [
                    name.strip() if name else ""
                    for name in reader.fieldnames
                ]

            for row in reader:
                try:
                    timestamps.append(
                        datetime.fromisoformat(row["timestamp"].strip())
                    )
                    cpu_values.append(
                        int(float(row["total_cpu_millicores"].strip()))
                    )
                    pod_values.append(
                        int(row["pod_count"].strip())
                    )
                except (ValueError, KeyError, AttributeError):
                    continue

    except FileNotFoundError:
        print(f"CSV file not found: {CSV_FILE}")

    return timestamps, cpu_values, pod_values


while True:
    timestamps, cpu_values, pod_values = read_data()

    ax1.clear()
    ax2.clear()

    if timestamps:
        # CPU line: yellow
        ax1.plot(
            timestamps,
            cpu_values,
            label="CPU Usage",
            color="yellow",
            linewidth=2
        )

        # Pod count line: cyan
        ax2.plot(
            timestamps,
            pod_values,
            label="Pod Count",
            color="cyan",
            linewidth=2,
            marker="o"
        )

    ax1.set_xlabel("Time")
    ax1.set_ylabel("CPU Usage (millicores)", color="gold")
    ax2.set_ylabel("Number of Pods", color="deepskyblue")

    ax1.tick_params(axis="y", labelcolor="gold")
    ax2.tick_params(axis="y", labelcolor="deepskyblue")

    ax1.set_title("Dynamic Resource Scaling - Live Monitoring")
    ax1.grid(True, alpha=0.3)

    # Combine legends from both axes.
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    fig.autofmt_xdate()
    fig.tight_layout()

    plt.pause(5)
