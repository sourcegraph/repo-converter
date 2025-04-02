#!/bin/bash

# Exit on error
set -o errexit

# Clear the terminal
clear

# Update the requirements.txt file
pipreqs --force --mode gt .

# Deduplicate the requirements.txt file
LC_ALL=C sort -u -o requirements.txt requirements.txt

# Set environment variables from git metadata of this repo
export BUILD_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
export BUILD_COMMIT="$(git rev-parse --short HEAD)"
export BUILD_DATE="$(date -u +'%Y-%m-%d %H:%M:%S')"
export BUILD_DIRTY="$(git diff --quiet && echo 'False' || echo 'True')"
export BUILD_TAG="$(git tag --points-at HEAD)"

# Build the repo-converter image, and start the container
docker compose up -d --build --remove-orphans

# If you pass in an arg to this script
# it'll clear the terminal and start following the logs of the repo-converter container
if [ "$1" != "" ]
then

    clear
    docker compose logs repo-converter -f

fi
