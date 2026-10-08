import subprocess
import time
from datetime import datetime


DEPLOYMENT = "scaling-demo"

MIN_REPLICAS = 1
MAX_REPLICAS = 5

CPU_SCALE_UP_THRESHOLD = 70
CPU_SCALE_DOWN_THRESHOLD = 30

CHECK_INTERVAL = 15

# Number of consecutive checks required
# before scaling is performed.
SCALE_UP_CONFIRMATIONS = 2
SCALE_DOWN_CONFIRMATIONS = 3

# Prevent immediate repeated scaling.
COOLDOWN_PERIOD = 30


scale_up_counter = 0
scale_down_counter = 0
last_scale_time = 0


def get_replicas():
    """
    Get the desired number of replicas from the Deployment.
    """

    result = subprocess.run(
        [
            "kubectl",
            "get",
            "deployment",
            DEPLOYMENT,
            "-o",
            "jsonpath={.spec.replicas}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return int(result.stdout)


def get_cpu_usage():
    """
    Calculate average CPU utilization of all scaling-demo pods.

    Each pod has a CPU limit of 500m.
    """

    result = subprocess.run(
        [
            "kubectl",
            "top",
            "pods",
            "-l",
            "app=scaling-demo",
            "--no-headers",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()

    if not lines:
        return 0.0

    total_cpu = 0
    pod_count = 0

    for line in lines:

        parts = line.split()

        if len(parts) < 2:
            continue

        cpu = parts[1]

        if cpu.endswith("m"):
            cpu_value = int(cpu[:-1])
        else:
            cpu_value = int(cpu) * 1000

        total_cpu += cpu_value
        pod_count += 1

    if pod_count == 0:
        return 0.0

    average_cpu = total_cpu / pod_count

    # Pod CPU limit = 500m
    percentage = (average_cpu / 500) * 100

    return percentage


def scale(replicas):
    """
    Change the Deployment replica count.
    """

    global last_scale_time

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Scaling deployment to {replicas} replicas"
    )

    subprocess.run(
        [
            "kubectl",
            "scale",
            "deployment",
            DEPLOYMENT,
            f"--replicas={replicas}",
        ],
        check=True,
    )

    last_scale_time = time.time()


def main():

    global scale_up_counter
    global scale_down_counter

    print("======================================")
    print(" Phase 2 Dynamic Scaling Controller")
    print("======================================")

    while True:

        try:

            replicas = get_replicas()
            cpu = get_cpu_usage()

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"CPU={cpu:.2f}% | "
                f"Replicas={replicas}"
            )

            time_since_scale = time.time() - last_scale_time

            # ------------------------------------------------
            # HIGH CPU
            # ------------------------------------------------

            if cpu > CPU_SCALE_UP_THRESHOLD:

                scale_up_counter += 1
                scale_down_counter = 0

                print(
                    f"High CPU detected "
                    f"({scale_up_counter}/"
                    f"{SCALE_UP_CONFIRMATIONS})"
                )

                if (
                    scale_up_counter >= SCALE_UP_CONFIRMATIONS
                    and replicas < MAX_REPLICAS
                    and time_since_scale >= COOLDOWN_PERIOD
                ):

                    scale(replicas + 1)

                    scale_up_counter = 0

            # ------------------------------------------------
            # LOW CPU
            # ------------------------------------------------

            elif cpu < CPU_SCALE_DOWN_THRESHOLD:

                scale_down_counter += 1
                scale_up_counter = 0

                print(
                    f"Low CPU detected "
                    f"({scale_down_counter}/"
                    f"{SCALE_DOWN_CONFIRMATIONS})"
                )

                if (
                    scale_down_counter >= SCALE_DOWN_CONFIRMATIONS
                    and replicas > MIN_REPLICAS
                    and time_since_scale >= COOLDOWN_PERIOD
                ):

                    scale(replicas - 1)

                    scale_down_counter = 0

            # ------------------------------------------------
            # NORMAL CPU
            # ------------------------------------------------

            else:

                print("CPU within normal range")

                scale_up_counter = 0
                scale_down_counter = 0

        except Exception as e:

            print(f"Controller error: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()