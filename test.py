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
from decimal import Decimal
import boto3
from moto import mock_s3, mock_dynamodb2


def unit_tests(event_func):
    """
    Run all unit tests for Lambda fuction code with the given event body template
    """
    import ScoreCardSubmit
    import ScoreCardTally
    ScoreCardSubmit.unit_tests(event_func())
    ScoreCardTally.unit_tests(event_func())


def integration_tests(stack_name):
    """
    Run integration tests using HTTP requests against a deployed API.
    """
    pass


def populate_flags(table_name):
    """
    Generate and populate a collection of randomly generated flags, and return
    them.
    """
    from random import randint
    flags_table = boto3.resource('dynamodb').Table(table_name)

    flags = [
        # A simple durable flag
        {
            'flag': str(uuid.uuid1())
        },
        # A durable flag with an auth key for one team
        {
            'flag': str(uuid.uuid1()),
            'auth_key': {
                "1": "1"
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
                "1": "2"
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
                "1": "2"
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
                "1": "3"
            },
            'yes': False
        },
        # A simple durable flag that WILL NOT HAVE A WEIGHT
        {
            'flag': str(uuid.uuid1())
        },
    ]

    for i in range(len(flags)):
        flag = flags[i]
        if i < len(flags) - 1:
            flag['weight'] = i + 1
        else:
            pass
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


@mock_s3
@mock_dynamodb2
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
    pargs = parser.parse_args()

    import S3KeyValueStore

    # Perform S3 key value store unit tests.
    S3KeyValueStore.unit_tests(create_s3_bucket())

    # Test for both the S3 and DynamoDB key-value store backends
    unit_tests(setup_s3_backend)
    unit_tests(setup_dynamodb_backend)

    if pargs.stack_name is not None:
        integration_tests(pargs.stack_name)


if __name__ == "__main__":
    # Configure the default region for boto3/moto.
    import os
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    main()
