#!/bin/bash

coverage run --branch TestScoreCard.py
coverage run --append --branch TestS3KeyValueStore.py
coverage run --append --branch TestXrayChain.py
coverage html --include XrayChain.py,S3KeyValueStore.py,ScoreCardSubmit.py,ScoreCardTally.py

if [ $# -ne 0 ]
then
    $@
fi
