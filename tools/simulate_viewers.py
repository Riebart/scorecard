#!/usr/bin/env python3

import json
import time
import asyncio
import argparse
import multiprocessing
import concurrent.futures
from collections import Counter

import requests

def get_score(session, url):
    """
    Get the scores as a coroutine.
    """
    print(url)
    t0 = time.time()
    resp = session.get(url, stream=False)
    print(resp)
    t1 = time.time()
    return {
        "url": url,
        "timestamp": t0,
        "dt": t1 - t0,
        "status_code": resp.status_code
    }


def viewer_main(url, period, teams, queue):
    """
    Insertion point to start the viewer under the event loop.
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(viewer(url, period, teams, queue))

async def viewer(url, period, teams, queue):
    """
    Simulate the actions of a viewer fetching the scores from the API.

    URL is of the form:
      https://<URI of API Gateway Stage without trailing slash>
      e.g.: https://84nc624fy9.execute-api.us-east-1.amazonaws.com/Main
    """
    session = requests.Session()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(teams)) as executor:
        loop = asyncio.get_event_loop()
        while True:
            start_time = time.time()
            futures = [
                loop.run_in_executor(
                    executor,
                    get_score,
                    *(session, "%s/score/%s" % (url, str(team)))
                ) for team in teams
            ]
            for response in await asyncio.gather(*futures):
                queue.put(response)
            time.sleep(max(0, start_time + period - time.time()))


def stat_summary(stats):
    min_dt = min([s["dt"] for s in stats])
    max_dt = max([s["dt"] for s in stats])
    mean_dt = sum([s["dt"] for s in stats]) / len(stats)
    status_codes = dict([
        (str(k), v) for k, v in
        Counter([s["status_code"] for s in stats]).items()
    ])
    return {
        "min_dt": min_dt,
        "mean_dt": mean_dt,
        "max_dt": max_dt,
        "status_codes": status_codes
    }

def main():
    """
    Main insertion point
    """
    parser = argparse.ArgumentParser(
        description="""Simulate the given number of simultaneous viewers against the
        given URL."""
    )
    parser.add_argument(
        "--viewer-count",
        required=True,
        type=int,
        help="""The number of viewers to simulate"""
    )
    parser.add_argument(
        "--viewer-period",
        required=True,
        type=int,
        help="The number seconds between refreshes by a viewer"
    )
    parser.add_argument(
        "--api-url",
        required=True,
        help="The API url endpoint to target."
    )
    parser.add_argument(
        "--teams",
        required=True,
        help="Comma separated list of team IDs."
    )
    parser.add_argument(
        "--full-stats",
        required=False,
        type=bool,
        help="Dump the full JSON representation of the stats for all requests."
    )
    pargs = parser.parse_args()
    stats_queue = multiprocessing.Queue()

    # For each viewer, spawn a process and let them go at it.
    procs = [
        multiprocessing.Process(
            target=viewer_main,
            args=(pargs.api_url, pargs.viewer_period, pargs.teams.split(","), stats_queue)) for
        _ in range(pargs.viewer_count)
    ]

    for proc in procs:
        proc.start()

    print("Press Enter to stop testing")
    input()

    for proc in procs:
        proc.terminate()
    
    stats = []
    while not stats_queue.empty():
        stats.append(stats_queue.get())
    
    if pargs.full_stats:
        print(json.dumps(stats))
    else:
        print(json.dumps(stat_summary(stats)))

if __name__ == "__main__":
    main()
