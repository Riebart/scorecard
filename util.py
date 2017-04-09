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

            if os.environ["DEBUG"] == "TRUE":
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
