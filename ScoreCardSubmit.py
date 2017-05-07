#!/usr/bin/env python
"""
Ingest a flag and update the DynamoDB table accordingly.
"""

import time
from decimal import Decimal
import boto3

from S3KeyValueStore import Table as S3Table
from util import traced_lambda

BACKEND_TYPE = None
# Cache the table backends, as appropriate.
BACKEND_TYPE = None
SCORES_TABLE = None
FLAGS_TABLE = None

# Flag data is only scanned from the flags DynamoDB table every 30 seconds to
# conserve DynamoDB table capacity.
FLAGS_DATA = {'check_interval': 30}


# Note that there is already an awslambda infrastructure module called init()
# and this clobbers things, so it's renamed to a private scoped function.
def __module_init(event, chain):
    """
    Initialize module-scope resources, such as caches and DynamoDB resources.
    """
    global BACKEND_TYPE
    global SCORES_TABLE
    global FLAGS_TABLE

    if BACKEND_TYPE != event['KeyValueBackend']:
        # print "Switching backend: %s to %s" % (BACKEND_TYPE,
        #                                        event["KeyValueBackend"])
        SCORES_TABLE = None
        FLAGS_TABLE = None

    if SCORES_TABLE is None or FLAGS_TABLE is None:
        swap_chain = chain.fork_root()
        segment_id = swap_chain.log_start("BackendSwap")
        # print "Configuring backend resource connectors"
        BACKEND_TYPE = event['KeyValueBackend']
        ddb_resource = boto3.resource('dynamodb')
        if event['KeyValueBackend'] == 'DynamoDB':
            SCORES_TABLE = ddb_resource.Table(event['ScoresTable'])
        else:
            SCORES_TABLE = S3Table(event['KeyValueS3Bucket'],
                                   event['KeyValueS3Prefix'], ['flag', 'team'])
        FLAGS_TABLE = ddb_resource.Table(event['FlagsTable'])
        swap_chain.log_end(segment_id)

        # Prime the pump by scanning for flags
        FLAGS_DATA['check_time'] = time.time()
        FLAGS_DATA['flags'] = swap_chain.trace("SwapFlagScan")(
            FLAGS_TABLE.scan)()['Items']


def update_flag_data(chain):
    """
    Check to see if the flag data should be updated from DynamoDB, and do so
    if required.

    Regardless, return the current flag data.
    """
    if time.time() > (FLAGS_DATA['check_time'] + FLAGS_DATA['check_interval']):
        update_chain = chain.fork_subsegment()
        scan_result = update_chain.trace("PeriodicFlagScan")(
            FLAGS_TABLE.scan)()
        FLAGS_DATA['flags'] = scan_result.get('Items', [])
        FLAGS_DATA['check_time'] = time.time()

    return FLAGS_DATA['flags']


@traced_lambda("ScorecardSubmit")
def lambda_handler(event, _, chain=None):
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

    chain.trace_associated("ModuleInit")(__module_init)(event, chain)
    flag_data = chain.trace_associated("FlagDataUpdate")(update_flag_data)(
        chain)

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
        response['client_error'] = [
            '"team" key must exist and be integeral or parsable as integral'
        ]

    if 'flag' not in event:
        if 'client_error' in response:
            response['client_error'].append('"flag" key must exist')
        else:
            response['client_error'] = ['"flag key must exist']

    if len(response.keys()) > 0:
        return response

    # Look for the flag in the flags table.
    # flag_item = FLAGS_TABLE.get_item(Key={'flag': str(event['flag'])})
    flag_items = [
        flag for flag in flag_data if flag['flag'] == str(event['flag'])
    ]

    if len(flag_items) == 0:
        return {'valid_flag': False}
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
                return {'valid_flag': False}

            # Check if the auth_key provided matches the auth_key for the flag
            # for this team.
            if str(event['team']) not in flag_item['auth_key'] or event[
                    'auth_key'] != flag_item['auth_key'][str(event['team'])]:
                return {'valid_flag': False}

        chain.trace("FlagSubmit")(SCORES_TABLE.update_item)(
            Key={
                "team": event["team"]
            },
            UpdateExpression="set %s=:last_seen" % event["flag"],
            ExpressionAttributeValues={
                ":last_seen": {
                    "N": repr(time.time())
                }
            })
        return {'valid_flag': True}
