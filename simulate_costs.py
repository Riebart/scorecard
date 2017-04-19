"""
Given a collection of properties for the scoreboard system, estimate the cache
hit rate and the amount of DynamoDB capacity that will be required.
"""

import json
import random
import argparse


def __run(nkeys, nattempts, nclients=1):
    # We need k buckets representing caches
    caches = [set() for _ in xrange(nkeys)]

    nhits = 0
    nmisses = 0

    # For each round (n), sample all of the caches, and update the hit/miss
    # counts, then update the caches.
    for _ in xrange(nattempts):
        spread = random.sample(caches, nkeys)
        for _ in xrange(nclients):
            for i, c in zip(xrange(nkeys), spread):
                if i in c:
                    nhits += 1
                else:
                    nmisses += 1
                    c.add(i)

    return nhits / float(nhits + nmisses)


def __main():
    parser = argparse.ArgumentParser(
        description="Estimate the cache hit rate and required DynamoDB capacity"
    )
    parser.add_argument(
        "--num-teams", type=int, required=True, help="Number of teams")
    parser.add_argument(
        "--num-flags",
        type=int,
        required=True,
        help="Number of flags configured that need to be polled for each team")
    parser.add_argument(
        "--num-clients",
        type=int,
        required=True,
        help="Number of clients polling for scores")
    parser.add_argument(
        "--score-ttl",
        type=int,
        required=False,
        default=30,
        help="Number of seconds for which scores are cached")
    parser.add_argument(
        "--client-refresh",
        type=int,
        required=False,
        default=10,
        help="Number of seconds in between polls by a client")
    pargs = parser.parse_args()

    opportunities = pargs.score_ttl / pargs.client_refresh
    hit_chance = []
    for _ in xrange(100):
        hit_chance.append(
            __run(pargs.num_teams, opportunities, pargs.num_clients))

    p_hit = sum(hit_chance) / len(hit_chance)
    rps = (
        1 - p_hit
    ) * pargs.num_teams * pargs.num_flags * pargs.num_clients / pargs.client_refresh
    hph = 3600 * pargs.num_clients * pargs.num_teams / pargs.client_refresh
    print json.dumps(
        {
            "MeanCacheHitProbability": int(10000 * p_hit) / 10000.0,
            # Remember that weakly consistent reads are 2/RCU
            "EstimatedScoresTableRCU": rps / 2,
            "AverageRequestsPerSecond": rps,
            "EstimatedCostPerHour": {
                "DynamoDB":
                0.065 * (rps / 2) / 50,
                "Lambda":
                0.20 * hph / 1000000 + (p_hit + 5 *
                                        (1 - p_hit)) * 0.000000625 * hph,
                "APIGateway":
                3.5 * hph / 1000000,
                "S3":
                rps * 3600 / 100000 * 0.004
            }
        },
        indent=4)


if __name__ == "__main__":
    __main()
