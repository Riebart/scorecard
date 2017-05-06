#!/bin/bash

export PYTHONPATH=..:$PYTHONPATH
coverage run --branch test/TestScoreCard.py -v
coverage run --append --branch test/TestS3KeyValueStore.py -v
coverage run --append --branch test/TestXrayChain.py -v
coverage html --include util.py,XrayChain.py,S3KeyValueStore.py,ScoreCardSubmit.py,ScoreCardTally.py

if [ $# -ne 0 ]
then
    $@
fi
