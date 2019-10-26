#!/usr/bin/env python3

import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from random import randint

import boto3

ddb = boto3.client("dynamodb")
ses = boto3.client("ses", region_name=os.environ["SES_REGION"])

HMAC_SECRET = os.environ["HMAC_SECRET"].encode("utf-8")
API_URL = os.environ["API_URL"]


def sign_payload(data):
    sig = hmac.new(HMAC_SECRET, data.encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return base64.b32encode(
        json.dumps({
            "data": data,
            "sig": sig
        }).encode("utf-8")).decode("utf-8")


def validate_payload(payload_b32):
    try:
        payload = json.loads(
            base64.b32decode(payload_b32.encode("utf-8")).decode("utf-8"))
        data = payload["data"]
        sig = payload["sig"]
        sig2 = hmac.new(HMAC_SECRET, data.encode("utf-8"),
                        hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, sig2):
            return data
        else:
            return None
    except:
        return None


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

    # If the DDB item doesn't exist, or if it does and it hasn't yet been assigned a team ID
    # then there is no duplicate problem.
    if "Item" in item and "teamId" in item["Item"]:
        return {"result": "failed_duplicate"}

    confirmation_payload = {
        "email": email,
        "username": username,
        "teamId": team_id,
        "registrationTime": time.time()
    }

    confirmation_token = sign_payload(json.dumps(confirmation_payload))

    ses.send_email(Destination={"ToAddresses": [email]},
                   Source="The Big Kahuna CTF <ctf@example.com>",
                   Message={
                       "Subject": {
                           "Data": "The Big Kahuna CTF - Confirm your email"
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
        <h1 id="ctf-registration">CTF Registration - Confirm your email</h1>
<p>You've taken the first step towards registering in the CTF. We just need you to confirm your email, and we'll be on our way.</p>
<p>Click the  <a href="%s">here</a> to confirm your registration.</p>
<p>See you soon!</p>
<p>The Big Kahuna CTF Team</p>
    </body>
    </html>
                               """ %
                               (API_URL + "/register?confirmation_token=" +
                                confirmation_token)
                           }
                       }
                   })
    return {"result": "success"}


def get_confirm(event, context):
    """
    Step 2 of registration where they are confirming an email address.
    """
    confirmation_token = event["confirmation_token"]
    registration_payload = validate_payload(confirmation_token)

    if registration_payload is None:
        return "Unable to validate token."
    else:
        registration_payload = json.loads(registration_payload)

    email = registration_payload["email"]
    team_id = registration_payload["teamId"]
    username = registration_payload["username"]
    registration_time = registration_payload["registrationTime"]

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
                         "N": repr(registration_time)
                     },
                     "confirmationTime": {
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
        if event.get("confirmation_token", "") != "":
            return get_confirm(event, context)
        else:
            return get(event, context)
