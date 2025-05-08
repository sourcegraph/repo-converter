#!/bin/bash

REQUIREMENTS_FILE="../requirements.txt"
APPLICATION_CODE_DIR="../repo-converter/"

# Exit on error
set -o errexit

# Update the requirements.txt file
# pipreqs --force --mode no-pin --savepath "$REQUIREMENTS_FILE" "$APPLICATION_CODE_DIR"

# Sort and deduplicate the requirements.txt file
LC_ALL=C sort -u -o "$REQUIREMENTS_FILE" "$REQUIREMENTS_FILE"

# Set environment variables from git metadata of this repo
export BUILD_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
export BUILD_COMMIT="$(git rev-parse --short HEAD)"
export BUILD_DATE="$(date -u +'%Y-%m-%d %H:%M:%S')"
export BUILD_DIRTY="$(git diff --quiet && echo 'False' || echo 'True')"
export BUILD_TAG="$(git tag --points-at HEAD)"

# Build the repo-converter image
docker compose build repo-converter

# If you pass any args to this script
if [ "$1" != "" ]
then

    # Start the compose deployment
    docker compose up -d --remove-orphans

    # Clear the terminal
    clear

    # Follow the container logs
    docker compose logs repo-converter -f

fi
