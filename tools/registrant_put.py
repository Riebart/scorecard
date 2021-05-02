#!/usr/bin/env python3

# Usage:

# python3 registrant_put.py \
#       ~/Downloads/Registration responses.csv \
#       "MyScoredProject-Scorecard-RegistrantsTable-CZP7ZHU"

import csv
import sys
import boto3
from botocore.exceptions import ClientError

ddb = boto3.client("dynamodb")

with open(sys.argv[1]) as fp:
    for row in csv.reader(fp):
        if row[0].strip() == "":
            continue
        team_name = row[0]
        team_id = row[1]
        team_members = [i for i in row[2:] if i != ""]
        for member_email in team_members:
            item = {
                "email": {
                    "S": member_email
                },
                "display_name": {
                    "S": team_name
                },
                "teamId": {
                    "N": str(team_id)
                }
            }
            print(item)
            try:
                resp = ddb.put_item(
                    TableName=sys.argv[2],
                    Item=item,
                    ConditionExpression="attribute_not_exists(email)")
            except ClientError as e:
                if e.response['Error'][
                        'Code'] != 'ConditionalCheckFailedException':
                    raise e
                else:
                    resp = None
                    print("Value already exists, skipping")
            print(resp)
