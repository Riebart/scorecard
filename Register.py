#!/usr/bin/env python3

import os
import json
import re
import time
from random import randint

import boto3

ddb = boto3.client("dynamodb")
ses = boto3.client("ses", region_name=os.environ["SES_REGION"])


def post(event, contest):
    email = None
    username = None

    try:
        email = event["email"]
    except:
        return {"result": "failure"}

    try:
        username = event["username"]
    except:
        return {"result": "failure"}

    if email is None or username is None:
        return {"result": "failure"}

    try:
        if re.match("^[^@]+@[^@]+\\.[^@]+$", email) is None:
            return {"result": "failure_parse"}

        if re.match("^[a-z0-9A-Z]{4,64}$", username) is None:
            return {"result": "failure_parse"}
    except:
        return {"result": "failure_parse"}

    team_id = randint(2**63, 2**64)

    # Check to see if the item exists in the table.
    item = ddb.get_item(TableName=event["RegistrantsTable"],
                        Key={"email": {
                            "S": email
                        }})
    if "Item" in item:
        return {"result": "failed_duplicate"}

    ddb.put_item(TableName=event["RegistrantsTable"],
                 Item={
                     "email": {
                         "S": email
                     },
                     "username": {
                         "S": username
                     },
                     "teamId": {
                         "N": str(team_id)
                     },
                     "registrationTime": {
                         "N": repr(time.time())
                     }
                 })

    ses.send_email(Destination={"ToAddresses": [email]},
                   Source="The Big Kahuna CTF <ctf@example.com>",
                   Message={
                       "Subject": {
                           "Data": "The Big Kahuna CTF Registration"
                       },
                       "Body": {
                           "Html": {
                               "Charset":
                               "utf-8",
                               "Data":
                               """
<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>CTF Registration</title>

        <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/Microsoft/vscode/extensions/markdown-language-features/media/markdown.css">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/Microsoft/vscode/extensions/markdown-language-features/media/highlight.css">

        <style>
.task-list-item { list-style-type: none; } .task-list-item-checkbox { margin-left: -20px; vertical-align: middle; }
</style>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe WPC', 'Segoe UI', 'Ubuntu', 'Droid Sans', sans-serif;
                font-size: 14px;
                line-height: 1.6;
            }
        </style>


    </head>
    <body class="vscode-light">
        <h1 id="ctf-registration">CTF Registration</h1>
<!-- You can use Markdown to craft your welcome emails, and then render it to HTML and use it as the body in `Register.py` -->
<p>Congratulations %s! You've signed up for our CTF, The Big Kahuna CTF!</p>
<ul>
<li>When submitting your flags, your team ID is %d and you will show up as &quot;%s&quot; on the scores list</li>
<li>To submit flags, head over to <a href="https://ctf.example.com/submit">https://ctf.example.com/submit</a></li>
<li>To view the current standings, head over to <a href="https://ctf.example.com/scores">https://ctf.example.com/scores</a></li>
</ul>
<p>Enjoy and godspeed!</p>
<p>Best wishes,
The Big Kahuna CTF Team</p>

    </body>
    </html>
""" % (username, team_id, username)
                           }
                       }
                   })

    return {"result": "success"}


def get(event, contest):
    items = ddb.scan(TableName=event["RegistrantsTable"])
    return [{
        "team_id": item["teamId"]["N"],
        "team_name": item["username"]["S"]
    } for item in items.get("Items", [])]


def lambda_handler(event, context):
    print(json.dumps(event))

    # This function is called with two methods, GET and POST.
    # - POST creates a new registration
    # - GET scans the DynamoDB table and returns the participant list in a format usable by the dashboard.
    if event["Method"] == "POST":
        return post(event, context)
    elif event["Method"] == "GET":
        return get(event, context)
