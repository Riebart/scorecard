"""
A collection of functions and utilities shared across submission and tally
functions.
"""

import os
from random import random
from functools import wraps
from XrayChain import Chain as XrayChain


def traced_lambda(name):
    """
    Trace a lambda insertion point, creating the root chain, passing it in as
    a parameter, and logging the timing of the lambda. Requires a name for the
    root trace segment.
    """

    def __decorator(target):
        @wraps(target)
        def __wrapper(*args):
            event = args[0]
            context = args[1]

            # To decide whether or not to trace this call (for real),
            # use the OS environment variable (choosing 0.0 if the )
            try:
                sample_probability = float(
                    os.environ.get("XraySampleProbability", 0.0))
            except ValueError:
                sample_probability = 0.0

            # mock the Xray API calls if and only if the random() value is
            # NOT less than the sample probability.
            mock = random() >= sample_probability

            root_chain = XrayChain(mock=mock)
            segment_id = root_chain.log_start(name=name)
            task_chain = root_chain.fork_root()
            ret = target(*(args + (task_chain, )))
            if "team" in args[0]:
                http = {
                    "request": {
                        "url": "/score/" + str(event["team"]),
                        "method": "GET"
                    }
                }
                if "ClientError" in ret:
                    http["response"] = {"status": 400}
                else:
                    http["response"] = {"status": 200}
            else:
                http = None

            annotations = {
                "Application": "Scorecard",
                "BackendType": event["KeyValueBackend"]
            }
            if "annotations" in ret:
                annotations.update(ret["annotations"])
                del ret["annotations"]

            if os.environ.get("DEBUG", None) == "TRUE":
                ret["Debug"] = {"MockedXray": mock}

            root_chain.log_end(
                segment_id=segment_id,
                http=http,
                metadata={
                    "AWSRequestId":
                    context.aws_request_id
                    if context is not None else "<MISSING>"
                },
                annotations=annotations)
            root_chain.flush()
            task_chain.flush()
            return ret

        return __wrapper

    return __decorator

def binomial_list(flips, heads):
    """
    Return a list of n items where the numerators are [1,...,n] and the
    denomenators are (n-m)! and m!.
    """
    return [
        float(i) / j
        for i, j in zip(range(1, heads + 1), range(1, heads + 1))
    ] + [
        float(i) / j
        for i, j in zip(
            range(heads + 1, flips + 1), range(1, flips - heads + 2))
    ]

def coin_toss(flips, heads, p_head=0.5):
    """
    Return the probability of returning exactly the given number of heads out of
    the given number of flips, with the probability of a head being as given.
    """
    # p^m (1-p)^(n-m) Binomial[n,m]
    binomial = binomial_list(flips, heads)
    probabilities = [float(p_head) for _ in xrange(heads)] + [
        float(1 - p_head) for _ in xrange(flips - heads)
    ]
    return reduce(lambda a, b: a * b,
                  [a * b for a, b in zip(binomial, probabilities)])

def coin_toss_range(flips, min_heads, max_heads, p_head):
    """
    Return the probability of getting between the min and max number of heads
    out of the given number of flips, with the given probability of a head.
    """
    if min_heads < 0 or max_heads > flips:
        return float('nan')
    return sum([
        coin_toss(flips, heads, p_head)
        for heads in xrange(min_heads, max_heads + 1)
    ])

def coin_toss_counts(p_head, min_rate, max_rate, p_cutoff=0.999):
    """
    Determine the necessary number of coin tosses required to ensure, within the
    given probability, that the number of heads turned up is within the minimum
    and maximum rate given the probability of a head.
    """
    dflips = 128
    flips = dflips
    last_prob = 0.0
    last_flips = 0
    while True:
        prob = coin_toss_range(
            flips,
            int(min_rate * flips), int(max_rate * flips),
            p_head)
        if prob < p_cutoff:
            # Because of floating point error, two adjacent values
            # can have slightly different probabilities.
            if prob <= last_prob and flips > last_flips + 10:
                print (prob, last_prob), (flips, last_flips)
                raise RuntimeError("Specified rate range will not converge.")
            last_prob = prob
            last_flips = flips
            flips += dflips
        elif dflips > 1:
            flips -= dflips
            dflips /= 2
            flips += dflips
        else:
            break
    return flips
