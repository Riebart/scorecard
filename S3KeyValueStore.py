"""
Implements a performant key-value store backed on S3 that uses objects stored
in a specific prefix. In practice, this is more performant and scales to a few
hundred transactions per second for workloads without atomicity requirements.
"""
import sys
import json
import cPickle
import hashlib

import boto3
from botocore.exceptions import ClientError


class Table(object):
    """
    Implements the key-value store on top of S3 that provides get_item and put_item
    semantics identical to a DynamoDB Table resource.
    """

    def __init__(self, bucket, prefix, keys):
        """
        Create an S3 key-value table object, by providing the bucket, the prefix,
        and the list of keys that must be present in every object that will be used
        to construct the S3 object key.
        """
        self.bucket = bucket
        self.prefix = prefix.strip('/')
        self.client = boto3.client('s3')
        self.keys = set(keys)

    def get_item(self, **kwargs):
        """
        Provides a method for getting an item with the same semantics as the DynamoDB
        get_item function of a Table resource.
        """
        if 'Key' not in kwargs:
            raise KeyError("'Key' is a non-optional keyword argument")

        item = kwargs['Key']

        if not isinstance(item, dict):
            raise TypeError("'Key' must be a dictionary")

        try:
            item_key = dict([(k, item[k]) for k in self.keys])
        except KeyError as e:
            item_key = dict()

        if set(item_key.keys()) != self.keys:
            raise ValueError("'Key' must have at least the following keys: %s"
                             % str(self.keys))

        object_key = hashlib.sha256(
            json.dumps(item_key, sort_keys=True)).hexdigest()

        try:
            value_object = self.client.get_object(
                Bucket=self.bucket, Key=self.prefix + '/' + object_key)
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'NoSuchKey' or exc.response[
                    'Error']['Code'] == 'AccessDenied':
                value_object = None
            else:
                sys.stderr.write("%s %s\n" %
                                 (self.bucket, self.prefix + '/' + object_key))
                raise exc

        ret = dict()
        if value_object is not None:
            ret['Item'] = cPickle.loads(value_object['Body'].read())
        else:
            pass

        return ret

    def put_item(self, **kwargs):
        """
        Provides a method for getting an item with the same semantics as the DynamoDB
        get_item function of a Table resource.
        """
        if 'Item' not in kwargs:
            raise KeyError("'Item' is a non-optional keyword argument")

        item = kwargs['Item']

        if not isinstance(item, dict):
            raise TypeError("'Item' must be a dictionary")

        try:
            item_key = dict([(k, item[k]) for k in self.keys])
        except KeyError:
            item_key = dict()

        if set(item_key.keys()) != self.keys:
            raise ValueError("'Item' must have at least the following keys: %s"
                             % str(self.keys))

        object_key = hashlib.sha256(
            json.dumps(item_key, sort_keys=True)).hexdigest()

        self.client.put_object(
            Bucket=self.bucket,
            Key=self.prefix + '/' + object_key,
            Body=cPickle.dumps(item))

    # def update_item(self, **kwargs):
    #     for kwarg in ["Key", "UpdateExpression", "ExpressionAttributeValues"]:
    #         if kwarg not in kwargs:
    #             raise KeyError("'%s' is a non-optional keyword argument" %
    #                            kwarg)

    #     key = kwargs['Item']

    #     if not isinstance(item, dict):
    #         raise TypeError("'Item' must be a dictionary")

    #     try:
    #         item_key = dict([(k, item[k]) for k in self.keys])
    #     except KeyError:
    #         item_key = dict()

    #     if set(item_key.keys()) != self.keys:
    #         raise ValueError("'Item' must have at least the following keys: %s"
    #                          % str(self.keys))

    #     object_key = hashlib.sha256(
    #         json.dumps(item_key, sort_keys=True)).hexdigest()

    #     self.client.put_object(
    #         Bucket=self.bucket,
    #         Key=self.prefix + '/' + object_key,
    #         Body=cPickle.dumps(item))

        return dict()
