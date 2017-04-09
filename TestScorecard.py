#!/usr/bin/env python
"""
Unit tests for the submission logic
"""

import os
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


class ScoreCardTest(unittest.TestCase):
    """
    Setup and teardown shared by all ScoreCard tests.
    """

    @classmethod
    def setUpClass(cls):
        """
        If there is no AWS region set from the environment provider, then configure
        the default region as US-EAsT-1
        """
        os.environ["MOCK_XRAY"] = "TRUE"
        if boto3.Session().region_name is None:
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


class BackendTest(ScoreCardTest):
    """
    Test the S3 Key-Value backend for correctness using moto for local mocking
    """

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


class XraySamplingTests(ScoreCardTest):
    """
    Test that the scorecard functions properly obey Xray sampling rates.
    """

    @staticmethod
    def __binomial_list(flips, heads):
        return [
            Decimal(i) / j
            for i, j in zip(range(1, heads + 1), range(1, heads + 1))
        ] + [
            Decimal(i) / j
            for i, j in zip(
                range(heads + 1, flips + 1), range(1, flips - heads + 2))
        ]

    @staticmethod
    def __coin_toss(flips, heads, p_head=0.5):
        # p^m (1-p)^(n-m) Binomial[n,m]
        binomial = XraySamplingTests.__binomial_list(flips, heads)
        probabilities = [Decimal(p_head) for _ in xrange(heads)] + [
            Decimal(1 - p_head) for _ in xrange(flips - heads)
        ]
        return reduce(lambda a, b: a * b,
                      [a * b for a, b in zip(binomial, probabilities)])

    @staticmethod
    def __coin_toss_range(flips, min_heads, max_heads, p_head):
        if min_heads < 0 or max_heads > flips:
            return float('nan')
        return sum([
            XraySamplingTests.__coin_toss(flips, heads, p_head)
            for heads in xrange(min_heads, max_heads + 1)
        ])

    @staticmethod
    def __coin_toss_counts(desired_rate, min_rate, max_rate, p_cutoff=0.999):
        dflips = 1024
        flips = dflips
        while True:
            prob = XraySamplingTests.__coin_toss_range(flips,
                                                       int(min_rate * flips),
                                                       int(max_rate * flips),
                                                       desired_rate)
            if prob < p_cutoff:
                flips += dflips
            elif dflips > 1:
                flips -= dflips
                dflips /= 2
                flips += dflips
            else:
                break
        return flips

    def test_binomial(self):
        """
        Test that the binomial calculation works for Binomial(100, n)
        """
        binomials = [
            reduce(lambda a, b: a * b, self.__binomial_list(100, n))
            for n in xrange(0, 101)]
        expected = [
            1, 100, 4950, 161700, 3921225, 75287520, 1192052400, 16007560800,
            186087894300, 1902231808400, 17310309456440, 141629804643600, 1050421051106700,
            7110542499799200, 44186942677323600, 253338471349988640, 1345860629046814650,
            6650134872937201800, 30664510802988208300, 132341572939212267400,
            535983370403809682970, 2041841411062132125600, 7332066885177656269200,
            24865270306254660391200, 79776075565900368755100, 242519269720337121015504,
            699574816500972464467800, 1917353200780443050763600, 4998813702034726525205100,
            12410847811948286545336800, 29372339821610944823963760, 66324638306863423796047200,
            143012501349174257560226775, 294692427022540894366527900, 580717429720889409486981450,
            1095067153187962886461165020, 1977204582144932989443770175,
            3420029547493938143902737600, 5670048986634686922786117600,
            9013924030034630492634340800, 13746234145802811501267369720,
            20116440213369968050635175200, 28258808871162574166368460400,
            38116532895986727945334202400, 49378235797073715747364762200,
            61448471214136179596720592960, 73470998190814997343905056800,
            84413487283064039501507937600, 93206558875049876949581681100,
            98913082887808032681188722800, 100891344545564193334812497256,
            98913082887808032681188722800, 93206558875049876949581681100,
            84413487283064039501507937600, 73470998190814997343905056800,
            61448471214136179596720592960, 49378235797073715747364762200,
            38116532895986727945334202400, 28258808871162574166368460400,
            20116440213369968050635175200, 13746234145802811501267369720,
            9013924030034630492634340800, 5670048986634686922786117600,
            3420029547493938143902737600, 1977204582144932989443770175,
            1095067153187962886461165020, 580717429720889409486981450,
            294692427022540894366527900, 143012501349174257560226775,
            66324638306863423796047200, 29372339821610944823963760, 12410847811948286545336800,
            4998813702034726525205100, 1917353200780443050763600, 699574816500972464467800,
            242519269720337121015504, 79776075565900368755100, 24865270306254660391200,
            7332066885177656269200, 2041841411062132125600, 535983370403809682970,
            132341572939212267400, 30664510802988208300, 6650134872937201800,
            1345860629046814650, 253338471349988640, 44186942677323600, 7110542499799200,
            1050421051106700, 141629804643600, 17310309456440, 1902231808400, 186087894300,
            16007560800, 1192052400, 75287520, 3921225, 161700, 4950, 100, 1]
        max_rel_error = max([abs(float(a - b)) / b for a, b in zip(binomials, expected)])
        assert max_rel_error < 10**-15

    def test_coin_toss(self):
        """
        Test that the coin-toss simulation is correct for a few select values
        """
        for i in range(1, 101):
            assert self.__coin_toss(100, i, 0.0) == 0.0
        assert self.__coin_toss(100, 0, 0.0) == 1.0
        for i in range(0, 100):
            assert self.__coin_toss(100, i, 1.0) == 0.0
        assert self.__coin_toss(100, 100, 1.0) == 1.0
        assert abs(
            self.__coin_toss(300, 200, 0.75) -
            Decimal(0.00026617318083780561928702841873999185536747448066193)) < 10**-15

        # Now for a collection of tests with less precision
        test_cases = [
            [27, 3, 0.326783, 0.00766693], [19, 10, 0.50931, 0.178918],
            [23, 15, 0.564874, 0.119859], [27, 16, 0.168794, 7.4084 * 10**-7],
            [24, 9, 0.72225, 0.000315816], [13, 11, 0.417621, 0.00178283],
            [8, 8, 0.478113, 0.0027305], [25, 22, 0.98442, 0.00615759],
            [23, 2, 0.123151, 0.242895], [29, 27, 0.957073, 0.228824]]
        for case in test_cases:
            assert float(abs(self.__coin_toss(*case[:3]) - Decimal(case[3]))) < 10**-5

    # def test_xray_sampling_rate(self):
    #     """
    #     Ensure that the rate at which requests are sampled is correct.
    #     """
    #     events_per_round = 100
    #     os.environ["DEBUG"] = "TRUE"
    #     for event in [self.ddb_event, self.s3_event]:
    #         for xsp in [0.0, 0.01, 0.1, 0.5, 1.0]:
    #             n_mocked = 0
    #             os.environ["XraySampleProbability"] = str(xsp)
    #             for _ in xrange(
    #                     events_per_round):  # Tally the scores of N teams.
    #                 event["team"] = str(randint(10**35, 10**36))
    #                 res = ScoreCardTally.lambda_handler(
    #                     copy.deepcopy(event), None)
    #                 if res["Debug"]["MockedXray"]:
    #                     n_mocked += 1
    #             if xsp == 0.0:
    #                 assert n_mocked == 0
    #             elif xsp == 1.0:
    #                 assert n_mocked == events_per_round
    #             else:
    #                 # f=Function[{n,m,p},
    #                 # p^m (1-p)^(n-m) Binomial[n,m]
    #                 # ];
    #                 # g=Function[{n,m,k,p},
    #                 # Table[
    #                 # f[n,m+i,p],{i,-k,k}
    #                 # ]//N
    #                 # ];
    #                 assert 0.9
    #             print n_mocked, events_per_round

    #     del os.environ["DEBUG"]
    #     del os.environ["XraySampleProbability"]


if __name__ == "__main__":
    unittest.main()
