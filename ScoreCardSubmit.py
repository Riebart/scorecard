#!/usr/bin/env python
"""
Ingest a flag and update the DynamoDB table accordingly.
"""

import time
from decimal import Decimal
import boto3
from S3KeyValueStore import Table as S3Table

# Cache the table backends, as appropriate.
SCORES_TABLE = None
FLAGS_TABLE = None

# Flag data is only scanned from the flags DynamoDB table every 30 seconds to
# conserve DynamoDB table capacity.
FLAGS_DATA = {'check_interval': 30}


# Note that there is already an awslambda infrastructure module called init()
# and this clobbers things, so it's renamed to a private scoped function.
def __module_init(event):
    """
    Initialize module-scope resources, such as caches and DynamoDB resources.
    """
    global SCORES_TABLE
    global FLAGS_TABLE
    if SCORES_TABLE is None or FLAGS_TABLE is None:
        ddb_resource = boto3.resource('dynamodb')
        if event['KeyValueBackend'] == 'DynamoDB':
            SCORES_TABLE = ddb_resource.Table(event['ScoresTable'])
        else:
            SCORES_TABLE = S3Table(event['S3Bucket'], event['S3Prefix'],
                                   ['flag', 'team'])
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
    else:
        pass

    return FLAGS_DATA['flags']


def lambda_handler(event, _):
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

    # If the values are in the event body, attempt to parse them as floats and
    # update the cache objects at the global scope.
    try:
        FLAGS_DATA['check_interval'] = float(event['FlagCacheLifetime'])
    except:
        pass

    __module_init(event)
    flag_data = update_flag_data()

    # Validate input format
    response = dict()

    # The team is either an integer or None after this block.
    try:
        event['team'] = int(event['team'])
    except ValueError:
        event['team'] = None
    except KeyError:
        event['team'] = None

    if event['team'] is None:
        response['ClientError'] = [
            '"team" key must exist and be integeral or parsable as integral'
        ]

    if 'flag' not in event:
        if 'ClientError' in response:
            response['ClientError'].append('"flag" key must exist')
        else:
            response['ClientError'] = ['"flag key must exist']

    if len(response.keys()) > 0:
        return response

    # Look for the flag in the flags table.
    # flag_item = FLAGS_TABLE.get_item(Key={'flag': str(event['flag'])})
    flag_items = [
        flag for flag in flag_data if flag['flag'] == str(event['flag'])
    ]

    if len(flag_items) == 0:
        return {'ValidFlag': False}
    else:
        # Check to ensure that if the auth_key parameter exists for this flag,
        # that there is an auth_key parameter in the request, and that it matches
        # the auth_key for that team in the flag's definition.
        #
        # If the flag's definition doesn't specify an auth_key for the given
        # team, then the team cannot claim this flag.
        flag_item = flag_items[0]
        if 'auth_key' in flag_item:
            if 'auth_key' not in event:
                return {'ValidFlag': False}

            # Check if the auth_key provided matches the auth_key for the flag
            # for this team.
            if event['auth_key'] != flag_item['auth_key'][str(event['team'])]:
                return {'ValidFlag': False}

        SCORES_TABLE.put_item(Item={
            'team': event['team'],
            'flag': event['flag'],
            'last_seen': Decimal(time.time())
        })
        return {'ValidFlag': True}


def unit_tests(event):
    """
    Run unit tests against moto or other local resources.
    """
    global SCORES_TABLE
    global FLAGS_TABLE
    global FLAGS_DATA
    SCORES_TABLE = None
    FLAGS_TABLE = None
    FLAGS_DATA = {'check_interval': 30}

    flags = event['Flags']

    # Assert that lack of 'team' AND 'flag' results in a ClientError
    res = lambda_handler(event, None)
    assert 'ClientError' in res
    assert len(res['ClientError']) == 2

    # Assert that lack of 'team' OR 'flag' results in a ClientError
    event['team'] = 10
    res = lambda_handler(event, None)
    assert 'ClientError' in res
    assert len(res['ClientError']) == 1
    del event['team']
    event['flag'] = ''
    res = lambda_handler(event, None)
    assert 'ClientError' in res
    assert len(res['ClientError']) == 1

    # Assert that the team must be integral (or parsable as integral)
    event['team'] = 'abcde'
    res = lambda_handler(event, None)
    assert 'ClientError' in res
    assert len(res['ClientError']) == 1

    # Assert that the team must be integral (or parsable as integral)
    event['team'] = 10
    res = lambda_handler(event, None)
    assert 'ClientError' not in res

    # Assert that the team must be integral (or parsable as integral)
    event['team'] = '10'
    res = lambda_handler(event, None)
    assert 'ClientError' not in res

    # Attempt to claim a nonexistent flag
    event['team'] = 10
    event['flag'] = ""
    res = lambda_handler(event, None)
    assert res == {'ValidFlag': False}

    # A simple durable flag
    event['team'] = 10
    event['flag'] = flags[0]['flag']
    res = lambda_handler(event, None)
    assert res == {'ValidFlag': True}

    # Override the interval for flag refreshing so that the refresh occurs
    event['FlagCacheLifetime'] = 0

    # A durable flag with an auth key for one team as the wrong team
    event['team'] = 1
    event['flag'] = flags[1]['flag']
    res = lambda_handler(event, None)
    assert res == {'ValidFlag': False}

    # A durable flag with an auth key for one team as the right team and right key
    event['team'] = flags[1]['auth_key'].keys()[0]
    event['flag'] = flags[1]['flag']
    event['auth_key'] = flags[1]['auth_key'][event['team']]
    res = lambda_handler(event, None)
    assert res == {'ValidFlag': True}

    # A durable flag with an auth key for one team as the right team with the wrong key
    event['team'] = flags[1]['auth_key'].keys()[0]
    event['flag'] = flags[1]['flag']
    event['auth_key'] = ""
    res = lambda_handler(event, None)
    assert res == {'ValidFlag': False}
