"""
Generate and insert a bunch of random data into an API, and build an associated
constants.js file.
"""

import sys
import json
import uuid
import urllib
import argparse
from random import randint, sample

import boto3
import requests

NOUN_LIST_URL = "https://raw.githubusercontent.com/dariusk/corpora/master/data/words/nouns.json"
ADJECTIVE_LIST_URL = "https://raw.githubusercontent.com/dariusk/corpora/master/data/words/adjs.json"


def err_log(s):
    """
    Log a string to stderr.
    """
    sys.stderr.write(s + "\n")


def word_parts():
    """
    Pull down the word lists and filter for the appropriate length and fix casing
    """
    err_log("Fetching adjective and noun lists...")
    adjectives = json.loads(urllib.urlopen(ADJECTIVE_LIST_URL).read())['adjs']
    nouns = json.loads(urllib.urlopen(NOUN_LIST_URL).read())['nouns']

    # Just pick the ones that have an appropriate length
    err_log("Fetched %d adjectives and %d nouns. Trimming by length." %
            (len(adjectives), len(nouns)))
    adjectives = [a.title() for a in adjectives if 4 <= len(a) <= 6]
    nouns = [n.title() for n in nouns if 4 <= len(n) <= 6]
    err_log("Trimmed to %d adjectives and %d nouns." %
            (len(adjectives), len(nouns)))

    return (adjectives, nouns)


def main():
    """
    Actually do this stuff.
    """

    parser = argparse.ArgumentParser(
        description="""Generate some random content to insert into the DynamoDB
        tables of a given Cloudformation stack.""")
    parser.add_argument(
        "--stack-name",
        required=True,
        help="""Stack name used to determine teh DynamoDB table names for
        inserting the sample data""")
    parser.add_argument(
        "--team-count",
        required=False,
        default=10,
        type=int,
        help="""Number of teams to generate and use. Random team names will be
        assigned to each team based on a list of common words.""")
    parser.add_argument(
        "--flag-count",
        required=False,
        default=10,
        type=int,
        help="""Number of flags generated with random weights. A random selection
        of flags will be selected for each team. All flags are irrecovable durable
        flags.""")
    pargs = parser.parse_args()

    adjectives, nouns = word_parts()

    err_log("Generaging %d teams." % pargs.team_count)
    teams = [(randint(10**36, 10**37), " ".join(
        (sample(adjectives, 1)[0], sample(nouns, 1)[0])))
             for _ in xrange(pargs.team_count)]
    print json.dumps(teams)

    err_log("Generaging %d flags." % pargs.flag_count)
    flags = [(str(uuid.uuid1()), randint(10, 50))
             for _ in xrange(pargs.flag_count)]
    print json.dumps(flags)

    cfn_client = boto3.client("cloudformation")
    api_id = cfn_client.describe_stack_resources(
        StackName=pargs.stack_name,
        LogicalResourceId="API")["StackResources"][0]["PhysicalResourceId"]
    api_endpoint = "https://%s.execute-api.%s.amazonaws.com/Main" % (
        api_id, boto3.Session().region_name)
    flag_table_name = cfn_client.describe_stack_resources(
        StackName=pargs.stack_name, LogicalResourceId="FlagsTable")[
            "StackResources"][0]["PhysicalResourceId"]

    err_log("API URL: %s" % api_endpoint)
    err_log("Flag table name: %s" % flag_table_name)

    ddb_client = boto3.client("dynamodb")
    err_log("Creating flags in the DynamoDB table...")
    for flag in flags:
        ddb_client.put_item(
            TableName=flag_table_name,
            Item={"flag": {
                "S": flag[0]
            },
                  "weight": {
                      "N": repr(flag[1])
                  }})

    print "Claiming flags for teams and confiming scores"
    for team in teams:
        if len(flags) > 1:
            claimed_flags = sample(flags, randint(0, len(flags)))
        else:
            claimed_flags = flags

        score = 0
        for flag in claimed_flags:
            score += flag[1]
            resp = requests.post(
                url=api_endpoint + "/flag",
                json={"team": str(team[0]),
                      "flag": flag[0]},
                headers={'Content-Type': 'application/json'})
            assert resp.json() == {'ValidFlag': True}
        resp = requests.get(url=api_endpoint + "/score/" + str(team[0]))
        assert resp.json()["Score"] == score
        print json.dumps({"Team": str(team[0]), "Score": score})

    with open("constants.js.sample_%s" % pargs.stack_name, "w") as fp:
        fp.write("var API_ENDPOINT = '%s';\n" % api_endpoint)
        fp.write("var TEAMS = %s;\n" % json.dumps([{
            "team_id": str(team[0]),
            "team_name": team[1]
        } for team in teams]))


if __name__ == "__main__":
    main()
