#!/usr/bin/env python
"""
Python daemon script to watch the tally endpoint (polling asynchronously for all teams
at a frequency specified), and broadcasting updates to all clients on a websocket.
"""

from __future__ import print_function

import argparse
import json
import os
import os.path
import signal
import ssl
import sys
import threading
import time
from copy import deepcopy
from hashlib import sha256

from SimpleWebSocketServer import (SimpleSSLWebSocketServer,
                                   SimpleWebSocketServer, WebSocket)

import ScoreCardTally

WEBSOCKET_SERVER = None
WEBSOCKET_CLIENTS = list()
TEAM_SCORES = dict()
TEAM_CHECKER_THREADS = None


def json_int_list(str_val):
    l = json.loads(str_val)
    try:
        assert isinstance(l, list)
    except:
        raise Exception("\"%s\" is not a list." % str_val)
    for i in l:
        try:
            assert isinstance(i, int)
        except:
            raise Exception("\"%s\" is not an integer." % str(i))
    return l


class ScoreUpdateWebsocket(WebSocket):
    def handleMessage(self):
        pass

    def handleConnected(self):
        print("New client: %s" % str(self), file=sys.stderr)
        WEBSOCKET_CLIENTS.append(self)
        self.sendMessage(
            json.dumps({
                "timestamp": time.time(),
                "contentType": "score_update",
                "content": {
                    sha256(str(k)).hexdigest(): v
                    for k, v in TEAM_SCORES.iteritems()
                }
            }))

    def handleClose(self):
        print("Disconnected client: %s" % str(self), file=sys.stderr)
        WEBSOCKET_CLIENTS.remove(self)


class ScoreCheckThread(threading.Thread):
    def __init__(self, scores_table, flags_table, team_id, delay):
        threading.Thread.__init__(self)
        self.scores_table = scores_table
        self.flags_table = flags_table
        self.team_id = team_id
        self.delay = delay
        self.running = True

    def run(self):
        while self.running:
            # print("Checking score for %d in thread" % self.team_id,
            #       file=sys.stderr)
            get_team_score(self.scores_table, self.flags_table, [self.team_id])
            time.sleep(self.delay)


def send_updates(team_id):
    t0 = time.time()
    for sock_client in WEBSOCKET_CLIENTS:
        sock_client.sendMessage(
            json.dumps({
                "timestamp": time.time(),
                "contentType": "score_update",
                "content": {
                    sha256(str(team_id)).hexdigest(): TEAM_SCORES[team_id]
                }
            }))
    dt = time.time() - t0
    print("Spent %s seconds sending websocket updates" % repr(dt),
          file=sys.stderr)


def get_team_score(scores_table, flags_table, teams):
    event_base = {
        "ScoresTable": scores_table,
        "FlagsTable": flags_table,
        "KeyValueBackend": "DynamoDB",
        "ScoreCacheLifetime": 0,
        "FlagCacheLifetime": 30
    }

    for team in teams:
        event = deepcopy(event_base)
        event["team"] = team
        try:
            resp = ScoreCardTally.lambda_handler(event, None)
        except Exception as e:
            print("Exception encountered when getting scores for team %s: %s" %
                  (str(team), str([str(e), repr(e)])),
                  file=sys.stderr)
            continue

        if team in TEAM_SCORES:
            # If we have a score for this team already, then check to see if it has changed
            # TODO This is comparing floats, so.... But in our case, they're almost always ints
            if TEAM_SCORES[team]["score"] != resp["score"]:
                print("Updating scores for team %s" % str(team),
                      file=sys.stderr)
                TEAM_SCORES[team]["last_update"] = time.time()
                TEAM_SCORES[team]["score"] = resp["score"]
                send_updates(team)
        else:
            print("First score for team %s fetched" % str(team),
                  file=sys.stderr)
            TEAM_SCORES[team] = dict()
            TEAM_SCORES[team]["last_update"] = time.time()
            TEAM_SCORES[team]["score"] = resp["score"]
            send_updates(team)


def __main(parsed_args):
    if parsed_args.ssl and os.path.isfile(
            parsed_args.ssl_cert) and os.path.isfile(parsed_args.ssl_key):
        # Start a TLS server, using TLS 1.2.
        print("Creating TLS socket", file=sys.stderr)
        WEBSOCKET_SERVER = SimpleSSLWebSocketServer(
            parsed_args.server_host,
            parsed_args.listen_port,
            ScoreUpdateWebsocket,
            parsed_args.ssl_cert,
            parsed_args.ssl_key,
            version=ssl.PROTOCOL_TLSv1_2)
    else:
        # Start an unencrypted server.
        print("Creating bare socket", file=sys.stderr)
        WEBSOCKET_SERVER = SimpleWebSocketServer(parsed_args.server_host,
                                                 parsed_args.listen_port,
                                                 ScoreUpdateWebsocket)

    print("Creating SIGINT handler", file=sys.stderr)

    def close_sig_handler(signal, frame):
        print("SIGINT caught", file=sys.stderr)
        print("Stopping server", file=sys.stderr)
        WEBSOCKET_SERVER.close()
        print("Stopping threads", file=sys.stderr)
        for thread in TEAM_CHECKER_THREADS:
            thread.running = False
            print("Joining thread", file=sys.stderr)
            thread.join()
        sys.exit()

    signal.signal(signal.SIGINT, close_sig_handler)

    # Prime the pump on the scores
    print("Getting team scores", file=sys.stderr)
    get_team_score(parsed_args.scores_table_name, parsed_args.flags_table_name,
                   parsed_args.teams)

    print("Creating threads for checking team scores", file=sys.stderr)
    TEAM_CHECKER_THREADS = [
        ScoreCheckThread(parsed_args.scores_table_name,
                         parsed_args.flags_table_name, team, parsed_args.delay)
        for team in parsed_args.teams
    ]

    print("Starting threads for checking team scores", file=sys.stderr)
    for thread in TEAM_CHECKER_THREADS:
        print("Starting thread %s" % repr(thread), file=sys.stderr)
        thread.start()
        print(thread.is_alive())

    print("Serving Websocket", file=sys.stderr)
    WEBSOCKET_SERVER.serveforever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--delay",
        type=int,
        required=False,
        default=5,
        help=
        """Delay between when individual team scores are polled, default 5 seconds"""
    )

    parser.add_argument("--listen-port",
                        type=int,
                        required=False,
                        default=8000,
                        help="""TCP port to listen on""")

    parser.add_argument(
        "--server-host",
        type=str,
        required=False,
        default="0.0.0.0",
        help="""Hostname or IP address to bind server socket to.""")

    parser.add_argument(
        "--ssl",
        required=False,
        default=False,
        action="store_true",
        help="""Whether or not to enable ssl, requires that --ssl-key and
        --ssl-cert also be provided.""")

    parser.add_argument("--ssl-cert",
                        type=str,
                        required=False,
                        default=None,
                        help="""Path to PEM encoded SSL certificate.""")

    parser.add_argument(
        "--ssl-key",
        type=str,
        required=False,
        default=None,
        help="""Path to PEM encoded SSL certificate private key.""")

    parser.add_argument(
        "--scores-table-name",
        type=str,
        required=True,
        default=None,
        help=
        """Name of AWS DynamoDB tables that stores the scores of each team.""")

    parser.add_argument(
        "--flags-table-name",
        type=str,
        required=True,
        default=None,
        help=
        """Name of AWS DynamoDB tables that stores the details of the flags""")

    parser.add_argument("--teams",
                        type=json_int_list,
                        required=True,
                        default=list(),
                        help="""List of team IDs to poll for scores.""")

    parsed_args = parser.parse_args()

    if parsed_args.ssl and (parsed_args.ssl_cert is None
                            or parsed_args.ssl_key is None):
        print("Cannot enable SSL without both a certificate and a key",
              file=sys.stderr)

    __main(parsed_args)
