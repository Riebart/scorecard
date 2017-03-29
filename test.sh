#!/bin/bash

coverage run --branch TestScoreCard.py
coverage run --append --branch TestS3KeyValueStore.py
coverage html --include S3KeyValueStore.py,ScoreCardSubmit.py,ScoreCardTally.py

if [ $# -ne 0 ]
then
    $@
fi
