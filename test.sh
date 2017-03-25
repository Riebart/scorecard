#!/bin/bash

coverage run test.py
coverage html --include S3KeyValueStore.py,ScoreCardSubmit.py,ScoreCardTally.py

if [ $# -ne 0 ]
then
    $@
fi
