#!/usr/bin/env python

import uuid
import argparse
import StringIO
import zipfile
import boto3


def zip_files(filenames):
    """
    Map a collection of files into a zip file with the same name and paths.
    """
    sso = StringIO.StringIO()
    with zipfile.ZipFile(sso, "w") as zfile:
        for fname in filenames:
            zfile.write(fname)
    sso.seek(0)
    return sso.read()


def main():
    parser = argparse.ArgumentParser(
        description="Deploy a scorecard stack with the given parameters")
    parser.add_argument(
        "--code-bucket",
        required=True,
        help="""The bucket that is used to store code zipfiles for reference
        in the CloudFormation template.""")
    parser.add_argument(
        "--stack-name",
        required=True,
        help="""The name of the stack to bring up. If the stack exists, it is
        updated instead.""")
    parser.add_argument(
        "--backend-type",
        required=False,
        default="DynamoDB",
        help="""Indicates either a DynamoDB or S3 backend for score-keeping.
        If omitted, the previous the default for new stacks is DynamoDB, and
        for stack updates, the existing value is preserved. Allowable values are
        "DynamoDB" and "S3". If set to "S3" then both --backend-s3-bucket and
        --backend-s3-prefix must be specified.""")
    parser.add_argument(
        "--backend-s3-bucket",
        required=False,
        default=None,
        help="Bucket to use for S3 backend for scorekeeping")
    parser.add_argument(
        "--backend-s3-prefix",
        required=False,
        default=None,
        help="Prefix to use for S3 backend for scorekeeping")
    parser.add_argument(
        "--score-cache-lifetime",
        required=False,
        default=None,
        help="Duration (in seconds) for lambda functions to cache team scores.")
    parser.add_argument(
        "--flag-cache-lifetime",
        required=False,
        default=None,
        help="Duration (in seconds) for lambda functions to cache game flags.")
    pargs = parser.parse_args()

    if pargs.backend_type is not None:
        if pargs.backend_type not in ["S3", "DynamoDB"]:
            print "Backend type must be one of: S3, DynamoDB"
            exit(1)
        elif pargs.backend_type == "S3":
            if pargs.backend_s3_bucket is None or pargs.backend_s3_prefix is None:
                print "If backend type is S3, both bucket and prefix must be specified."
                exit(2)

    print "Building code zip files for deployment..."
    tally_code = (str(uuid.uuid1()), zip_files(
        ["ScoreCardTally.py", "S3KeyValueStore.py", "XrayChain.py",
         "util.py"]))
    submit_code = (str(uuid.uuid1()), zip_files([
        "ScoreCardSubmit.py", "S3KeyValueStore.py", "XrayChain.py", "util.py"
    ]))

    print "Uploading code zip files to S3 bucke (%s)..." % pargs.code_bucket
    s3_client = boto3.client("s3")
    for code in [tally_code, submit_code]:
        print "    Uploading %s.zip" % code[0]
        s3_client.put_object(
            Bucket=pargs.code_bucket, Key="%s.zip" % code[0], Body=code[1])

    cfn_client = boto3.client("cloudformation")

    print "Determining stack operation..."
    try:
        stack_description = cfn_client.describe_stacks(
            StackName=pargs.stack_name)
        print "    Stack Update selected"
    except:
        print "    Stack create selected"
        stack_description = None

    print "Building stack parameters..."
    stack_params = []

    if stack_description is not None:
        stack_params.append({
            "ParameterKey": "XraySampleRate",
            "UsePreviousValue": True
        })

    stack_params.append({
        "ParameterKey": "CodeSourceBucket",
        "ParameterValue": pargs.code_bucket
    })
    stack_params.append({
        "ParameterKey": "CodeSourceTallyObject",
        "ParameterValue": tally_code[0] + ".zip"
    })
    stack_params.append({
        "ParameterKey": "CodeSourceSubmitObject",
        "ParameterValue": submit_code[0] + ".zip"
    })

    if pargs.backend_type is None:
        if stack_description is None:
            print "    Using default backend configuration"
        else:
            print "    Using previous backend configuration"
            stack_params.append({
                "ParameterKey": "KeyValueBackend",
                "UsePreviousValue": True
            })
            stack_params.append({
                "ParameterKey": "KeyValueS3Bucket",
                "UsePreviousValue": True
            })
            stack_params.append({
                "ParameterKey": "KeyValueS3Prefix",
                "UsePreviousValue": True
            })
    elif pargs.backend_type == "S3":
        print "    Configuring S3 backend (%s, %s)" % (pargs.backend_s3_bucket,
                                                       pargs.backend_s3_prefix)
        stack_params.append({
            "ParameterKey": "KeyValueBackend",
            "ParameterValue": "S3"
        })
        stack_params.append({
            "ParameterKey": "KeyValueS3Bucket",
            "ParameterValue": pargs.backend_s3_bucket
        })
        stack_params.append({
            "ParameterKey": "KeyValueS3Prefix",
            "ParameterValue": pargs.backend_s3_prefix
        })
    elif pargs.backend_type == "DynamoDB":
        print "    Configuring DynamoDB backend"
        stack_params.append({
            "ParameterKey": "KeyValueBackend",
            "ParameterValue": "DynamoDB"
        })
        if stack_description is not None:
            stack_params.append({
                "ParameterKey": "KeyValueS3Bucket",
                "UsePreviousValue": True
            })
            stack_params.append({
                "ParameterKey": "KeyValueS3Prefix",
                "UsePreviousValue": True
            })

    if pargs.score_cache_lifetime is not None:
        print "    Setting new score cache timeout"
        stack_params.append({
            "ParameterKey": "ScoreCacheLifetime",
            "ParameterValue": str(pargs.score_cache_lifetime)
        })
    elif stack_description is not None:
        stack_params.append({
            "ParameterKey": "ScoreCacheLifetime",
            "UsePreviousValue": True
        })

    if pargs.flag_cache_lifetime is not None:
        print "    Setting new flag cache timeout"
        stack_params.append({
            "ParameterKey": "FlagCacheLifetime",
            "ParameterValue": str(pargs.flag_cache_lifetime)
        })
    elif stack_description is not None:
        stack_params.append({
            "ParameterKey": "FlagCacheLifetime",
            "UsePreviousValue": True
        })

    print "Reading cloudformation template..."
    with open("cloudformation.yaml") as fp:
        template_body = fp.read()

    if stack_description is None:
        print "Creating stack..."
        cfn_client.create_stack(
            StackName=pargs.stack_name,
            TemplateBody=template_body,
            Parameters=stack_params,
            Capabilities=['CAPABILITY_IAM'])
        waiter = cfn_client.get_waiter('stack_create_complete')
    else:
        print "Updating stack..."
        cfn_client.update_stack(
            StackName=pargs.stack_name,
            TemplateBody=template_body,
            Parameters=stack_params,
            Capabilities=['CAPABILITY_IAM'])
        waiter = cfn_client.get_waiter('stack_update_complete')

    print "Waiting for stack operation to complete..."
    waiter.wait(StackName=pargs.stack_name)

    api_resource = cfn_client.describe_stack_resources(
        StackName=pargs.stack_name,
        LogicalResourceId='API')['StackResources'][0]['PhysicalResourceId']

    if stack_description is not None:
        print "Creating new API Gateway deployment..."
        apig_client = boto3.client('apigateway')
        apig_client.create_deployment(restApiId=api_resource, stageName='Main')

    print "Stack operation complete."
    print "API URL: https://%s.execute-api.%s.amazonaws.com/Main" % (
        api_resource, boto3.Session().region_name)


if __name__ == "__main__":
    main()
