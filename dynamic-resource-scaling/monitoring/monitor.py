import subprocess
import time
import csv
from datetime import datetime


OUTPUT_FILE = "scaling_results.csv"

INTERVAL = 5


def get_cpu():

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

        return 0

    total_cpu = 0

    for line in lines:

        parts = line.split()

        if len(parts) < 2:
            continue

        cpu = parts[1]

        if cpu.endswith("m"):

            total_cpu += int(cpu[:-1])

        else:

            total_cpu += int(cpu) * 1000

    return total_cpu


def get_pod_count():

    result = subprocess.run(
        [
            "kubectl",
            "get",
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

    return len(lines)


def main():

    print("Monitoring started.")

    with open(
        OUTPUT_FILE,
        "w",
        newline=""
    ) as file:

        writer = csv.writer(file)

        writer.writerow(
            [
                "timestamp",
                "total_cpu_millicores",
                "pod_count"
            ]
        )

        while True:

            try:

                timestamp = datetime.now().isoformat()

                cpu = get_cpu()

                pods = get_pod_count()

                writer.writerow(
                    [
                        timestamp,
                        cpu,
                        pods
                    ]
                )

                file.flush()

                print(
                    f"{timestamp} | "
                    f"CPU={cpu}m | "
                    f"Pods={pods}"
                )

            except Exception as e:

                print(
                    f"Monitoring error: {e}"
                )

            time.sleep(INTERVAL)


if __name__ == "__main__":
    main()