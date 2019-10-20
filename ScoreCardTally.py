#!/usr/bin/env python
"""
Given a team number, tally the score of that team.
"""

import time
import hashlib

import boto3
try:
    from S3KeyValueStore import Table as S3Table
except:
    print("Ignoring S3 backend.")
from util import traced_lambda

BACKEND_TYPE = None
# Cache the table backends, as appropriate.
SCORES_TABLE = None
FLAGS_TABLE = None

# Team scores are only recalculated periodically to conserve costs and capacity
# on the DynamoDB table backend (if selected) at the expense of responsiveness
# of the scoreboard views to newly claimed flags.
#
# This protects the backend and potential cost of running this from abusively
# fast refreshing dashboard clients.
TEAM_SCORE_CACHE = {"timeout": 30}

# Flag data is only scanned from the flags DynamoDB table every 30 seconds to
# conserve DynamoDB table capacity.
FLAGS_DATA = {"check_interval": 30}


# Note that there is already an awslambda infrastructure module called init()
# and this clobbers things, so it's renamed to a private scoped function.
def __module_init(event, chain):
    """
    Initialize module-scope resources, such as caches and DynamoDB resources.
    """
    global BACKEND_TYPE
    global SCORES_TABLE
    global FLAGS_TABLE

    if BACKEND_TYPE != event["KeyValueBackend"]:
        # print "Switching backend: %s to %s" % (BACKEND_TYPE,
        #                                        event["KeyValueBackend"])
        SCORES_TABLE = None
        FLAGS_TABLE = None

    if SCORES_TABLE is None or FLAGS_TABLE is None:
        swap_chain = chain.fork_root()
        segment_id = swap_chain.log_start("BackendSwap")
        # print "Configuring backend resource connectors"
        BACKEND_TYPE = event["KeyValueBackend"]
        ddb_resource = boto3.resource("dynamodb")
        if event["KeyValueBackend"] == "DynamoDB":
            SCORES_TABLE = ddb_resource.Table(event["ScoresTable"])
        else:
            SCORES_TABLE = S3Table(event["KeyValueS3Bucket"],
                                   event["KeyValueS3Prefix"], ["flag", "team"])
        FLAGS_TABLE = ddb_resource.Table(event["FlagsTable"])
        swap_chain.log_end(segment_id)

        # Prime the pump by scanning for flags
        FLAGS_DATA["check_time"] = time.time()
        FLAGS_DATA["flags"] = swap_chain.trace("SwapFlagScan")(
            FLAGS_TABLE.scan)()["Items"]


def update_flag_data(chain):
    """
    Check to see if the flag data should be updated from DynamoDB, and do so
    if required.

    Regardless, return the current flag data.
    """
    if time.time() > (FLAGS_DATA["check_time"] + FLAGS_DATA["check_interval"]):
        update_chain = chain.fork_subsegment()
        scan_result = update_chain.trace("PeriodicFlagScan")(
            FLAGS_TABLE.scan)()
        FLAGS_DATA["flags"] = scan_result.get("Items", [])
        FLAGS_DATA["check_time"] = time.time()

    return FLAGS_DATA["flags"]


def score_flag(team, flag, item, sim_time):
    """
    Given a team ID, and a flag DynamoDB row.
    """
    # Attempt to get the flag last_seen value from the ddb item, otherwise
    # just return None.
    last_seen = item.get(flag["flag"], None)
    if last_seen is not None:
        # Try to fetch the weight of the flag, ignore it otherwise.
        if "weight" not in flag:
            return None
        else:
            flag_weight = float(flag["weight"])

        # Check to see if there's a timeout value for this flag.
        if "timeout" in flag:
            # if there is, check to see if the flag needs to have been seen
            # within the last timeout, or NOT have been seen.
            # If the 'yes' value is not in the flag row, then assume it is
            # True.
            flag_timeout = float(flag["timeout"])
            if "yes" not in flag or flag["yes"]:
                # If the flag was NOT seen in the last flag_timeout seconds,
                # then return nothing.
                if last_seen < sim_time - flag_timeout:
                    return None
            else:
                # If the flag WAS seen in the last flag_timeout seconds, then
                # return nothing.
                if last_seen > sim_time - flag_timeout:
                    return None

        return flag_weight
    else:
        return None


def score_bitmask(scores):
    """
    Given a list of tuple pairings from the score key name to the score value, canonically sort
    the list by the score key name, and convert the values to boolean (with TRUE <=> != 0)
    """
    return [
        dict(
            zip(["hash", "claimed", "nickname"], (hashlib.sha256(
                score[0]).hexdigest(), score[1] not in [0.0, None], score[2])))
        for score in sorted(scores)
    ]


@traced_lambda("ScorecardTally")
def lambda_handler(event, context, chain=None):
    """
    Insertion point for AWS Lambda
    """
    start_time = time.time()
    # Expected format of the event object.
    # - team

    # General logic flow
    # - Given a team number, find all items in the DynamoDB table that match
    #   the team number.
    # - Correlate these rows, and the flags in them, with the flags table
    #   to determine whether each flag for the team is still valid (given
    #   timeout information) and weight.
    # - Return the score.

    # If the values are in the event body, attempt to parse them as floats and
    # update the cache objects at the global scope.
    try:
        TEAM_SCORE_CACHE["timeout"] = float(event["ScoreCacheLifetime"])
    except:
        pass

    try:
        FLAGS_DATA["check_interval"] = float(event["FlagCacheLifetime"])
    except:
        pass

    chain.trace_associated("ModuleInit")(__module_init)(event, chain)
    flag_data = chain.trace_associated("FlagDataUpdate")(update_flag_data)(
        chain)

    try:
        team = int(event["team"])
    except ValueError:
        team = None
    except KeyError:
        team = None

    if team is None:
        return {
            "client_error": [
                "\"team\" key must exist and be integral or parsable as integral"
            ]
        }

    # At this point, check to see if the score for the requested team still has
    # a cache entry, and check whether it is stale or not. If it is stale, then
    # recompute, otherwise return the cached value.
    try:
        disable_cache = context.disable_cache
    except:  # pylint: disable=W0702
        disable_cache = False

    if not disable_cache and team in TEAM_SCORE_CACHE and \
        TEAM_SCORE_CACHE[team]["time"] > (start_time - TEAM_SCORE_CACHE["timeout"]):
        return {
            "team": str(team),
            "score": TEAM_SCORE_CACHE[team]["score"],
            "bitmask": TEAM_SCORE_CACHE[team]["bitmask"],
            "annotations": {
                "Cache": "Hit"
            }
        }

    score = 0.0
    scores = []

    segment_id = chain.log_start("ScoreCalculation")
    score_chain = chain.fork_subsegment()

    # Get the DynamoDB row for the team. If there is no such row, use a simple
    # dict with the team key set to the team ID.
    ddb_row = score_chain.trace("GetItem")(SCORES_TABLE.get_item)(Key={
        "team": team
    })
    ddb_item = ddb_row.get("Item", {"team": team})

    for flag in flag_data:
        try:
            sim_time = context.sim_time
        except:  # pylint: disable=W0702
            sim_time = time.time()

        # For each flag DDB row, try to score each flag for the team.
        flag_score = score_chain.trace("ScoreFlag")(score_flag)(team, flag,
                                                                ddb_item,
                                                                sim_time)
        scores.append([
            flag["flag"], flag_score,
            flag.get("nickname", "NONICK: %s" % flag["flag"])
        ])
        if flag_score is not None:
            score += float(flag_score)

    bitmask = score_bitmask(scores)
    chain.log_end(segment_id)

    TEAM_SCORE_CACHE[team] = {
        "score": score,
        "time": start_time,
        "bitmask": bitmask
    }
    return {
        "team": str(team),
        "score": score,
        "bitmask": bitmask,
        "annotations": {
            "Cache": "Miss"
        }
    }
