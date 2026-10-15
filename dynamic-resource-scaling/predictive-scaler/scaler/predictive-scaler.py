"""Multi-step predictive + reactive Kubernetes scaling controller.

Reads aggregate CPU measurements from scaling_results.csv, predicts future
CPU using linear regression, and scales the Deployment one Pod at a time.

Predictive scale-up thresholds: 150m, 200m, 250m, 300m.
Predictive scale-down uses lower thresholds to avoid rapid up/down oscillation.
Reactive CPU utilization thresholds remain as a fallback.
"""

import csv
import math
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Project layout:
# dynamic-resource-scaling/
#   monitoring/monitoring.py
#   scaler/scaler.py
#   scaling_results.csv

PROJECT_DIR = Path(__file__).resolve().parents[1]
CSV_FILE = Path(
    os.getenv("SCALING_CSV_FILE", str(PROJECT_DIR / "scaling_results.csv"))
)

DEPLOYMENT = os.getenv("SCALING_DEPLOYMENT", "scaling-demo")
POD_SELECTOR = os.getenv("SCALING_POD_SELECTOR", "app=scaling-demo")

MIN_REPLICAS = int(os.getenv("MIN_REPLICAS", "1"))
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "5"))
CPU_LIMIT_PER_POD_M = float(os.getenv("CPU_LIMIT_PER_POD_M", "500"))

CHECK_INTERVAL = int(os.getenv("SCALER_CHECK_INTERVAL", "5"))
PREDICTION_HORIZON_SECONDS = int(
    os.getenv("PREDICTION_HORIZON_SECONDS", "10")
)
HISTORY_WINDOW = int(os.getenv("PREDICTION_HISTORY_WINDOW", "12"))
MIN_HISTORY_SAMPLES = int(os.getenv("MIN_HISTORY_SAMPLES", "3"))

# Predictive scale-up thresholds in aggregate CPU millicores.
# Each crossed threshold adds one Pod to the desired replica count.
SCALE_UP_THRESHOLDS_M = [150, 200, 250, 300]

# Lower thresholds provide hysteresis for scaling down.
# For example, after scaling up at 150m, don't scale down again
# until forecast CPU falls below 120m.
SCALE_DOWN_THRESHOLDS_M = [120, 170, 220, 270]

# Require sustained low forecast before scaling down.
PREDICTIVE_DOWNSCALE_CONFIRMATIONS = int(
    os.getenv("PREDICTIVE_DOWNSCALE_CONFIRMATIONS", "2")
)

# Reactive fallback thresholds based on total CPU utilization percentage.
CPU_SCALE_UP_THRESHOLD = float(os.getenv("CPU_SCALE_UP_THRESHOLD", "70"))
CPU_SCALE_DOWN_THRESHOLD = float(os.getenv("CPU_SCALE_DOWN_THRESHOLD", "30"))

SCALE_UP_CONFIRMATIONS = 1
SCALE_DOWN_CONFIRMATIONS = 2
COOLDOWN_PERIOD = int(os.getenv("SCALER_COOLDOWN_SECONDS", "10"))

scale_up_counter = 0
scale_down_counter = 0
predictive_down_counter = 0
last_scale_time = 0.0


def log(message: str) -> None:
    """Print a timestamped message."""
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}",
        flush=True,
    )


def run_kubectl(args: list[str]) -> str:
    """Execute a kubectl command and return its output."""
    result = subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return result.stdout.strip()


def get_replicas() -> int:
    """Get the Deployment's configured replica count."""
    value = run_kubectl(
        [
            "get",
            "deployment",
            DEPLOYMENT,
            "-o",
            "jsonpath={.spec.replicas}",
        ]
    )

    if not value:
        raise RuntimeError(
            f"Deployment {DEPLOYMENT!r} returned no replica count"
        )

    return int(value)


def parse_cpu_to_millicores(cpu_text: str) -> int:
    """Convert CPU such as 150m or 1 into millicores."""
    cpu_text = cpu_text.strip()

    if cpu_text.endswith("m"):
        return round(float(cpu_text[:-1]))

    return round(float(cpu_text) * 1000)


def get_cpu_usage() -> tuple[int, int]:
    """Return aggregate CPU in millicores and number of measured Pods."""
    output = run_kubectl(
        ["top", "pods", "-l", POD_SELECTOR, "--no-headers"]
    )

    total_cpu_m = 0
    measured_pods = 0

    for line in output.splitlines():
        parts = line.split()

        if len(parts) < 2:
            continue

        cpu_m = parse_cpu_to_millicores(parts[1])
        total_cpu_m += cpu_m
        measured_pods += 1

    return total_cpu_m, measured_pods


def read_history() -> list[tuple[float, float]]:
    """Read recent (timestamp, aggregate CPU millicores) CSV samples."""
    samples: list[tuple[float, float]] = []

    if not CSV_FILE.exists():
        return samples

    try:
        with CSV_FILE.open(
            "r", newline="", encoding="utf-8-sig"
        ) as handle:
            reader = csv.DictReader(handle)

            required = {"timestamp", "total_cpu_millicores"}

            if (
                not reader.fieldnames
                or not required.issubset(set(reader.fieldnames))
            ):
                log(
                    f"CSV needs columns {sorted(required)}; "
                    f"found {reader.fieldnames}"
                )
                return samples

            for row in reader:
                try:
                    stamp = datetime.fromisoformat(
                        row["timestamp"].strip()
                    ).timestamp()
                    cpu = float(row["total_cpu_millicores"])

                    if math.isfinite(stamp) and math.isfinite(cpu) and cpu >= 0:
                        samples.append((stamp, cpu))

                except (TypeError, ValueError, AttributeError):
                    continue

    except OSError as exc:
        log(f"Could not read CSV {CSV_FILE}: {exc}")
        return []

    return samples[-HISTORY_WINDOW:]


def predict_cpu(
    history: list[tuple[float, float]]
) -> Optional[float]:
    """Predict aggregate CPU at the configured future time."""
    if len(history) < MIN_HISTORY_SAMPLES:
        return None

    # Use relative time rather than large Unix timestamps.
    t0 = history[0][0]
    xs = [stamp - t0 for stamp, _ in history]
    ys = [cpu for _, cpu in history]

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)

    denominator = sum((x - x_mean) ** 2 for x in xs)

    if denominator <= 1e-9:
        return None

    # Least-squares regression: calculate the CPU trend per second.
    slope = sum(
        (x - x_mean) * (y - y_mean)
        for x, y in zip(xs, ys)
    ) / denominator

    future_x = xs[-1] + max(1, PREDICTION_HORIZON_SECONDS)
    prediction = y_mean + slope * (future_x - x_mean)

    return max(0.0, prediction)


def replicas_for_scale_up(predicted_cpu_m: float) -> int:
    """Calculate the target replica count using ascending CPU thresholds."""
    crossed_thresholds = sum(
        predicted_cpu_m >= threshold
        for threshold in SCALE_UP_THRESHOLDS_M
    )

    desired = MIN_REPLICAS + crossed_thresholds

    return max(MIN_REPLICAS, min(MAX_REPLICAS, desired))


def replicas_for_scale_down(predicted_cpu_m: float) -> int:
    """Calculate the replica target using lower downscale thresholds."""
    crossed_thresholds = sum(
        predicted_cpu_m >= threshold
        for threshold in SCALE_DOWN_THRESHOLDS_M
    )

    desired = MIN_REPLICAS + crossed_thresholds

    return max(MIN_REPLICAS, min(MAX_REPLICAS, desired))


def scale(replicas: int, reason: str) -> None:
    """Apply the requested replica count and start the cooldown."""
    global last_scale_time

    replicas = max(
        MIN_REPLICAS,
        min(MAX_REPLICAS, int(replicas)),
    )

    log(
        f"SCALING: Deployment {DEPLOYMENT} -> {replicas} replicas "
        f"| reason: {reason}"
    )

    run_kubectl(
        ["scale", "deployment", DEPLOYMENT, f"--replicas={replicas}"]
    )

    last_scale_time = time.time()


def main() -> None:
    global scale_up_counter
    global scale_down_counter
    global predictive_down_counter

    log("Multi-step predictive + reactive scaler started")
    log(f"CSV: {CSV_FILE}")
    log(
        f"Deployment={DEPLOYMENT}, replica range={MIN_REPLICAS}-{MAX_REPLICAS}"
    )
    log(f"Scale-up thresholds: {SCALE_UP_THRESHOLDS_M}")
    log(f"Scale-down thresholds: {SCALE_DOWN_THRESHOLDS_M}")
    log(
        f"Prediction horizon={PREDICTION_HORIZON_SECONDS}s, "
        f"check interval={CHECK_INTERVAL}s, cooldown={COOLDOWN_PERIOD}s"
    )

    while True:
        try:
            replicas = get_replicas()
            current_cpu_m, measured_pods = get_cpu_usage()

            # Calculate utilization across the total configured CPU capacity.
            current_cpu_pct = (
                current_cpu_m / (replicas * CPU_LIMIT_PER_POD_M) * 100
                if measured_pods > 0
                and replicas > 0
                and CPU_LIMIT_PER_POD_M > 0
                else None
            )

            history = read_history()
            predicted_cpu_m = predict_cpu(history)

            cooldown_done = (
                time.time() - last_scale_time >= COOLDOWN_PERIOD
            )

            cpu_label = (
                f"{current_cpu_pct:.1f}%"
                if current_cpu_pct is not None
                else "unavailable"
            )

            forecast_label = (
                f"{predicted_cpu_m:.0f}m"
                if predicted_cpu_m is not None
                else "not enough history"
            )

            log(
                f"Current CPU={current_cpu_m}m ({cpu_label}), "
                f"forecast={forecast_label}, "
                f"CSV samples={len(history)}, replicas={replicas}"
            )

            # -------------------------------------------------
            # 1. Predictive scaling
            # -------------------------------------------------
            if predicted_cpu_m is not None:
                up_target = replicas_for_scale_up(predicted_cpu_m)
                down_target = replicas_for_scale_down(predicted_cpu_m)

                # Scale up one Pod at a time. If the forecast remains high,
                # later checks can add more Pods after the cooldown.
                if up_target > replicas:
                    predictive_down_counter = 0

                    if cooldown_done:
                        next_replicas = min(replicas + 1, up_target)

                        scale(
                            next_replicas,
                            f"forecast {predicted_cpu_m:.0f}m crossed "
                            f"scale-up threshold; target={up_target}",
                        )

                        scale_up_counter = 0
                        scale_down_counter = 0

                        time.sleep(CHECK_INTERVAL)
                        continue

                # Scale down one Pod at a time after repeated low forecasts.
                elif down_target < replicas:
                    predictive_down_counter += 1

                    log(
                        "Low forecast confirmation "
                        f"{predictive_down_counter}/"
                        f"{PREDICTIVE_DOWNSCALE_CONFIRMATIONS}"
                    )

                    if (
                        predictive_down_counter
                        >= PREDICTIVE_DOWNSCALE_CONFIRMATIONS
                        and cooldown_done
                    ):
                        next_replicas = max(replicas - 1, down_target)

                        scale(
                            next_replicas,
                            f"sustained low forecast "
                            f"{predicted_cpu_m:.0f}m; target={down_target}",
                        )

                        predictive_down_counter = 0
                        scale_up_counter = 0
                        scale_down_counter = 0

                        time.sleep(CHECK_INTERVAL)
                        continue

                else:
                    predictive_down_counter = 0

            # -------------------------------------------------
            # 2. Reactive fallback based on current CPU
            # -------------------------------------------------
            if current_cpu_pct is None:
                log("Current CPU metrics unavailable; waiting for metrics")
                scale_up_counter = 0
                scale_down_counter = 0

            elif current_cpu_pct > CPU_SCALE_UP_THRESHOLD:
                scale_up_counter += 1
                scale_down_counter = 0

                if (
                    scale_up_counter >= SCALE_UP_CONFIRMATIONS
                    and replicas < MAX_REPLICAS
                    and cooldown_done
                ):
                    scale(
                        replicas + 1,
                        f"reactive fallback: CPU={current_cpu_pct:.1f}%",
                    )
                    scale_up_counter = 0
                    scale_down_counter = 0

            elif current_cpu_pct < CPU_SCALE_DOWN_THRESHOLD:
                scale_down_counter += 1
                scale_up_counter = 0

                if (
                    scale_down_counter >= SCALE_DOWN_CONFIRMATIONS
                    and replicas > MIN_REPLICAS
                    and cooldown_done
                ):
                    scale(
                        replicas - 1,
                        f"reactive fallback: CPU={current_cpu_pct:.1f}%",
                    )
                    scale_down_counter = 0
                    scale_up_counter = 0

            else:
                scale_up_counter = 0
                scale_down_counter = 0
                log("CPU is within the reactive normal range")

        except subprocess.TimeoutExpired:
            log("kubectl timed out; check Kubernetes connectivity and metrics-server")

        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            log(f"kubectl failed: {detail}")

        except (OSError, ValueError, RuntimeError) as exc:
            log(f"Controller error: {exc}")

        except Exception as exc:
            log(
                f"Unexpected controller error: "
                f"{type(exc).__name__}: {exc}"
            )

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()