#!/usr/bin/env python
"""
Given a team number, tally the score of that team.
"""

import time
import boto3
from S3KeyValueStore import Table as S3Table

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
TEAM_SCORE_CACHE = {'timeout': 30}

# Flag data is only scanned from the flags DynamoDB table every 30 seconds to
# conserve DynamoDB table capacity.
FLAGS_DATA = {'check_interval': 30}


# Note that there is already an awslambda infrastructure module called init()
# and this clobbers things, so it's renamed to a private scoped function.
def __module_init(event):
    """
    Initialize module-scope resources, such as caches and DynamoDB resources.
    """
    global BACKEND_TYPE
    global SCORES_TABLE
    global FLAGS_TABLE

    if BACKEND_TYPE != event['KeyValueBackend']:
        SCORES_TABLE = None
        FLAGS_TABLE = None

    if SCORES_TABLE is None or FLAGS_TABLE is None:
        BACKEND_TYPE = event['KeyValueBackend']
        ddb_resource = boto3.resource('dynamodb')
        if event['KeyValueBackend'] == 'DynamoDB':
            SCORES_TABLE = ddb_resource.Table(event['ScoresTable'])
        else:
            SCORES_TABLE = S3Table(event['KeyValueS3Bucket'],
                                   event['KeyValueS3Prefix'], ['flag', 'team'])
        FLAGS_TABLE = ddb_resource.Table(event['FlagsTable'])

        # Prime the pump by scanning for flags
        FLAGS_DATA['check_time'] = time.time()
        FLAGS_DATA['flags'] = FLAGS_TABLE.scan()['Items']


def update_flag_data():
    """
    Check to see if the flag data should be updated from DynamoDB, and do so
    if required.

    Regardless, return the current flag data.
    """
    if time.time() > (FLAGS_DATA['check_time'] + FLAGS_DATA['check_interval']):
        scan_result = FLAGS_TABLE.scan()
        FLAGS_DATA['flags'] = scan_result.get('Items', [])
        FLAGS_DATA['check_time'] = time.time()

    return FLAGS_DATA['flags']


def score_flag(team, flag):
    """
    Given a team ID, and a flag DynamoDB row.
    """
    item = SCORES_TABLE.get_item(Key={'team': team, 'flag': flag['flag']})
    if 'Item' in item:
        team_flag = item['Item']

        # Try to fetch the weight of the flag, ignore it otherwise.
        if 'weight' not in flag:
            return None
        else:
            flag_weight = float(flag['weight'])

        # Check to see if there's a timeout value for this flag.
        if 'timeout' in flag:
            # if there is, check to see if the flag needs to have been seen
            # within the last timeout, or NOT have been seen.
            # If the 'yes' value is not in the flag row, then assume it is
            # True.
            flag_timeout = float(flag['timeout'])
            last_seen = float(team_flag['last_seen'])
            if 'yes' not in flag or flag['yes']:
                # If the flag was NOT seen in the last flag_timeout seconds,
                # then return nothing.
                if last_seen < time.time() - flag_timeout:
                    return None
            else:
                # If the flag WAS seen in the last flag_timeout seconds, then
                # return nothing.
                if last_seen > time.time() - flag_timeout:
                    return None

        return flag_weight
    else:
        return None


def lambda_handler(event, _):
    """
    Insertion point for AWS Lambda
    """
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
        TEAM_SCORE_CACHE['timeout'] = float(event['ScoreCacheLifetime'])
    except:
        pass

    try:
        FLAGS_DATA['check_interval'] = float(event['FlagCacheLifetime'])
    except:
        pass

    __module_init(event)
    flag_data = update_flag_data()

    try:
        team = int(event['team'])
    except ValueError:
        team = None
    except KeyError:
        team = None

    if team is None:
        return {
            'ClientError':
            ['"team" key must exist and be integeral or parsable as integral']
        }

    # At this point, check to see if the score for the requested team still has
    # a cache entry, and check whether it is stale or not. If it is stale, then
    # recompute, otherwise return the cached value.
    if team in TEAM_SCORE_CACHE and \
        TEAM_SCORE_CACHE[team]['time'] > (time.time() - TEAM_SCORE_CACHE['timeout']):
        return {'Team': team, 'Score': TEAM_SCORE_CACHE[team]['score']}

    score = 0.0
    scores = []

    for flag in flag_data:
        # For each flag DDB row, try to score each flag for the team.
        flag_score = score_flag(team, flag)
        scores.append([flag['flag'], flag_score])
        if flag_score is not None:
            score += float(flag_score)

    TEAM_SCORE_CACHE[team] = {'score': score, 'time': time.time()}
    return {'Team': team, 'Score': score}
