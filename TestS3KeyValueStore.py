#!/usr/bin/env python
"""
Unit tests for the S3 Key-Value Store backend.
"""
import uuid
import unittest

import boto3
import moto

import S3KeyValueStore


class MotoTest(unittest.TestCase):
    """
    Test the S3 Key-Value backend for correctness using moto for local mocking
    """

    def setUp(self):
        """
        Create up a new moto context and S3 bucket for each test to ensure no
        clobbering occurs.
        """
        self.mock = moto.mock_s3()
        self.mock.start()
        self.s3_client = boto3.client('s3')
        self.bucket = str(uuid.uuid1())
        self.s3_client.create_bucket(Bucket=self.bucket)
        self.tbl = S3KeyValueStore.Table(self.bucket, "Prefix-1",
                                         ['hkey', 'skey'])

    def tearDown(self):
        """
        Dispose of the S3 client and table after each test.
        """
        self.mock.stop()
        self.mock = None
        self.s3_client = None
        self.bucket = None

    def test_nonexistent_bucket(self):
        """
        Confirm that an uncaught (that is, not a 404/NoSuchKey) exception is reraised.
        """
        self.tbl = S3KeyValueStore.Table(
            str(uuid.uuid1()), "Prefix-1", ['hkey', 'skey'])
        exc = None
        try:
            self.tbl.get_item(Key={'hkey': '', 'skey': ''})
        except Exception as exc:
            pass
        assert exc is not None

    def test_successful_put(self):
        """
        Confirm that an object can be put to the table without excepting
        """
        item = {
            'hkey': '12345',
            'skey': 2134,
            'val1': {
                'abc': 123
            },
            'val2': ['abc', 123]
        }
        assert self.tbl.put_item(Item=item) == dict()

    def test_incomplete_key(self):
        """
        Attempt to put an item with an incomplete key
        """
        for k in [dict(), {'hkey': 'abc'}, {'skey': 123}]:
            exc = None
            try:
                self.tbl.put_item(Item=k)
            except ValueError as exc:
                pass
            assert exc is not None

    def test_nondictionary_item(self):
        """
        Attempt to put an item with a non-dictionary key
        """
        exc = None
        try:
            self.tbl.put_item(Item=[])
        except TypeError as exc:
            pass
        assert exc is not None

    def test_missing_item(self):
        """
        Attempt to put an item with a missing item kwarg
        """
        exc = None
        try:
            self.tbl.put_item()
        except KeyError as exc:
            pass
        assert exc is not None

    def test_successful_retrieval(self):
        """
        Confirm that an item can be retrieved from the table correctly
        """
        item = {
            'hkey': '12345',
            'skey': 2134,
            'val1': {
                'abc': 123
            },
            'val2': ['abc', 123]
        }
        self.tbl.put_item(Item=item)
        assert self.tbl.get_item(Key=item)['Item'] == item

    def test_nonexistent_key(self):
        """
        Confirm that retrieving a non-existent item results in an empty dict
        """
        assert self.tbl.get_item(Key={'hkey': '', 'skey': ''}) == dict()

    def test_incorrect_key_schema(self):
        """
        Confirm that trying to retrieve an item with an incorrect key schema raises
        a ValueError
        """
        for k in [dict(), {'hkey': 'abc'}, {'skey': 123}]:
            exc = None
            try:
                self.tbl.get_item(Key=k)
            except ValueError as exc:
                pass
            assert exc is not None

    def test_nondicitonary_key(self):
        """
        Attempt to put an item with a non-dictionary key
        """
        exc = None
        try:
            self.tbl.get_item(Key=[])
        except TypeError as exc:
            pass
        assert exc is not None

    def test_missing_key(self):
        """
        Attempt to put an item with a missing item kwarg
        """
        exc = None
        try:
            self.tbl.get_item()
        except KeyError as exc:
            pass
        assert exc is not None


if __name__ == "__main__":
    unittest.main()
