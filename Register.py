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

# This will be "open" or "closed", which determins how email address that don't exist in the
# registrants table are handled.
REGISTRATION_MODE = os.environ["REGISTRATION_MODE"].lower()


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
        # In closed registration, this may pre-assigned, but we still want to ask for a username
        # so we can let them down and confuse the registrants. :)
        display_name = username
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

    # Registrations are duplicates if the email exists in the DDB table, and the "confirmationTime" column
    # doesn't yet have a timestamp.
    #
    # Obvious, if the item is missing, the get_item() call returns no Item key.
    if "Item" in item:
        # Regardless of registration mode, if there is a confirmed registration for this email,
        # don't permit another.
        if "confirmationTime" in item["Item"]:
            return {"result": "failed_duplicate"}
        else:
            # This is the case where the email exists, in which case the registration mode matters.

            # The default behaviour is open registration.
            # For closed registration, they needn't have a team ID, but they might, so if they do
            # have one from the table already, use that.
            if REGISTRATION_MODE == "closed":
                team_id = int(item["Item"].get("team_id", {"N": team_id})["N"])
                display_name = item["Item"].get("display_name", username)["S"]
            else:  # REGISTRATION_MODE == "open", or any other value.
                pass
    else:
        # In the case of closed registration, every email that tries to register must be part of
        # the table already. If it isn't, it gets an "unauthorized" error response, but to prevent
        # people trying to credential-stuff, we'll just say "unknown". 😺
        if REGISTRATION_MODE == "closed":
            return {"result": "failed_unknown"}

    confirmation_payload = {
        "email": email,
        "username": username,
        "teamId": team_id,
        "registrationTime": time.time(),
        "display_name": display_name
    }

    confirmation_token = sign_payload(json.dumps(confirmation_payload))

    ses.send_email(Destination={"ToAddresses": [email]},
                   Source="CTF Registration <%s>" % os.environ["SES_EMAIL_SOURCE"],
                   Message={
                       "Subject": {
                           "Data": "CTF Registration - Confirm your email"
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
<p>Click <a href="%s">here</a> to confirm your registration.</p>
<p>See you soon!</p>
<p>The CTF Team</p>
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
    display_name = registration_payload["display_name"]
    registration_time = registration_payload["registrationTime"]

    ddb.put_item(TableName=event["RegistrantsTable"],
                 Item={
                     "email": {
                         "S": email
                     },
                     "username": {
                         "S": username
                     },
                     "display_name": {
                         "S": display_name
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
                   Source="CTF Registration <%s>" % os.environ["SES_EMAIL_SOURCE"],
                   Message={
                       "Subject": {
                           "Data": "CTF Registration - Complete!"
                       },
                       "Body": {
                           "Html": {
                               "Charset":
                               "utf-8",
                               "Data":
                               f"""
<!DOCTYPE html>
    <html>

<body>
    <h1>Welcome to the 2019 CCDC event!</h1>
    <p>To get you started, here's some important information and references. <ul>
            <li>Your team name is "{display_name}"", and we have auto-generated a team ID for your team.</li>
            <li>Your team ID is {team_id}</li>
            <li>You'll need this team ID when submitting flags, <i>don't lose this</i>! To submit flags, you will need
                to use the <a href="https://ccdc.zone/scores/submit">flag submission page</a>. </li>
            <li>To see the scoreboard, go to the <a href="https://ccdc.zone/scores/dashboard">score dashboard</a></li>
            <li>This team ID is unique to your team, so don't share it with members of other teams.</li>
        </ul>
    </p>
    <p>Your team has been allocated an environment for today, complete with targets, as well as VMs for you to remote
        into that will contain all of the tools you will need today. You can find your team's starting package <a
            href="https://ccdc.zone/packages/{team_id}.zip">here</a>. <ul>
            <li>This package contains passwords, private keys, hostnames, and other information to get you and your
                teammates started.</li>
            <li>Inside of the zip package, you'll see a few files that start with the word `jumpbox`. These files
                contain the details for access your team's jumpboxes (<a target="_blank"
                    href="https://en.wikipedia.org/wiki/Jump_server">Ref</a>). There are 5 jumpboxes for your team, so
                you and your teammates can decide who gets which jumpbox (they are numbered for your convenience). </li>
            <li><b>THE JUMP BOXES ARE NOT IN SCOPE OF THE EVENT.</b> They are provided as ready-made environments,
                complete with all of the tools you will need during the event. If there are tools you want to use that
                are not installed in the jumpboxes, you are welcome to install them (you have full Administrator
                credentials to these jumpboxes), however <i>you do so at your own risk</i>. <b>IF YOU LOCK YOURSELF OUT
                    OF YOUR JUMPBOX, WE WILL NOT PROVISION A NEW ONE AND YOU WILL NEED TO DEPEND ON YOUR TEAMMATES</b>.
            </li>
            <li>To access your chosen jumpbox, you will need to RDP into it using the hostname and credentials in the
                corresponding file. Microsoft has documentation on how their applications (<a target="_blank"
                    href="https://docs.microsoft.com/en-us/windows-server/remote/remote-desktop-services/clients/remote-desktop-clients">Ref</a>),
                and for those on Linux we recommend using the <a target="_blank" href="https://remmina.org/">Remmina
                    remote desktop client</a>.</li>
        </ul>
    </p>
    <p> This should be enough to get you started, but you will need to read the <a href="https://ccdc.zone/documentation">official
            complete documentation</a> for all of the information you will need to be successful today. </p>
    <h2>Keep your email inbox open or notifications turned on, as we may be sending updates, hints, and notifications to
        you by email throughout the day.</h2>

</html>
</body>
"""
                           }
                       }
                   })

    return {"result": "success"}


def get(event, contest):
    items = ddb.scan(TableName=event["RegistrantsTable"])
    pairs = set([(item["teamId"]["N"], item["display_name"]["S"]) for item in items.get("Items", [])])
    return [{
        "team_id": t[0],
        "team_name": t[1]
    } for t in pairs]


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
