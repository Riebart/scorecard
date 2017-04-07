#!/usr/bin/env python
"""
Unit tests for the submission logic
"""
import copy
import time
import uuid
import unittest
from random import randint
from decimal import Decimal

import boto3
import moto

import ScoreCardSubmit
import ScoreCardTally


class MotoTest(unittest.TestCase):
    """
    Test the S3 Key-Value backend for correctness using moto for local mocking
    """

    @classmethod
    def setUpClass(cls):
        """
        If there is no AWS region set from the environment provider, then configure
        the default region as US-EAsT-1
        """
        if boto3.Session().region_name is None:
            import os
            os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

    def populate_flags(self, table_name=None, timeout=0.5):
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

    def setup_s3_backend(self):
        """
        Create the AWS resources for an S3 key-value backend, and return the
        event body template
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
        flags = self.populate_flags(flags_table)

        return {
            'KeyValueS3Bucket': s3_bucket,
            'KeyValueS3Prefix': s3_prefix,
            'FlagsTable': flags_table,
            'KeyValueBackend': 'S3',
            'Flags': flags
        }

    def setup_dynamodb_backend(self):
        """
        Create the AWS resources for a DynamoDB key-value backend, and return
        the event body template
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
        flags = self.populate_flags(flags_table)

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

    def setUp(self):
        """
        Create up a new moto context and S3 bucket for each test to ensure no
        clobbering occurs.
        """
        reload(ScoreCardSubmit)
        reload(ScoreCardTally)
        self.mocks = [moto.mock_s3(), moto.mock_dynamodb2()]
        for mock in self.mocks:
            mock.start()
        self.ddb_event = self.setup_dynamodb_backend()
        self.s3_event = self.setup_s3_backend()

    def tearDown(self):
        """
        Dispose of the S3 client and table after each test.
        """
        for mock in self.mocks:
            mock.stop()
        self.mocks = None

    def test_submit_backend_swap(self):
        """
        Cofirm that the submission backend switches when different events are provided.
        """
        self.ddb_event['team'] = str(10)
        self.ddb_event['flag'] = ''
        ScoreCardSubmit.lambda_handler(self.ddb_event, None)
        assert ScoreCardSubmit.BACKEND_TYPE == "DynamoDB"
        assert not isinstance(ScoreCardSubmit.SCORES_TABLE,
                              type(ScoreCardSubmit.S3Table))
        self.s3_event['team'] = str(10)
        self.s3_event['flag'] = ''
        ScoreCardSubmit.lambda_handler(self.s3_event, None)
        assert ScoreCardSubmit.BACKEND_TYPE == "S3"
        assert isinstance(ScoreCardSubmit.SCORES_TABLE,
                          ScoreCardSubmit.S3Table)
        ScoreCardSubmit.lambda_handler(self.ddb_event, None)
        assert ScoreCardSubmit.BACKEND_TYPE == "DynamoDB"
        assert not isinstance(ScoreCardSubmit.SCORES_TABLE,
                              type(ScoreCardSubmit.S3Table))

    def test_missing_arguments(self):
        """
        Assert that lack of 'team' AND 'flag' results in a ClientError with two errors
        """
        for event in [self.ddb_event, self.s3_event]:
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert 'ClientError' in res
            assert len(res['ClientError']) == 2

    def test_missing_argument(self):
        """
        Assert that lack of 'team' OR 'flag' results in a ClientError
        """
        for event in [self.ddb_event, self.s3_event]:
            event['team'] = str(10)
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert 'ClientError' in res
            assert len(res['ClientError']) == 1
            del event['team']
            event['flag'] = ''
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert 'ClientError' in res
            assert len(res['ClientError']) == 1

    def test_nonintegral_team(self):
        """
        Assert that the team must be integral (or parsable as integral)
        """
        for event in [self.ddb_event, self.s3_event]:
            event['team'] = 'abcde'
            event['flag'] = ''
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert 'ClientError' in res
            assert len(res['ClientError']) == 1

    def test_integral_team(self):
        """
        Assert that the team can be integral
        """
        for event in [self.ddb_event, self.s3_event]:
            event['team'] = str(10)
            event['flag'] = ''
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert 'ClientError' not in res

    def test_integral_string_team(self):
        """
        Assert that the team can be a parsable integer
        """
        for event in [self.ddb_event, self.s3_event]:
            event['team'] = '10'
            event['flag'] = ''
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert 'ClientError' not in res

    def test_invalid_flag(self):
        """
        Attempt to claim a nonexistent flag
        """
        for event in [self.ddb_event, self.s3_event]:
            event['team'] = str(10)
            event['flag'] = ""
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert res == {'ValidFlag': False}

    def test_durable_flag(self):
        """
        A simple durable flag
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[0]['flag']
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert res == {'ValidFlag': True}
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 1.0}

    def test_score_cache_lifetime_precision(self):
        """
        Ensure that the score caching is timely and tight.
        """
        for event in [self.ddb_event, self.s3_event]:
            for cache_lifetime in [0, 1, 2, 3, 4, 5]:
                reload(ScoreCardSubmit)
                reload(ScoreCardTally)
                flags = event['Flags']
                event['team'] = str(randint(10**35, 10**36))
                event['flag'] = flags[0]['flag']
                event['ScoreCacheLifetime'] = cache_lifetime
                t0 = time.time()
                res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
                assert res == {'Team': event['team'], 'Score': 0.0}
                res = ScoreCardSubmit.lambda_handler(
                    copy.deepcopy(event), None)
                assert res == {'ValidFlag': True}
                while True:
                    time.sleep(0.05)
                    res = ScoreCardTally.lambda_handler(
                        copy.deepcopy(event), None)
                    if res['Score'] != 0:
                        break
                cache_delay = time.time() - t0
                assert cache_delay > cache_lifetime
                # assert (cache_delay - cache_lifetime) < 1.0

    def test_flag_cache_lifetime_precision(self):
        """
        Ensure that the flag caching is timely and tight
        """
        ddb_resource = boto3.resource('dynamodb')
        for event in [self.ddb_event, self.s3_event]:
            tbl = ddb_resource.Table(event['FlagsTable'])
            for cache_lifetime in [0, 1, 2, 3, 4, 5]:
                reload(ScoreCardSubmit)
                reload(ScoreCardTally)
                flag = str(uuid.uuid1())

                event['team'] = str(randint(10**35, 10**36))
                event['flag'] = flag
                event['FlagCacheLifetime'] = cache_lifetime
                event['ScoreCacheLifetime'] = 0

                # Submit the not-yet-existent flag, to put the flags into the submission cache
                # Tally the score to put the flags into the tally cache
                # Put the flag into the Flags table.
                # Spin, submitting and tallying until the flag registers, and the score registers
                t0 = time.time()
                res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
                assert res == {'Team': event['team'], 'Score': 0.0}
                res = ScoreCardSubmit.lambda_handler(
                    copy.deepcopy(event), None)
                assert res == {'ValidFlag': False}

                tbl.put_item(Item={'flag': flag, 'weight': Decimal(1)})

                while True:
                    time.sleep(0.05)
                    res = ScoreCardSubmit.lambda_handler(
                        copy.deepcopy(event), None)
                    if res['ValidFlag']:
                        break

                res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
                assert res == {'Team': event['team'], 'Score': 1.0}

                cache_delay = time.time() - t0
                assert cache_delay > cache_lifetime
                # assert (cache_delay - cache_lifetime) < 1.0

    def test_auth_flag1(self):
        """
        Confirm that the wrong team cannot claim an authorized flag without a key
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[1]['flag']
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert res == {'ValidFlag': False}

    def test_auth_flag2(self):
        """
        Confirm that the wrong team cannot claim an authorized flag with the wrong key
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[1]['flag']
            event['auth_key'] = str(uuid.uuid1())
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert res == {'ValidFlag': False}

    def test_auth_flag3(self):
        """
        Confirm that the wrong team cannot claim an authorized flag with the right key
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[1]['flag']
            event['auth_key'] = flags[1]['auth_key'][flags[1]['auth_key']
                                                     .keys()[0]]
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert res == {'ValidFlag': False}

    def test_auth_flag4(self):
        """
        Confirm that the right team and claim the flag with the right key
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(flags[1]['auth_key'].keys()[0])
            event['flag'] = flags[1]['flag']
            event['auth_key'] = flags[1]['auth_key'][event['team']]
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert res == {'ValidFlag': True}

    def test_auth_flag5(self):
        """
        Confirm that the right team cannot claim the flag with the wrong key
        """
        for event in [self.ddb_event, self.s3_event]:
            # A durable flag with an auth key for one team as the right team with the wrong key
            flags = event['Flags']
            event['team'] = str(flags[1]['auth_key'].keys()[0])
            event['flag'] = flags[1]['flag']
            event['auth_key'] = str(uuid.uuid1())
            res = ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            assert res == {'ValidFlag': False}

    def test_tally_backend_swap(self):
        """
        Cofirm that the submission backend switches when different events are provided.
        """
        self.ddb_event['team'] = str(10)
        self.ddb_event['flag'] = ''
        ScoreCardTally.lambda_handler(self.ddb_event, None)
        assert ScoreCardTally.BACKEND_TYPE == "DynamoDB"
        assert not isinstance(ScoreCardTally.SCORES_TABLE,
                              type(ScoreCardTally.S3Table))
        self.s3_event['team'] = str(10)
        self.s3_event['flag'] = ''
        ScoreCardTally.lambda_handler(self.s3_event, None)
        assert ScoreCardTally.BACKEND_TYPE == "S3"
        assert isinstance(ScoreCardTally.SCORES_TABLE, ScoreCardTally.S3Table)
        ScoreCardTally.lambda_handler(self.ddb_event, None)
        assert ScoreCardTally.BACKEND_TYPE == "DynamoDB"
        assert not isinstance(ScoreCardTally.SCORES_TABLE,
                              type(ScoreCardTally.S3Table))

    def test_tally_input1(self):
        """
        Assert that lack of 'team' results in a ClientError
        """
        for event in [self.ddb_event, self.s3_event]:
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert 'ClientError' in res
            assert len(res['ClientError']) == 1

    def test_tally_input2(self):
        """
        Assert that the team must be integral (or parsable as integral)
        """
        for event in [self.ddb_event, self.s3_event]:
            event['team'] = 'abcde'
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert 'ClientError' in res
            assert len(res['ClientError']) == 1

    def test_tally_default_score(self):
        """
        Confirm that the team score without flags claimed is 0
        """
        for event in [self.ddb_event, self.s3_event]:
            event['team'] = str(randint(10**35, 10**36))
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 0.0}

    def test_tally_simple_cached(self):
        """
        Claim a simple durable flag, and fetch the scorefrom cache
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[0]['flag']
            event['ScoreCacheLifetime'] = 10
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 0.0}
            ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 0.0}

            # Override the team score cache to get real-time updates on scores
            event['ScoreCacheLifetime'] = 0

            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 1.0}

    def test_tally_revocable_alive1(self):
        """
        A simple recovable-alive flag, 'yes' unspecified
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[2]['flag']
            event['ScoreCacheLifetime'] = 0
            ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 3.0}
            time.sleep(1.5 * float(flags[2]['timeout']))
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 0.0}

    def test_tally_revocable_alive2(self):
        """
        A simple recovable-alive flag, 'yes' set to TRUE
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[4]['flag']
            event['ScoreCacheLifetime'] = 0
            ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 5.0}
            time.sleep(1.5 * float(flags[4]['timeout']))
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 0.0}

    def test_tally_revocable_dead1(self):
        """
        A simple recovable-dead flag
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[6]['flag']
            event['ScoreCacheLifetime'] = 0
            ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 0.0}
            time.sleep(1.5 * float(flags[6]['timeout']))
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 7.0}

    def test_unweighted_flag(self):
        """
        A simple durable flag without a weight
        """
        for event in [self.ddb_event, self.s3_event]:
            flags = event['Flags']
            event['team'] = str(randint(10**35, 10**36))
            event['flag'] = flags[-1]['flag']
            event['ScoreCacheLifetime'] = 0
            ScoreCardSubmit.lambda_handler(copy.deepcopy(event), None)
            res = ScoreCardTally.lambda_handler(copy.deepcopy(event), None)
            assert res == {'Team': event['team'], 'Score': 0.0}


if __name__ == "__main__":
    unittest.main()
