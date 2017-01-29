#!/usr/bin/env python
"""
Ingest a flag and update the DynamoDB table accordingly.
"""

import time
from decimal import Decimal
import boto3

DDB_RESOURCE = boto3.resource('dynamodb')
TEAMS = DDB_RESOURCE.Table('ScoreCard-Teams')
FLAGS = DDB_RESOURCE.Table('ScoreCard-Flags')


def lambda_handler(event, context):
    """
    Insertion point for AWS Lambda
    """
    # Expected format of the event object.
    # - team
    # - flag

    # General logic flow:
    # - Receive request, ensure that it has the required keys.
    #  - Any extraneous keys are ignores.
    # - Check if flag exists in flags table (as a key). If the flag is not a
    #   string, then use the str() of the flag value in the event. The
    #   resulting string is converted to upper case when getting the item from
    #   DynamoDB.
    #  - If flag doesn't exist, return False
    #  - If flag exists, insert item mapping time seen, team, and flag in the
    #    teams table, return True.

    # Validate input format
    response = dict()
    if 'team' not in event or not isinstance(event['team'], int):
        response['ClientError'] = ['"team" key must exist and be an integer']

    if 'flag' not in event:
        if 'ClientError' in response:
            response['ClientError'].append('"flag" key must exist')
        else:
            response['ClientError'] = ['"flag key must exist']

    if len(response.keys()) > 0:
        return response

    # Look for the flag in the flags table.
    flag_item = FLAGS.get_item(Key={'flag': str(event['flag'])})
    if 'Item' not in flag_item or len(flag_item['Item']) == 0:
        return {'ValidFlag': False}
    else:
        # Check to ensure that if the auth_key parameter exists for this flag,
        # that there is an auth_key parameter in the request, and that it matches
        # the auth_key for that team in the flag's definition.
        #
        # If the flag's definition doesn't specify an auth_key for the given
        # team, then the team cannot claim this flag.
        flag_item = flag_item['Item']
        if 'auth_key' in flag_item:
            if 'auth_key' not in event:
                return {'ValidFlag': False}

            # Check if the auth_key provided matches the auth_key for the flag
            # for this team.
            if event['auth_key'] != flag_item['auth_key'][str(event['team'])]:
                return {'ValidFlag': False}

        TEAMS.put_item(Item={
            'team': event['team'],
            'flag': event['flag'],
            'last_seen': Decimal(time.time())
        })
        return {'ValidFlag': True}
