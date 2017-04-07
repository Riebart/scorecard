# ScoreCard

This intends to provide a backend and partial front-end for submitting flags for teams, tracking and displaying scores, and tracking the flags available in a competition.

Modify the `constnts.js.example` to contain your team IDs (integers) and API Gateway endpoint URL.

## QuickStart: Backend

To deploy, have `boto3` installed (`pip install boto3`) and AWS API credentials configured, and use the `deploy.py` script to deploy a new stack.

```bash
python deploy.py --stack-name ScoreCard --code-bucket cf-templates-2m24puvkjhv-us-east-1
```

This will deploy a default configuration using DynamoDB for both the flag configuration and score-keeping, with minimal capacity (1RCU and 1WCU) provisioned for each table.

You can deploy an S3-based key-value backend for score keeping which provides better scaling than DynamoDB up to a few hundres TPS with truly on-demand cost.

```bash
python deploy.py --stack-name ScoreCard --code-bucket cf-templates-2m24puvkjhv-us-east-1 --backend-type S3 --backend-s3-bucket my-key-value-bucket --backend-s3-prefix CTF-Mar2017-ScoreCard
```

### Unit Testing

A collection local unit tests that use moto and are run under coverage with branch coverage tracking are included and can be run with:

```bash
MOCK_XRAY=TRUE bash test.sh
```

You can get coverage html output with:

```bash
MOCK_XRAY=TRUE bash test.sh tar -cf - htmlcov | tar -xf -
```

See the **Xray** section for details on the `MOCK_XRAY=TRUE` environment variable.

### Live Integration Testing

Once deployed, you can run an integration test-suite against your deployed stack to ensure that it deployed correctly.

```bash
MOCK_XRAY=TRUE python test.py --stack-name ScoreCard
```

The stack will be temporarily modified to eliminate caching for testing purposes, and restore your configured cache parameters after the tests complete (successfully or otherwise).

See the **Xray** section for details on the `MOCK_XRAY=TRUE` environment variable.

**Note**: Only items created in DynamoDB are cleaned up. When an S3 backend for score data is chosen then the associated objects that are created by the API backend in S3 are *not* cleaned up and will reamin.

### Sample Data

Once a stack is deployed, you can use the `sample_game.py` script to generate and insert random simple sample data into the live stack. It will output log messages to stderr, and JSON lines to stdout that indicate the team ID and names, the flag IDs and weights, and the teams and scores. While claiming flags, the script also asserts that the live stack is reporting the correct score for each team.

```bash
python sample_game.py --stack-name ScoreCard
```

This leaves the stack with data in it, unlike the integration testing script which removes all data that was inserted into the DynamoDB tables.

This will also output a new constants.js file named as `constants.js.sample_{StackName}`.

## QuickStart: Frontend

Once the backend has been deployed, copy the `constants.js.example` file to `constants.js`, and edit the `API_ENDPOINT` to match that output at the end of the `deploy.py` output. Edit the `TEAMS` list to include the list of team IDs (and optionally, team names for client-side display). Host the following files together on a webserver (or S3) and distribute the link to the dashboard and submission HTML pages:

- constants.js
- dashboard-app.js
- submit-app.js
- dashboard.html
- submit.html

## Requirements and Specifications

The requirements for this scoring engine, and hence the target use case, are the following.

- Teams will have an ID that is an integer, with enough integer range that collisions are unlikely and brute-forcing the range is infeasible (minimum 64-bit).
- Flags are arbitrary strings (not binary data)
- Flags are worth a certain number of points, stored as a floating point value that is permitted to be negative.
- Attempts to claim a flag should return, in a timely fashion, whether or not the attempt was successful.
- No information should be leaked as to whether a submitted flag is close to an existing flag. Only exact matches count.
- If a team attempts to claim a flag and is unauthorized to do so (via `auth_key` mentioned later), the same response will be returned as would have been if the flag does not exist (that is, no information is leaked as to the exitence of a flag with authorization denied).
- There are three classes of flags based on when they count for points
  - Durable/discoverable flags are discovered (such as by reverse engineering a binary), and submitted once granting the team the points of that flag irrecovably.
  - Revocable-Alive flags are flags that are reported by infrastructure elements of the competition and in addition to a weight, they are accompanied by a timeout value. This flag is only worth points if it has been reported in the last `timeout` seconds. This could be points awarded for keeping a webserver alive and responding.
  - Revocable-Dead flags are similar to the previous category in that they are reported by infrastructure elements and have an associated timeout value. The difference, however, is that these flags only count for points if they have *not* been reported in the last `timeout` seconds. This could be points awarded by changing default login credentials on an infrastructure element or terminating a rogue process.
- All flags support an authentication scheme that prevents adversarial conduct between teams, where one team may report a Revocable-Dead flag for another team, preventing them from scoring those points.
    - This is accomplished with an optional `auth_key` property associated with each flag that is a mapping from team IDs to an arbitrary string. For a flag with an `auth_key` property, all attempts to claim that flag for a team must also include the `auth_key` for that flag/team pairing. If that key is not provided, or provided and incorrect, then the same result is returned as if an attempt was made to claim a flag that does not exist.

Obvious, but notable, properties:

- Discoverable flags cannot be claimed multiple times.

## Frontend

The frontend for this scoring system is HTML+AngularJS web interfaces that provide ways of tallying the scores for teams, as well as for teams to submit flags. These are implemented in `dashboard.html`/`dashboard-app.js` and `submit.html`/`submit-app.js` respectively, and both JavaScript applications rely on the `constants.js` file which supplies the list of team IDs for the dashboard as well as the API Gateway endpoint URL for both the dashboard and submission pages.

The dashboard page will poll periodically (10 seconds is the default which is hardcoded into the `dashboard-app.js` JavaScript) for tallies of the teams defined in the `constants.js` file.

The submission page does client-side parsing of the given team ID to an integer, and will alert the user if the given team ID is invalid. This depends on the accuracy of JavaScript's `parseInt()` method. When a user submits a flag feedback is provided synchronously (disabling the submission button to indicate that flag verification is in progress).

## Backend

The backend services for this are two AWS Lambda functions (Python) that interface with two DynamoDB tables and are invoked from an API Gateway API.

### Amazon DynamoDB

The backend leverages two DynamoDB tables, one that stores the possible flags (`ScoreCard-Flags`), and one that stores the state of an ongoing event (`ScoreCard-Teams`).

The `Teams` table has a very simple structure that stores every valid flag claimed by a team, and the last time the flag was reported for that team.

- `team` (Number) - Hash key
- `flag` (String) - Sort key
- `last_seen` (Number)

The `Flags` table has a more complicated structure that stores each flag, it's accompanied weight, timeout, and authorization information.

- `flag` (String) - Hash key
- `weight` (Number)
  - If this value is omitted, then the flag is ignored and treated as invalid. No dfault weight is assigned to unweighted flags.
- `timeout` (Number)
  - Optional: If not included, then the flag is a discoverable/durable flag, otherwise it is a revocable flag.
- `yes` (Boolean)
  - Optional: If included for a flag without a timeout, this property is ignored. When not included, or included and set to True for a flag with a timeout then the flag is a revocable-alive flag. If it is included and set to false for a flag with a timeout then the flag is a revocable-dead flag.
- `auth_key` (Map)
  - A mapping of stringifications of the team IDs to arbitrary strings that represent the key that must be supplied for a team to successfully claim this flag.

### Amazon S3

There is an alternate score-keeping backend that uses S3 as a large key-value storage platform. This backend can be chosen through the Cloudformation template parameters (exposed nicely by the `--backend-type` option to `deploy.py`).

This backend is recommended for most deployments, howver it is more opaque and offers a less intuitive interface for visibility into the scores of teams. This backend will perform better and will not incur the costs associated with unused provisioned capacity, however GET operations will be charged at standard S3 rates (as of this: 0.004USD/10000 requests).

### AWS Lambda functions

The two AWS Lambda functions called by the API implement the logic for interacting with the DynamoDB table, as well as caching behaviour to enabled scaling to large client-numbers without increasing DynamoDB capacity.

- `ScoreCardSubmit.py`
  - No caching functions exist here to ensure that if flags are added in the middle of a competition, they can be claimed immediately.
  - Validates input (team, flag, and authorization), and if valid (flag exists, and all authorization information matches appropriately) inserts a row into the Teams DynamoDB table that indicates that the given team claimed the given flag at a time determined on the server-side fo the communication.
- `ScoreCardTally.py`
  - The intended use case is that it is possible that every participant may be tallying the scores for one or more teams at a frequency of once every several seconds. This can result in several hundred teams being tallied per minute, and caching is used to accomplish this without a high DynamoDB read capacity at the expense of immediacy of results being reflected in the tallies.
  - Caching of available flags for scoring is used to prevent scanning a DynamoDB table on every tally. The available flags table is only scanned once every 30 seconds.
  - Caching of a team's score is done to ensure that large teams querying for their score very rapidly do not end up exceeding DynamoDB capacity. The score of a team is only recomputed every 10 seconds, and all queries inside of the cache lifetime are served without DynamoDB reads.

### API Gateway

All API resources and methods permit a request origin of `*` as this exposes an API and thus should be callable from any HTML interface. The API has the following structure:

- POST @ `/flag`
  - JSON body input
  
  | Key | Type | Optional | Description |
  |---|---|---|---|
  | `team` | Integer | No | The team ID for the team claiming the flag. |
  | `flag` | String | No | The flag being claimed. |
  | `auth_key` | String | Yes | The authorization key that is to be matched against the team's value in the `auth_key` property of the flag. If this is unspecified and the flag requires an auth key, then the flag is invalid. If this is specified and does not match the required value, then the flag is invalid. |

  - JSON body return value

  | Key | Type | Optional | Description |
  |---|---|---|---|
  | `ValidFlag` | Boolean | No | Whether or not the flag claim was successful. If this is `true` then the flag was successfulyl claimed. |
  | `ClientError` | List | Yes | If this key exists, it contains a list of strings that describe errors encountered in the provided input. These errors are format/client errors and do not leak information about validitiy or authorization when claiming a flag. |


- GET @ `/score/{Team}`
  - Accepts a URL parameter, such as GET@`/score/10`, and returns the current score of the team queried.
  - JSON body return value

  | Key | Type | Optional | Description |
  |---|---|---|---|
  | `Team` | Integer | No | The team specified in the query. |
  | `Score` | Number | No | The score of the team in the specified query. |
  | `ClientError` | List | Yes | If this key exists, it contains a list of strings that describe errors encountered in the provided input. These errors are format/client errors and do not leak information about validitiy or authorization when claiming a flag. |

### XRay

AWS Xray tracing is included to provide insights into timing and performance of the portions of the code. Whwen running udner moto, there are issues with the use of the real Xray service. Since moto does not mock Xray endpoints, the solution is to use an environment variable, `MOCK_XRAY`, that, if it exists with any vale, disables submission to the Xray API. All other XrayChain.Chain member functions will funciton as normal.

The traced data collected by Xray allows for deep insights into the timings and behaviours of the backend.

The traced data can be aggregated by the Xray web console into a service map that shows the latencies and connections of the various computing steps.

![Xray Service Map](/images/xray_service-map.png?raw=true)

The traces can be filtered by annotations to show only selected projections and filtered slices of the traces to identify performance in various cases. Current annotations supported are:

- `Cache` is either `Hit` or `Miss`, and represents whether a score tally query hit or missed the in-memory lambda cache.
- `BackendType` is either `DynamoDB` or `S3`.

![Timings for cache hits](/images/xray_cache-hit.png?raw=true)
![Timings for cache misses](/images/xray_cache-miss.png?raw=true)

Individual traces can be inspected for waterfall and grouped timeline information.

![Waterfall timeline for a tally operation](/images/xray_tally-timeline.png?raw=true)
![Waterfall timeline for a submit operation](/images/xray_submit-timeline.png?raw=true)

Traces can be sorted based on latency and other properties to identify and drill down into outliers.

![Sorted traces showing outliers](/images/xray_trace-sorting.png?raw=true)


## Dockerfile and Unit Tests

The Dockerfile included builds the test environment suitable for running the unit-tests which depend on the Python coverage module, as well as moto.

Unit tests use the Python unittest framework.

## TODO

- Permit fetching scores for multiple teams in a single request
  - Optimizes costs by reducing the number of API Gateway and lambda invocations, and amortizing overhead of lambda functions across more fetches.
- Use Python threading to optimize the time spent fetching S3 objects for many flags and teams in a single invocation
  - Optimizes for reducing Lambda runtime and improves repsonsiveness.
