#!/usr/bin/env python
"""
Run a set of tests that inserts flags into the DynamoDB table, and ensures that
all cases are covered when attempting to claim them.

Takes in a CloudFormation stack name and automatically idenfities URLs
to use.

Becuse moto has limited support for API Gateway, AWS Lambda, and IAM,
this uses a deployed stack for testing, and is unable to perform client
only testing. All tests are integration tests.
"""

from __future__ import print_function

import copy
import time
import uuid
import argparse
import traceback
from random import randint
from decimal import Decimal

import requests
import boto3
from botocore.exceptions import ClientError


def helpful_assert_equal(lhs, rhs):
    try:
        assert lhs == rhs
    except AssertionError as e:
        print(lhs)
        print(rhs)
        print(traceback.format_exc())
        raise e


def update_stack_parameters(stack_name, parameters):
    """
    Perform an in-place update of a CloudFormation stack that replaces only the
    parameters. Also deploys a new API Gateway stage to make the new parameters
    take effect in the body mapping templates.
    """
    print("Updating stack parameters...")
    cfn_client = boto3.client('cloudformation')
    api_client = boto3.client('apigateway')
    try:
        print("Updating stack...")
        cfn_client.update_stack(
            StackName=stack_name,
            UsePreviousTemplate=True,
            Parameters=parameters,
            Capabilities=['CAPABILITY_IAM'])
    except ClientError:
        print("    No stack update necessary")
    else:
        print("Waiting on stack update...")
        update_waiter = cfn_client.get_waiter('stack_update_complete')
        update_waiter.wait(StackName=stack_name)

    print("Deploying new API Gateway stage for new parameters...")
    api_resource = cfn_client.describe_stack_resources(
        StackName=stack_name,
        LogicalResourceId='API')['StackResources'][0]['PhysicalResourceId']
    api_client.create_deployment(restApiId=api_resource, stageName='Main')
    print("    Sleeping while new stage deployment propagates...")
    time.sleep(5)


def integration_tests(stack_name):
    """
    Run integration tests using HTTP requests against a deployed API by describing
    the CloudFormation stack, adding a collection of rows to the DynamoDB table
    and attempting to claim and tally them.
    """
    # The workflow for integration testing a live stack is as follows:
    # - Describe the stack to determine the API endpoint and Flags DDB table
    # - Populate some new flags in the DynamoDB table, tracking them for
    #   cleanup afterwards
    # - Use a collection of teams that are unlikely to be in the table already
    #   to test claiming and tallying the team's scores.
    cfn_client = boto3.client('cloudformation')
    ddb_client = boto3.client('dynamodb')

    print("Performing integration tests against stack: %s" % stack_name)
    stack_parameters = cfn_client.describe_stacks(
        StackName=stack_name)['Stacks'][0]['Parameters']

    print("Generating cache-free parameters...")
    cache_free_parameters = copy.deepcopy(stack_parameters)
    score_cache = [
        p for p in cache_free_parameters
        if p['ParameterKey'] == 'ScoreCacheLifetime'
    ][0]
    score_cache['ParameterValue'] = '0'
    flags_cache = [
        p for p in cache_free_parameters
        if p['ParameterKey'] == 'FlagCacheLifetime'
    ][0]
    flags_cache['ParameterValue'] = '0'

    update_stack_parameters(stack_name, cache_free_parameters)
    print("Cache parameter update complete")

    api_resource = cfn_client.describe_stack_resources(
        StackName=stack_name,
        LogicalResourceId='API')['StackResources'][0]['PhysicalResourceId']
    flags_table_name = cfn_client.describe_stack_resources(
        StackName=stack_name, LogicalResourceId='FlagsTable')[
            'StackResources'][0]['PhysicalResourceId']

    try:
        scores_table_name = cfn_client.describe_stack_resources(
            StackName=stack_name, LogicalResourceId='ScoresTable')[
                'StackResources'][0]['PhysicalResourceId']
    except IndexError:
        scores_table_name = None

    if [p for p in stack_parameters if p['ParameterKey'] == 'KeyValueBackend'
        ][0]['ParameterValue'] == 'S3':
        scores_table_name = None

    print("Inserting flag configuration into DynamoDB...")
    flags = populate_flags(flags_table_name, 5.0)

    api_endpoint = 'https://%s.execute-api.%s.amazonaws.com/Main' % (
        api_resource, boto3.Session().region_name)

    print("Setup successful")

    # Cache busting is handled by using newly generated team IDs each time. This
    # still necessitates some sleeping while we wait for the recovable flags to
    # do their thing.

    flags_record = []

    print("Running tests...")
    try:
        print("    Assert that a team's default score is 0")
        for team in [randint(10**35, 10**36) for _ in range(2)]:
            resp = requests.get(url=api_endpoint + "/score/" + str(team))
            helpful_assert_equal(resp.json(), {
                'score': 0.0,
                'team': str(team)
            })

        print("    Assert that each team cannot claim a non-existent flag")
        for team in [randint(10**35, 10**36) for _ in range(2)]:
            record = {'team': str(team), 'flag': str(uuid.uuid1())}
            flags_record.append(record)
            resp = requests.post(
                url=api_endpoint + "/flag",
                json=record,
                headers={
                    'Content-Type': 'application/json'
                })
            helpful_assert_equal(resp.json(), {'valid_flag': False})

        print("    Assert that each team can claim a durable simple flag.")
        for team in [randint(10**35, 10**36) for _ in range(2)]:
            record = {'team': str(team), 'flag': flags[0]['flag']}
            flags_record.append(record)
            resp = requests.post(
                url=api_endpoint + "/flag",
                json=record,
                headers={
                    'Content-Type': 'application/json'
                })
            helpful_assert_equal(resp.json(), {'valid_flag': True})
            resp = requests.get(url=api_endpoint + "/score/" + str(team))
            helpful_assert_equal(resp.json(), {
                'score': 1.0,
                'team': str(team)
            })

        print(
            "    Assert that an authenticated flag can only be claimed by the right team"
        )
        print("      Right team wrong key...")
        record = {
            'team': list(flags[1]['auth_key'].keys())[0],
            'auth_key': "",
            'flag': flags[1]['flag']
        }
        flags_record.append(record)
        resp = requests.post(
            url=api_endpoint + "/flag",
            json=record,
            headers={
                'Content-Type': 'application/json'
            })
        helpful_assert_equal(resp.json(), {'valid_flag': False})
        resp = requests.get(url=api_endpoint + "/score/" + str(record['team']))
        helpful_assert_equal(resp.json(), {
            'score': 0.0,
            'team': str(record['team'])
        })
        print("      Right team right key...")
        record = {
            'team': list(flags[1]['auth_key'].keys())[0],
            'auth_key': list(flags[1]['auth_key'].values())[0],
            'flag': flags[1]['flag']
        }
        flags_record.append(record)
        resp = requests.post(
            url=api_endpoint + "/flag",
            json=record,
            headers={
                'Content-Type': 'application/json'
            })
        helpful_assert_equal(resp.json(), {'valid_flag': True})
        resp = requests.get(url=api_endpoint + "/score/" + str(record['team']))
        helpful_assert_equal(resp.json(), {
            'score': 2.0,
            'team': str(record['team'])
        })
        print("      Wrong team right key...")
        record = {
            'team': randint(10**35, 10**36),
            'auth_key': list(flags[1]['auth_key'].values())[0],
            'flag': flags[1]['flag']
        }
        flags_record.append(record)
        resp = requests.post(
            url=api_endpoint + "/flag",
            json=record,
            headers={
                'Content-Type': 'application/json'
            })
        helpful_assert_equal(resp.json(), {'valid_flag': False})
        resp = requests.get(url=api_endpoint + "/score/" + str(record['team']))
        helpful_assert_equal(resp.json(), {
            'score': 0.0,
            'team': str(record['team'])
        })
        print("      Wrong team wrong key...")
        record = {
            'team': randint(10**35, 10**36),
            'auth_key': "",
            'flag': flags[1]['flag']
        }
        flags_record.append(record)
        resp = requests.post(
            url=api_endpoint + "/flag",
            json=record,
            headers={
                'Content-Type': 'application/json'
            })
        helpful_assert_equal(resp.json(), {'valid_flag': False})
        resp = requests.get(url=api_endpoint + "/score/" + str(record['team']))
        helpful_assert_equal(resp.json(), {
            'score': 0.0,
            'team': str(record['team'])
        })

        for flag_num in [2, 4]:
            print(
                "    Assert that revocable flags tally correctly only within their lifetime."
            )
            record = {
                'team': randint(10**35, 10**36),
                'flag': flags[flag_num]['flag']
            }
            flags_record.append(record)
            resp = requests.post(
                url=api_endpoint + "/flag",
                json=record,
                headers={
                    'Content-Type': 'application/json'
                })
            helpful_assert_equal(resp.json(), {'valid_flag': True})
            resp = requests.get(
                url=api_endpoint + "/score/" + str(record['team']))
            helpful_assert_equal(resp.json(), {
                'score': flag_num + 1.0,
                'team': str(record['team'])
            })
            time.sleep(1.5 * float(flags[flag_num]['timeout']))
            resp = requests.get(
                url=api_endpoint + "/score/" + str(record['team']))
            helpful_assert_equal(resp.json(), {
                'score': 0.0,
                'team': str(record['team'])
            })

            print("    Recovable alive flags with auth keys for the...")
            print("      Right team wrong key")
            record = {
                'team': list(flags[flag_num + 1]['auth_key'].keys())[0],
                'flag': flags[flag_num + 1]['flag'],
                'auth_key': "",
            }
            flags_record.append(record)
            resp = requests.post(
                url=api_endpoint + "/flag",
                json=record,
                headers={
                    'Content-Type': 'application/json'
                })
            helpful_assert_equal(resp.json(), {'valid_flag': False})
            resp = requests.get(
                url=api_endpoint + "/score/" + str(record['team']))
            helpful_assert_equal(resp.json(), {
                'score': 0.0,
                'team': str(record['team'])
            })

            print("      Right team right key")
            record = {
                'team': list(flags[flag_num + 1]['auth_key'].keys())[0],
                'flag': flags[flag_num + 1]['flag'],
                'auth_key': list(flags[flag_num + 1]['auth_key'].values())[0],
            }
            flags_record.append(record)
            resp = requests.post(
                url=api_endpoint + "/flag",
                json=record,
                headers={
                    'Content-Type': 'application/json'
                })
            helpful_assert_equal(resp.json(), {'valid_flag': True})
            resp = requests.get(
                url=api_endpoint + "/score/" + str(record['team']))
            helpful_assert_equal(resp.json(), {
                'score': flag_num + 1 + 1.0,
                'team': str(record['team'])
            })
            time.sleep(1.5 * float(flags[flag_num + 1]['timeout']))
            resp = requests.get(
                url=api_endpoint + "/score/" + str(record['team']))
            helpful_assert_equal(resp.json(), {
                'score': 0.0,
                'team': str(record['team'])
            })

            print("      Wrong team right key")
            record = {
                'team': randint(10**35, 10**36),
                'flag': flags[flag_num + 1]['flag'],
                'auth_key': list(flags[flag_num + 1]['auth_key'].values())[0],
            }
            flags_record.append(record)
            resp = requests.post(
                url=api_endpoint + "/flag",
                json=record,
                headers={
                    'Content-Type': 'application/json'
                })
            helpful_assert_equal(resp.json(), {'valid_flag': False})
            resp = requests.get(
                url=api_endpoint + "/score/" + str(record['team']))
            helpful_assert_equal(resp.json(), {
                'score': 0.0,
                'team': str(record['team'])
            })

            print("      Wrong team wrong key")
            record = {
                'team': randint(10**35, 10**36),
                'flag': flags[flag_num + 1]['flag'],
                'auth_key': "",
            }
            flags_record.append(record)
            resp = requests.post(
                url=api_endpoint + "/flag",
                json=record,
                headers={
                    'Content-Type': 'application/json'
                })
            helpful_assert_equal(resp.json(), {'valid_flag': False})
            resp = requests.get(
                url=api_endpoint + "/score/" + str(record['team']))
            helpful_assert_equal(resp.json(), {
                'score': 0.0,
                'team': str(record['team'])
            })

        print(
            "    Confirm that revocable-dead flags only count after they expire"
        )
        record = {'team': randint(10**35, 10**36), 'flag': flags[6]['flag']}
        flags_record.append(record)
        resp = requests.post(
            url=api_endpoint + "/flag",
            json=record,
            headers={
                'Content-Type': 'application/json'
            })
        helpful_assert_equal(resp.json(), {'valid_flag': True})
        resp = requests.get(url=api_endpoint + "/score/" + str(record['team']))
        helpful_assert_equal(resp.json(), {
            'score': 0.0,
            'team': str(record['team'])
        })
        time.sleep(1.5 * float(flags[6]['timeout']))
        resp = requests.get(url=api_endpoint + "/score/" + str(record['team']))
        helpful_assert_equal(resp.json(), {
            'score': 7.0,
            'team': str(record['team'])
        })

    except Exception as e:
        print("Tests Unsuccessful")
        print(traceback.format_exc())
        print(resp)
        print(resp.json())
    else:
        print("Tests successful")

    for record in flags_record:
        flag = record['flag']
        team = record['team']
        if scores_table_name is not None:
            ddb_client.delete_item(
                TableName=scores_table_name, Key={
                    'team': {
                        'N': str(team)
                    }
                })
        ddb_client.delete_item(
            TableName=flags_table_name, Key={
                'flag': {
                    'S': flag
                }
            })

    for flag in flags:
        ddb_client.delete_item(
            TableName=flags_table_name, Key={
                'flag': {
                    'S': flag['flag']
                }
            })

    print("Cleanup successful")

    update_stack_parameters(stack_name, stack_parameters)

    print("Cache policy restoration complete")


def populate_flags(table_name=None, timeout=0.5):
    """
    Generate and populate a collection of randomly generated flags, and return
    them.
    """
    flags = [
        # A simple durable flag
        {
            'flag': str(uuid.uuid1())
        },
        # A durable flag with an auth key for one team
        {
            'flag': str(uuid.uuid1()),
            'auth_key': {
                str(randint(10**35, 10**36)): "1"
            }
        },
        # A simple recovable-alive flag, 'yes' unspecified
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(timeout)
        },
        # A recovable-alive flag with an auth key for one team, 'yes' unspecified
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(timeout),
            'auth_key': {
                str(randint(10**35, 10**36)): "2"
            }
        },
        # A simple recovable-alive flag, 'yes' specified to TRUE
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(timeout),
            'yes': True
        },
        # A recovable-alive flag with an auth key for one team, 'yes' specified to TRUE
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(timeout),
            'auth_key': {
                str(randint(10**35, 10**36)): "2"
            },
            'yes': True
        },
        # A simple recovable-dead flag
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(timeout),
            'yes': False
        },
        # A recovable-dead flag with an auth key for one team
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(timeout),
            'auth_key': {
                str(randint(10**35, 10**36)): "3"
            },
            'yes': False
        },
        # A simple durable flag that WILL NOT HAVE A WEIGHT
        {
            'flag': str(uuid.uuid1())
        },
    ]

    if table_name is not None:
        flags_table = boto3.resource('dynamodb').Table(table_name)
    else:
        flags_table = None

    for flag_id in range(len(flags)):
        flag = flags[flag_id]
        if flag_id < len(flags) - 1:
            flag['weight'] = flag_id + 1
        else:
            pass
        if flags_table is not None:
            flags_table.put_item(Item=flag)

    return flags


def setup_s3_backend():
    """
    Create the AWS resources for an S3 key-value backend, and return the event body template
    """
    s3_client = boto3.client('s3')
    dynamodb_client = boto3.client('dynamodb')

    s3_bucket = str(uuid.uuid1())
    s3_prefix = str(uuid.uuid1()) + "/" + str(uuid.uuid1())
    s3_client.create_bucket(Bucket=s3_bucket)

    flags_table = str(uuid.uuid1())
    dynamodb_client.create_table(
        TableName=flags_table,
        AttributeDefinitions=[{
            'AttributeName': 'flag',
            'AttributeType': 'S'
        }],
        KeySchema=[{
            'AttributeName': 'flag',
            'KeyType': 'HASH'
        }],
        ProvisionedThroughput={
            'ReadCapacityUnits': 1,
            'WriteCapacityUnits': 1
        })
    flags = populate_flags(flags_table)

    return {
        'KeyValueS3Bucket': s3_bucket,
        'KeyValueS3Prefix': s3_prefix,
        'FlagsTable': flags_table,
        'KeyValueBackend': 'S3',
        'Flags': flags
    }


def setup_dynamodb_backend():
    """
    Create the AWS resources for a DynamoDB key-value backend, and return the event body template
    """
    dynamodb_client = boto3.client('dynamodb')

    flags_table = str(uuid.uuid1())
    scores_table = str(uuid.uuid1())

    dynamodb_client.create_table(
        TableName=flags_table,
        AttributeDefinitions=[{
            'AttributeName': 'flag',
            'AttributeType': 'S'
        }],
        KeySchema=[{
            'AttributeName': 'flag',
            'KeyType': 'HASH'
        }],
        ProvisionedThroughput={
            'ReadCapacityUnits': 1,
            'WriteCapacityUnits': 1
        })
    flags = populate_flags(flags_table)

    dynamodb_client.create_table(
        TableName=scores_table,
        AttributeDefinitions=[{
            'AttributeName': 'team',
            'AttributeType': 'N'
        }, {
            'AttributeName': 'flag',
            'AttributeType': 'S'
        }],
        KeySchema=[{
            'AttributeName': 'team',
            'KeyType': 'HASH'
        }, {
            'AttributeName': 'flag',
            'KeyType': 'RANGE'
        }],
        ProvisionedThroughput={
            'ReadCapacityUnits': 1,
            'WriteCapacityUnits': 1
        })

    return {
        'ScoresTable': scores_table,
        'FlagsTable': flags_table,
        'KeyValueBackend': 'DynamoDB',
        'Flags': flags
    }


def create_s3_bucket():
    """
    Just create an S3 bucket and return the bucket name.
    """
    s3_client = boto3.client('s3')
    bucket_name = str(uuid.uuid1())
    s3_client.create_bucket(Bucket=bucket_name)
    return bucket_name


def __main():
    """
    Main method for running tests and generating table data.
    """
    parser = argparse.ArgumentParser(
        description="Run tests against the codebase.")
    parser.add_argument(
        "--stack-name",
        required=False,
        default=None,
        help="""Stack name to use for deployed-stack testing. useful for testing
        integration and end-to-end configuration as moto is unable to test
        API Gateway, AWS Lambda, or IAM.""")
    pargs = parser.parse_args()

    if pargs.stack_name is not None:
        integration_tests(pargs.stack_name)


if __name__ == "__main__":
    # Configure the default region for boto3/moto.
    import os
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    __main()
