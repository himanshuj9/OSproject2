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

        with open(CSV_FILE, "r") as file:

            reader = csv.DictReader(file)

            for row in reader:

                timestamps.append(
                    datetime.fromisoformat(row["timestamp"])
                )

                cpu_values.append(
                    int(row["total_cpu_millicores"])
                )

                pod_values.append(
                    int(row["pod_count"])
                )

    except (FileNotFoundError, ValueError):
        pass

    return timestamps, cpu_values, pod_values


while True:

    timestamps, cpu_values, pod_values = read_data()

    ax1.clear()
    ax2.clear()

    if timestamps:

        ax1.plot(
            timestamps,
            cpu_values,
            label="CPU Usage"
        )

        ax2.plot(
            timestamps,
            pod_values,
            label="Pod Count"
        )

    ax1.set_xlabel("Time")
    ax1.set_ylabel("CPU Usage (millicores)")
    ax2.set_ylabel("Number of Pods")

    ax1.set_title(
        "Dynamic Resource Scaling - Live Monitoring"
    )

    ax1.grid(True)

    fig.autofmt_xdate()

    plt.pause(5)