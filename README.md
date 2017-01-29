# ScoreCard

This intends to provide a backend and partial front-end for submitting flags for teams, tracking and displaying scores, and tracking the flags available in a competition.

Modify the `constnts.js.example` to contain your team IDs (integers) and API Gateway endpoint URL.

## Requirements and Specifications

The requirements for this scoring engine, and hence the target use case, are the following.

- Teams will have an ID that is an integer.
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

The dashboard page will poll periodically (10 seconds is the default) for tallies of the teams defined in the `constants.js` file.

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
  - Optional: If included for a flag without a timeout, this property is ignored. When included and set to True for a flag with a timeout then the flag is a revocable-alive flag. If it is included and set to false for a flag with a timeout then the flag is a revocable-dead flag.
- `auth_key` (Map)
  - A mapping of stringifications of the team IDs to arbitrary strings that represent the key that must be supplied for a team to successfully claim this flag.

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

The API Gateway has the following structure Swagger+APIG Extension definition:

```json
{
  "swagger": "2.0",
  "info": {
    "version": "2017-01-29T18:37:56Z",
    "title": "ScoreCard"
  },
  "host": "**********.execute-api.us-east-1.amazonaws.com",
  "basePath": "/Production",
  "schemes": [
    "https"
  ],
  "paths": {
    "/flag": {
      "post": {
        "produces": [
          "application/json"
        ],
        "responses": {
          "200": {
            "description": "200 response",
            "schema": {
              "$ref": "#/definitions/Empty"
            },
            "headers": {
              "Access-Control-Allow-Origin": {
                "type": "string"
              }
            }
          }
        },
        "x-amazon-apigateway-integration": {
          "responses": {
            "default": {
              "statusCode": "200",
              "responseParameters": {
                "method.response.header.Access-Control-Allow-Origin": "'*'"
              }
            }
          },
          "uri": "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:000000000000:function:ScoreCard-Submit/invocations",
          "passthroughBehavior": "when_no_match",
          "httpMethod": "POST",
          "contentHandling": "CONVERT_TO_TEXT",
          "type": "aws"
        }
      },
      "options": {
        "consumes": [
          "application/json"
        ],
        "produces": [
          "application/json"
        ],
        "responses": {
          "200": {
            "description": "200 response",
            "schema": {
              "$ref": "#/definitions/Empty"
            },
            "headers": {
              "Access-Control-Allow-Origin": {
                "type": "string"
              },
              "Access-Control-Allow-Methods": {
                "type": "string"
              },
              "Access-Control-Allow-Headers": {
                "type": "string"
              }
            }
          }
        },
        "x-amazon-apigateway-integration": {
          "responses": {
            "default": {
              "statusCode": "200",
              "responseParameters": {
                "method.response.header.Access-Control-Allow-Methods": "'DELETE,GET,HEAD,OPTIONS,PATCH,POST,PUT'",
                "method.response.header.Access-Control-Allow-Headers": "'Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token'",
                "method.response.header.Access-Control-Allow-Origin": "'*'"
              }
            }
          },
          "requestTemplates": {
            "application/json": "{\"statusCode\": 200}"
          },
          "passthroughBehavior": "when_no_match",
          "type": "mock"
        }
      }
    },
    "/score/{Team}": {
      "get": {
        "consumes": [
          "application/json"
        ],
        "produces": [
          "application/json"
        ],
        "parameters": [
          {
            "name": "Team",
            "in": "path",
            "required": true,
            "type": "string"
          }
        ],
        "responses": {
          "200": {
            "description": "200 response",
            "schema": {
              "$ref": "#/definitions/Empty"
            },
            "headers": {
              "Access-Control-Allow-Origin": {
                "type": "string"
              }
            }
          }
        },
        "x-amazon-apigateway-integration": {
          "responses": {
            "default": {
              "statusCode": "200",
              "responseParameters": {
                "method.response.header.Access-Control-Allow-Origin": "'*'"
              }
            }
          },
          "requestTemplates": {
            "application/json": "{ \"team\": \"$input.params('Team')\" }"
          },
          "uri": "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:000000000000:function:ScoreCard-Tally/invocations",
          "passthroughBehavior": "when_no_templates",
          "httpMethod": "POST",
          "contentHandling": "CONVERT_TO_TEXT",
          "type": "aws"
        }
      },
      "options": {
        "consumes": [
          "application/json"
        ],
        "produces": [
          "application/json"
        ],
        "responses": {
          "200": {
            "description": "200 response",
            "schema": {
              "$ref": "#/definitions/Empty"
            },
            "headers": {
              "Access-Control-Allow-Origin": {
                "type": "string"
              },
              "Access-Control-Allow-Methods": {
                "type": "string"
              },
              "Access-Control-Allow-Headers": {
                "type": "string"
              }
            }
          }
        },
        "x-amazon-apigateway-integration": {
          "responses": {
            "default": {
              "statusCode": "200",
              "responseParameters": {
                "method.response.header.Access-Control-Allow-Methods": "'DELETE,GET,HEAD,OPTIONS,PATCH,POST,PUT'",
                "method.response.header.Access-Control-Allow-Headers": "'Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token'",
                "method.response.header.Access-Control-Allow-Origin": "'*'"
              }
            }
          },
          "requestTemplates": {
            "application/json": "{\"statusCode\": 200}"
          },
          "passthroughBehavior": "when_no_match",
          "type": "mock"
        }
      }
    }
  },
  "definitions": {
    "Empty": {
      "type": "object",
      "title": "Empty Schema"
    }
  }
}
```
