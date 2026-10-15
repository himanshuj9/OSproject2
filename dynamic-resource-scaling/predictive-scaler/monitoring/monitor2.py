"""Collect aggregate CPU and pod count for the predictive scaler.

Appends measurements to the shared project CSV so historical data survives
monitor restarts. Keeps the existing columns used by scaler.py and live_chart.py.
"""

import csv
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

# monitoring.py is inside the monitoring/ directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent

OUTPUT_FILE = Path(
    os.getenv("SCALING_CSV_FILE", str(PROJECT_DIR / "scaling_results.csv"))
)

INTERVAL = max(1, int(os.getenv("MONITOR_INTERVAL", "5")))
POD_SELECTOR = os.getenv("SCALING_POD_SELECTOR", "app=scaling-demo")

CSV_HEADER = ["timestamp", "total_cpu_millicores", "pod_count"]


def run_kubectl(args: list[str]) -> str:
    """Run kubectl and return its standard output."""
    result = subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return result.stdout.strip()


def parse_cpu_to_millicores(cpu_text: str) -> int:
    """Convert Kubernetes CPU values to millicores."""
    cpu_text = cpu_text.strip()

    if cpu_text.endswith("m"):
        return round(float(cpu_text[:-1]))

    # A value without 'm' is expressed in CPU cores.
    return round(float(cpu_text) * 1000)


def get_cpu() -> int:
    """Return aggregate CPU usage across matching pods, in millicores."""
    output = run_kubectl(
        ["top", "pods", "-l", POD_SELECTOR, "--no-headers"]
    )

    total_cpu = 0

    for line in output.splitlines():
        parts = line.split()

        # Format: POD_NAME CPU MEMORY
        if len(parts) >= 2:
            total_cpu += parse_cpu_to_millicores(parts[1])

    return total_cpu


def get_pod_count() -> int:
    """Return the number of matching pods listed by Kubernetes."""
    output = run_kubectl(
        ["get", "pods", "-l", POD_SELECTOR, "--no-headers"]
    )

    return sum(1 for line in output.splitlines() if line.strip())


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"Monitoring started. CSV: {OUTPUT_FILE}", flush=True)
    print(f"Sampling interval: {INTERVAL} seconds", flush=True)

    while True:
        try:
            # Check the file each time monitoring starts writing.
            # This also handles a missing or empty CSV safely.
            file_is_empty = (
                not OUTPUT_FILE.exists()
                or OUTPUT_FILE.stat().st_size == 0
            )

            with OUTPUT_FILE.open(
                "a", newline="", encoding="utf-8"
            ) as file:
                writer = csv.writer(file)

                if file_is_empty:
                    writer.writerow(CSV_HEADER)

                timestamp = datetime.now().isoformat(timespec="seconds")
                cpu = get_cpu()
                pods = get_pod_count()

                writer.writerow([timestamp, cpu, pods])
                file.flush()

            print(
                f"{timestamp} | total CPU={cpu}m | pods={pods}",
                flush=True,
            )

        except subprocess.TimeoutExpired:
            print("Monitoring error: kubectl timed out", flush=True)

        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            print(f"Monitoring error: kubectl failed: {detail}", flush=True)

        except (OSError, ValueError) as exc:
            print(f"Monitoring error: {exc}", flush=True)

        except Exception as exc:
            print(f"Unexpected monitoring error: {exc}", flush=True)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
