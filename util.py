"""
A collection of functions and utilities shared across submission and tally
functions.
"""

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
            root_chain = XrayChain()
            segment_id = root_chain.log_start(name=name)
            task_chain = root_chain.fork(False)
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
