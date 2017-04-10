#!/bin/bash

coverage run --branch TestScoreCard.py -v
coverage run --append --branch TestS3KeyValueStore.py -v
coverage run --append --branch TestXrayChain.py -v
coverage html --include util.py,XrayChain.py,S3KeyValueStore.py,ScoreCardSubmit.py,ScoreCardTally.py

if [ $# -ne 0 ]
then
    $@
fi
