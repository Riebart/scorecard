#!/usr/bin/env python
"""
Given a team number, tally the score of that team.
"""

import time
import boto3

DDB_RESOURCE = boto3.resource('dynamodb')
TEAMS = DDB_RESOURCE.Table('ScoreCard-Teams')
FLAGS = DDB_RESOURCE.Table('ScoreCard-Flags')
TEAM_SCORE_CACHE = {'timeout': 10}
FLAGS_DATA = {
    'flags': FLAGS.scan()['Items'],
    'check_time': time.time(),
    'check_interval': 30
}


def update_flag_data():
    """
    Check to see if the flag data should be updated from DynamoDB, and do so
    if required.

    Regardless, return the current flag data.
    """
    if time.time() > (FLAGS_DATA['check_time'] + FLAGS_DATA['check_interval']):
        FLAGS_DATA['flags'] = FLAGS.scan()['Items']
        FLAGS_DATA['check_time'] = time.time()

    return FLAGS_DATA['flags']


def score_flag(team, flag):
    """
    Given a team ID, and a flag DynamoDB row.
    """
    item = TEAMS.get_item(Key={'team': team, 'flag': flag['flag']})
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


def lambda_handler(event, context):
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

    flag_data = update_flag_data()

    if 'team' in event:
        try:
            team = int(event['team'])
        except ValueError:
            team = None
    else:
        team = None

    if team is None:
        return {
            'ClientError': ['"team" key must exist and be parsable integer']
        }

    # At this point, check to see if the score for the requested team still has
    # a cache entry, and check whether it is stale or not. If it is stale, then
    # recompute, otherwise return the cached value.
    if team in TEAM_SCORE_CACHE and \
        TEAM_SCORE_CACHE[team][1] > (time.time() - TEAM_SCORE_CACHE['timeout']):
        return {'Team': team, 'Score': TEAM_SCORE_CACHE[team][0]}

    score = 0.0
    scores = []

    for flag in flag_data:
        # For each flag DDB row, try to score each flag for the team.
        flag_score = score_flag(team, flag)
        scores.append([flag['flag'], flag_score])
        if flag_score is not None:
            score += float(flag_score)

    TEAM_SCORE_CACHE[team] = (score, time.time())
    return {'Team': team, 'Score': score}
