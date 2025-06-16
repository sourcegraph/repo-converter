#!/bin/bash
# Script for local dev builds

## Usage:

# ./build.sh
# Run the build, do not start the containers

# ./build.sh c
# Run the build, start the containers, clear the terminal, and follow repo-converter's logs

# ./build.sh <any>
# Run the build, start the containers, and follow repo-converter's logs


# TODO: check if the GitHub Actions build script can't be reused here?

## Switching to podman

# Install podman on macOS
# https://podman.io/docs/installation#macos
# brew install podman
# podman machine init
# podman machine start
# sudo /opt/homebrew/Cellar/podman/5.5.0/bin/podman-mac-helper install
# podman machine stop
# podman machine start

# Install podman-compose, because that's an unrelated OSS project
# brew install podman-compose

# Set exec flags

# Print all commands as they're run, so we don't need to echo everything
echo "set -x to print all commands as they're run"
set -x

# Exit on error
set -o errexit


# Update the requirements.txt file
# APPLICATION_CODE_DIR="../src/"
# pipreqs --force --mode no-pin --savepath "$REQUIREMENTS_FILE" "$APPLICATION_CODE_DIR"

# Sort and deduplicate the ${REQUIREMENTS_FILE} file
REQUIREMENTS_FILE="./requirements.txt"
echo "Sort and deduplicate the ${REQUIREMENTS_FILE} file"
LC_ALL=C sort -u -o "$REQUIREMENTS_FILE" "$REQUIREMENTS_FILE"


# Set environment variables from git metadata of this repo
BUILD_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BUILD_COMMIT="$(git rev-parse --short HEAD)"
BUILD_DATE="$(date -u +'%Y-%m-%d %H:%M:%S UTC')"
BUILD_DIRTY="$(git diff --quiet && echo 'False' || echo 'True')"
BUILD_TAG="$(git tag --points-at HEAD)"

# File path to dotenv file to be copied into the image
ENV_FILE=".env"

# Write the contents of the dotenv file
{
    echo "BUILD_BRANCH=${BUILD_BRANCH}"
    echo "BUILD_COMMIT=${BUILD_COMMIT}"
    echo "BUILD_DATE=${BUILD_DATE}"
    echo "BUILD_DIRTY=${BUILD_DIRTY}"
    echo "BUILD_TAG=${BUILD_TAG}"
} > "$ENV_FILE"

# Run the build
podman-compose build repo-converter

# If you pass any args to this script, start the built image, and follow the logs
if [ "$1" != "" ]
then

    # Stop any running containers
    # because podman-compose can't figure this out on its own
    podman-compose down

    # Pull the latest tags of the other images
    if [ "$1" == "*p*" ]
    then
        podman-compose pull
    fi

    # Start the compose deployment
    podman-compose up -d --remove-orphans

    # Clear the terminal
    if [ "$1" == "*c*" ]
    then
        clear
    fi

    # Follow the container logs
    if [ "$1" == "*f*" ]
    then
        podman-compose logs repo-converter -f
    fi

fi
