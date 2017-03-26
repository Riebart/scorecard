#!/usr/bin/env python
"""
Run a set of tests that inserts flags into the DynamoDB table, and ensures that all cases are covered when attempting to claim them.

Takes in a CloudFormation stack name and automatically idenfities URLs
to use.

Becuse moto has limited support for API Gateway, AWS Lambda, and IAM,
this uses a deployed stack for testing, and is unable to perform client
only testing. All tests are integration tests.
"""

import uuid
import argparse
from random import randint
from decimal import Decimal

import requests
import boto3
from moto import mock_s3, mock_dynamodb2


def integration_tests(stack_name):
    """
    Run integration tests using HTTP requests against a deployed API by describing
    the CloudFormation stack, adding a collection of rows to the DynamoDB table
    and attempting to claim and tally them.
    """
    import json
    # The workflow for integration testing a live stack is as follows:
    # - Describe the stack to determine the API endpoint and Flags DDB table
    # - Populate some new flags in the DynamoDB table, tracking them for
    #   cleanup afterwards
    # - Use a collection of teams that are unlikely to be in the table already
    #   to test claiming and tallying the team's scores.
    cfn_client = boto3.client('cloudformation')
    ddb_client = boto3.client('dynamodb')
    api_resource = cfn_client.describe_stack_resources(
        StackName='ScoreCard',
        LogicalResourceId='API')['StackResources'][0]['PhysicalResourceId']
    flags_table_name = cfn_client.describe_stack_resources(
        StackName='ScoreCard', LogicalResourceId='FlagsTable')[
            'StackResources'][0]['PhysicalResourceId']
    scores_table_name = cfn_client.describe_stack_resources(
        StackName='ScoreCard', LogicalResourceId='ScoresTable')[
            'StackResources'][0]['PhysicalResourceId']

    flags = populate_flags(flags_table_name)

    api_endpoint = 'https://%s.execute-api.%s.amazonaws.com/Main' % (
        api_resource, boto3.Session().region_name)

    teams = [randint(10**35, 10**36) for _ in range(2)]

    print "Setup successful"

    # Assert that a team's default score is 0
    for team in teams:
        resp = requests.get(url=api_endpoint + "/score/" + str(team))
        assert resp.json() == {'Score': 0.0, 'Team': team}

    # Assert that each team cannot claim a non-existent flag
    for team in teams:
        resp = requests.post(
            url=api_endpoint + "/flag",
            json={'team': team,
                  'flag': str(uuid.uuid1())},
            headers={'Content-Type': 'application/json'})
        assert resp.json() == {'ValidFlag': False}

    # Assert that each team can claim a durable simple flag.
    for team in teams:
        resp = requests.post(
            url=api_endpoint + "/flag",
            json={'team': team,
                  'flag': flags[0]['flag']},
            headers={'Content-Type': 'application/json'})
        assert resp.json() == {'ValidFlag': True}
        resp = requests.get(url=api_endpoint + "/score/" + str(team))
        print resp.json()
        assert resp.json() == {'Score': 1.0, 'Team': team}

    print "Tests successful"

    for flag in [f['flag'] for f in flags]:
        for team in teams:
            ddb_client.delete_item(
                TableName=scores_table_name,
                Key={'flag': {
                    'S': flag
                },
                     'team': {
                         'N': str(team)
                     }})
        ddb_client.delete_item(
            TableName=flags_table_name, Key={'flag': {
                'S': flag
            }})

    print "Cleanup successful"


@mock_s3
@mock_dynamodb2
def unit_tests():
    """
    Run all unit tests for Lambda fuction code with the given event body template
    """
    import S3KeyValueStore
    import ScoreCardSubmit
    import ScoreCardTally

    # Perform S3 key value store unit tests.
    S3KeyValueStore.unit_tests(create_s3_bucket())

    for backend in [setup_s3_backend, setup_dynamodb_backend]:
        # Test for both the S3 and DynamoDB key-value store backends
        ScoreCardSubmit.unit_tests(backend())
        ScoreCardTally.unit_tests(backend())


def populate_flags(table_name=None):
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
            'timeout': Decimal(0.5)
        },
        # A recovable-alive flag with an auth key for one team, 'yes' unspecified
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(0.5),
            'auth_key': {
                str(randint(10**35, 10**36)): "2"
            }
        },
        # A simple recovable-alive flag, 'yes' specified to TRUE
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(0.5),
            'yes': True
        },
        # A recovable-alive flag with an auth key for one team, 'yes' specified to TRUE
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(0.5),
            'auth_key': {
                str(randint(10**35, 10**36)): "2"
            },
            'yes': True
        },
        # A simple recovable-dead flag
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(0.5),
            'yes': False
        },
        # A recovable-dead flag with an auth key for one team
        {
            'flag': str(uuid.uuid1()),
            'timeout': Decimal(0.5),
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
        'S3Bucket': s3_bucket,
        'S3Prefix': s3_prefix,
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


def main():
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
    parser.add_argument(
        "--no-unit-tests",
        required=False,
        action='store_true',
        default=False,
        help="Disable running unit tests.")
    pargs = parser.parse_args()

    if not pargs.no_unit_tests:
        unit_tests()

    if pargs.stack_name is not None:
        integration_tests(pargs.stack_name)


if __name__ == "__main__":
    # Configure the default region for boto3/moto.
    import os
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    main()
