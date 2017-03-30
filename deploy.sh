#!/bin/bash
set -e

# Arg1: Bucket to use for staging the code files
# Arg2: Cloudformation stack to update. If the stack exists, then the stack will be updated, otherwise a new stack will be created witht he given name.

# Generate a unique UUID for use when uploading components of this stack
prefix=`uuidgen`

# Copy up the Python files
zip -q - ScoreCardTally.py S3KeyValueStore.py | aws s3 cp - "s3://$1/$prefix/ScoreCardTally.zip"
zip -q - ScoreCardSubmit.py S3KeyValueStore.py | aws s3 cp - "s3://$1/$prefix/ScoreCardSubmit.zip"

stack_params="[
{
    \"ParameterKey\": \"CodeSourceBucket\",
    \"ParameterValue\": \"$1\"
},
{
    \"ParameterKey\": \"CodeSourceTallyObject\",
    \"ParameterValue\": \"$prefix/ScoreCardTally.zip\"
},
{
    \"ParameterKey\": \"CodeSourceSubmitObject\",
    \"ParameterValue\": \"$prefix/ScoreCardSubmit.zip\"
},
{
    \"ParameterKey\": \"KeyValueBackend\",
    \"UsePreviousValue\": true
},
{
    \"ParameterKey\": \"KeyValueS3Bucket\",
    \"UsePreviousValue\": true
},
{
    \"ParameterKey\": \"KeyValueS3Prefix\",
    \"UsePreviousValue\": true
},
{
    \"ParameterKey\": \"ScoreCacheLifetime\",
    \"UsePreviousValue\": true
},
{
    \"ParameterKey\": \"FlagCacheLifetime\",
    \"UsePreviousValue\": true
}]"

if aws cloudformation describe-stacks --stack-name "$2" > /dev/null 2>&1
then
    echo "Updating stack" >&2
    aws cloudformation update-stack --stack-name "$2" --template-body "`cat cloudformation.yaml`" --capabilities CAPABILITY_IAM --parameters "$stack_params" >&2
    aws cloudformation wait stack-update-complete --stack-name "$2" >&2
else
    aws cloudformation create-stack --stack-name "$2" --template-body "`cat cloudformation.yaml`" --capabilities CAPABILITY_IAM --parameters "$stack_params" >&2
    aws cloudformation wait stack-create-complete --stack-name "$2" >&2
fi

echo "Waiting on stack operation to complete" >&2
api_id=`aws cloudformation describe-stack-resources --stack-name ScoreCard --logical-resource-id API --query StackResources[0].PhysicalResourceId --output text`
aws apigateway create-deployment --rest-api-id $api_id --stage-name Main >&2
echo $api_id
