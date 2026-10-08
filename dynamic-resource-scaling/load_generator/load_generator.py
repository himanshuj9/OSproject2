import requests
import time
from concurrent.futures import ThreadPoolExecutor


URL = "http://127.0.0.1:5000/work"


def send_request():

    start = time.time()

    try:

        response = requests.get(
            URL,
            timeout=10
        )

        latency = time.time() - start

        return latency, response.status_code

    except requests.RequestException:

        return None, None


def generate_load(requests_per_second, duration):

    print()
    print(
        f"Starting load: "
        f"{requests_per_second} req/s "
        f"for {duration} seconds"
    )

    total_requests = 0
    successful_requests = 0
    latencies = []

    end_time = time.time() + duration

    with ThreadPoolExecutor(
        max_workers=requests_per_second
    ) as executor:

        while time.time() < end_time:

            futures = []

            start = time.time()

            for _ in range(requests_per_second):

                futures.append(
                    executor.submit(send_request)
                )

            for future in futures:

                latency, status = future.result()

                total_requests += 1

                if status == 200:

                    successful_requests += 1

                if latency is not None:

                    latencies.append(latency)

            elapsed = time.time() - start

            if elapsed < 1:

                time.sleep(1 - elapsed)

    if latencies:

        average_latency = (
            sum(latencies) / len(latencies)
        )

    else:

        average_latency = 0

    success_rate = (
        successful_requests / total_requests
    ) * 100 if total_requests else 0

    print(
        f"Completed {total_requests} requests"
    )

    print(
        f"Success rate: {success_rate:.2f}%"
    )

    print(
        f"Average latency: "
        f"{average_latency:.4f} sec"
    )


def main():

    print("================================")
    print(" Phase 2 Load Testing")
    print("================================")

    scenarios = [

        # Low load
        (5, 30),

        # Medium load
        (20, 30),

        # High load
        (50, 30),

        # Extreme load
        (100, 30),

        # Recovery
        (5, 30),
    ]

    for rps, duration in scenarios:

        generate_load(
            rps,
            duration
        )

        # Give Kubernetes time
        # to react before next scenario.
        time.sleep(20)

    print()
    print("All Phase 2 tests completed.")


if __name__ == "__main__":
    main()