#!/usr/bin/env python
"""
Given the configuration of the DynamoDB table describing the flags, and a collection of JSON lines
that describes the POST events as teams claim/renew flags, this script will simulate the score
table changes as the game would have progressed.

This is useful for identifying which flags were claimed when by which teams, and which flags were
never (or universally) claimed.

The simulation is done by using moto to mock the DynamoDB backend, pre-populating the tables with
the input data:

- Using the input Flags table CSV to populate the flags table
- Using the flag config YAML to pre-claim a subset of flags for each team

The input events are then replayed against the unmodified submission and tallying functions in
the order they appear in the input file. This file MUST be sorted temporally for correct and
accurate simulation, and no sorting of the input is done by this script.

This assumes that the headers in the CSV are of the form described by ddb_name() and
ddb_key(), and it also assumes that there is a "timestamp" key in each JSON line input
which contains the timestamp in "%Y-%m-%dT%H:%M:%S.%fZ" format.

Example of running the script:

SQUELCH_XRAY=TRUE python LogReplay.py \\
    --flags-table-csv ScoreCard-FlagsTable-9NZ564375CIS.csv \\
    --post-events-json events.json \\
    --flags-config-yaml flags.yaml

The CSV table input file should have a header row that looks like:

    "flag (S)","weight (N)","auth_key (M)","timeout (N)","yes (BOOL)"

The events file should be in teh JSONLines format (i.e. one JSON object in compact form per line),
and each line should be a dictionary such as the following. Example is shown in expanded and
indented form for readability, but the file should be in the compact representation:

    {
        "timestamp": "2017-05-16T15:07:30.881Z",
        "auth_key": "977c371b5c03ec6c3d022d74c6701eddb509ec87cc9bb3a52be5af7ee975dd",
        "KeyValueBackend": "DynamoDB",
        "ScoresTable": "ScoreCard-ScoresTable-18QQD00AHUX13",
        "FlagsTable": "ScoreCard-FlagsTable-9NZ564375CIS",
        "FlagCacheLifetime": "600",
        "flag": "RootShell-linux2",
        "ScoreCacheLifetime": "30",
        "team": "12"
    }
"""

import os
import json
import time
import argparse
from datetime import datetime

import yaml
import boto3
import moto


class SimContext(object):  # pylint: disable=R0903
    """
    A trivial object that permits setting a simulation time for passing into the lambda
    handler when submitting or tallying. Also disables the caching behaviour for the tallying
    functions.
    """

    def __init__(self):
        # Set an obviously bogus request ID UUID.
        self.aws_request_id = "00000000-0000-0000-0000-000000000000"
        self.disable_cache = True
        self.sim_time = None


def ddb_name(csv_header):
    """
    Given a CSV header column value of the form "<ATTR_NAME> (<ATTR_TYPE>)", parse out the name part
    """
    return csv_header.split(" ")[0]


def ddb_type(csv_header):
    """
    Given a CSV header column value of the form "<ATTR_NAME> (<ATTR_TYPE>)", parse out the type part
    """
    return csv_header.split(" ")[1][1:-1]


def ddb_value(val_type, val):
    """
    Some values require special interpretation, specifically Mapping values need their strings
    JSON-read, and boolean values need to be interpreted from a TRUE/FALSE string.
    """
    if val_type == "M":
        if val == "":
            return dict()
        return json.loads(val)
    elif val_type == "BOOL":
        return val == "TRUE"

    return val


def read_flags_table(fname):
    """
    Read the flags table data in and parse it into items suitable for dynamodb:PutItem operations.

    The structure of the resulting table is determined by parsing the keys in the CSV header row.
    """
    import csv

    ddb_items = [
        dict([(ddb_name(k), {
            ddb_type(k): ddb_value(ddb_type(k), v)
        }) for k, v in row.iteritems() if v != ""])
        for row in csv.DictReader(open(fname, "r"))
    ]

    return ddb_items


def process_events(pargs, teams, flag_keys, total_events):
    # Import the module that will let us do the submission and tally logic
    #
    # Import is done after mocking to ensure that the correct DynamoDB data is picked up on initial
    # module load.
    import ScoreCardSubmit
    import ScoreCardTally

    # Keep track of the last time we tallied the scores (to ensure we're tallying at most as often
    # as the tally interval passed in as an argument)
    last_tally_time = None
    # Keep track of the snapshots as we tally them.
    score_snapshots = list()
    # The shared context object passed in for submission and tallying operations.
    lambda_context = SimContext()

    # Basic housekeeping for ETA calculation.
    events_processed = 0
    event_process_start = time.time()

    for text_line in open(pargs.post_events_json, "r"):
        # Parse the event as a JSON line
        event = json.loads(text_line)

        # Convert the timestamp from the noted format into a unix timestamp of seconds and
        # microseconds since the epoch.
        dt_ts = datetime.strptime(event["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ")
        event["timestamp"] = time.mktime(
            dt_ts.timetuple()) + dt_ts.microsecond / 1000000.0
        lambda_context.sim_time = event["timestamp"]

        # Modify the event to point to our mocked DynamoDB tables, and ensure the use of the
        # DynamoDB backend, regardless of what was in use during the live event.
        event["ScoresTable"] = "ScoresTable"
        event["FlagsTable"] = "FlagsTable"
        event["KeyValueBackend"] = "DynamoDB"

        # Submission returns a value we don't care about, so accept it and pitch it explicitly.
        _ = ScoreCardSubmit.lambda_handler(
            event,
            lambda_context), event["timestamp"], event["team"], event["flag"]

        # If we're overdue for a tally of the scores, then do so for each team we've seen.
        if last_tally_time is None or \
            event["timestamp"] - last_tally_time >= pargs.tally_interval:
            # Tally for each team we know of (based on preprocessing the events), and sort the
            # resulting snapshots so that the highest-scoring team is last.
            snapshot = sorted(
                [
                    ScoreCardTally.lambda_handler(
                        {
                            "BackendType": "DynamoDB",
                            "ScoresTable": "ScoresTable",
                            "FlagsTable": "FlagsTable",
                            "KeyValueBackend": "DynamoDB",
                            "ScoreCacheLifetime": "1",
                            "team": team
                        }, lambda_context) for team in teams
                ],
                key=lambda v: v["score"] if "score" in v else -1000)

            # Prune the snapshot to only those responses that contain a "team" key, and convert the
            # list to a dictionary that keys on the team (with the value being the score snapshot)
            snapshot = dict([(snap["team"], snap) for snap in snapshot
                             if "team" in snap])

            # For every response in the snapshot with a bitmask, convert the bitmask into a dict
            # mapping from the flag names to whether they were claimed.
            for team, snap in snapshot.iteritems():
                if "bitmask" in snap:
                    snap["bitmask"] = dict(zip(flag_keys, snap["bitmask"]))
                    # Since the team is the key, remove the team attribute as it is redundant
                    del snap["team"]

            # Append this snapshot associated with the timestamp it was tallied at to the list of
            # snapshots.
            score_snapshots.append({
                "timestamp": event["timestamp"],
                "score_snapshots": snapshot
            })
            last_tally_time = event["timestamp"]

        # Print out the ETA if we're far enough along.
        events_processed += 1
        if events_processed % 500 == 0:
            print "%d of %d complete. ETA: %f seconds" % (
                events_processed, total_events,
                (total_events - events_processed) *
                (time.time() - event_process_start) / events_processed)

    print time.time() - event_process_start
    with open("score_snapshots.json", "w") as out_fp:
        # Skip the first snapshot, as it is almost guaranteed not to have enough data to be
        # representative. All subsequent snapshots should have enough data though.
        out_fp.write(json.dumps(score_snapshots[1:]))


def __main__():
    parser = argparse.ArgumentParser(
        description="Replay the score change events from a given game.")
    parser.add_argument(
        "--flags-table-csv",
        required=True,
        help=
        "The CSV as dumped by the DynamoDB console's 'Export to CSV' function."
    )
    parser.add_argument(
        "--post-events-json",
        required=True,
        help="The file containing the JSON lines for POST events.")
    parser.add_argument(
        "--tally-interval",
        required=False,
        type=int,
        default=60,
        help=
        "How often, in seconds of simulated time, scores for teams should be tallied."
    )
    parser.add_argument(
        "--default-flags-yaml",
        required=True,
        help=
        """The YAML file that describes the flags, must contain one key, "DurableFlags", which
        has a value that is a list of strings.""")
    pargs = parser.parse_args()

    print "Resetting timezone to UTC"
    # Assume that all input timestamps are in UTC, so set the environment TZ variable, and force
    # the time module to re-detect the correct timesone
    os.environ["TZ"] = "UTC"

    # Note that time.tzset() is not available on Windows Python
    time.tzset()  # pylint: disable=E1101
    print "Timezone set to UTC"

    # Now prop up the mock targets, specifically DynamoDB
    print "Setting up and poopulating mock DynamoDB tables"
    mocks = [moto.mock_dynamodb2()]
    for mock in mocks:
        mock.start()

    ddb = boto3.client("dynamodb")
    ddb.create_table(
        TableName="FlagsTable",
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

    ddb.create_table(
        TableName="ScoresTable",
        AttributeDefinitions=[{
            'AttributeName': 'team',
            'AttributeType': 'N'
        }],
        KeySchema=[{
            'AttributeName': 'team',
            'KeyType': 'HASH'
        }],
        ProvisionedThroughput={
            'ReadCapacityUnits': 1,
            'WriteCapacityUnits': 1
        })

    # Populate the flags table based on the CSV input file
    for item in read_flags_table(pargs.flags_table_csv):
        ddb.put_item(TableName="FlagsTable", Item=item)

    print "Mock DynamoDB resources ready."

    teams = set()
    total_events = 0
    print "Scraping input events for teams present..."
    preprocess_t0 = time.time()
    # List all of the teams by iterating through the input events. Wasteful, but it has to happen.
    for text_line in open(pargs.post_events_json, "r"):
        event = json.loads(text_line)
        total_events += 1
        if event["team"] not in teams:
            try:
                teams.add(str(int(event["team"])))
            except:  # pylint: disable=W0702
                pass
    print "Preprocessing complete in %f seconds" % (
        time.time() - preprocess_t0)

    # Scrape the flag keys from the DDB table, these will be used to translate the bitmasks in the
    # scoring snapshots. Make sure there are no duplicates, and sort them lexicographically.
    flag_keys = sorted(
        list(
            set([
                row["flag"]["S"]
                for row in ddb.scan(TableName="FlagsTable")["Items"]
            ])))

    # Load the flag config, we'll use this to prime the pump, as well as translate the bitmasks
    flags = yaml.load(open(pargs.default_flags_yaml, "r").read())

    # Prime the pump by loading the default flags from the flags YAML file
    for flag in flags["DefaultFlags"]:
        for team in teams:
            ddb.update_item(
                TableName="ScoresTable",
                Key={"team": {
                    "N": team
                }},
                UpdateExpression="set #flag = :last_seen",
                ExpressionAttributeNames={"#flag": flag},
                ExpressionAttributeValues={
                    ":last_seen": {
                        "N": "0"
                    }
                })

    # Actually process the events in the input file.
    process_events(pargs, teams, flag_keys, total_events)


if __name__ == "__main__":
    __main__()
