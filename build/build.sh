#!/bin/bash
# Script for local dev builds

## Usage:

# ./build.sh
# Just run the build, do not start the containers

# ./build.sh <any>
# Run the build, start the containers

# c - clear the terminal
# f - follow repo-converter container's logs
# m - restart podman machine
# p - pull new images for src-cli and cloud-agent


# TODO:
    # Add `podman machine info` command to verify the local podman VM is running
    # check if the GitHub Actions build script can't be reused here?

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
# pip install --upgrade podman-compose

# Their brew cask may not get updated soon after a release
# brew install podman-compose

# Set exec flags

# Print all commands as they're run, so we don't need to echo everything
# echo "set -x to print all commands as they're run"
# set -x

# Exit on error
set -o errexit

script_name="$0"

container_name="repo-converter"

# pip requirements
req_file="./requirements.txt"

# Update the requirements.txt file
# src_dir="../src/"
# echo "Updating the ${req_file} file"
# pipreqs --force --mode no-pin --savepath "$req_file" "$src_dir"

# Sort and deduplicate the ${req_file} file
echo "Deduplicating the ${req_file} file"
LC_ALL=C sort -u -o "$req_file" "$req_file"


# Set environment variables from git metadata of this repo
echo "Gathering environment variables to bake into image's .env file"
BUILD_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BUILD_COMMIT="$(git rev-parse --short HEAD)"
BUILD_COMMIT_MESSAGE="$(git log -1 --pretty=%s)"
BUILD_DATE="$(date -u +'%Y-%m-%d %H:%M:%S UTC')"
BUILD_DIRTY="$(git diff --quiet && echo 'False' || echo 'True')"
BUILD_TAG="$(git tag --points-at HEAD)"

# File path to dotenv file to be copied into the image
ENV_FILE=".env"

# Write the contents of the dotenv file
{
    echo "BUILD_BRANCH=${BUILD_BRANCH}"
    echo "BUILD_COMMIT=${BUILD_COMMIT}"
    echo "BUILD_COMMIT_MESSAGE=${BUILD_COMMIT_MESSAGE}"
    echo "BUILD_DATE=${BUILD_DATE}"
    echo "BUILD_DIRTY=${BUILD_DIRTY}"
    echo "BUILD_TAG=${BUILD_TAG}"
} > "$ENV_FILE"

echo "Environment variables:"
cat "$ENV_FILE"

# If an m is passed in the args
if [[ "$1" == *"m"* ]]
then

    echo "$script_name args included 'm', restarting podman VM"

    # Restart the podman VM
    podman machine stop
    # Start it as a background process
    # and disown it, so it continues to run after this script ends
    # The disown doesn't seem to be working
    # podman machine start & disown
    nohup podman machine start >/dev/null 2>&1 &
    # But give it 10 seconds to start up
    sleep_time=20
    echo "Giving podman VM $sleep_time seconds to start up"
    sleep $sleep_time

fi

# Run the build
echo "Running podman build"

podman build \
    --file          ./Dockerfile \
    --format        docker \
    --jobs          0 \
    --label         "org.opencontainers.image.created=$BUILD_DATE" \
    --label         "org.opencontainers.image.revision=$BUILD_COMMIT" \
    --tag           "$container_name":build \
    ..

# If you pass any args to this script, start the built image, and follow the logs
if [[ "$1" != "" ]]
then

    # Stop any running containers
    # because podman-compose can't figure this out on its own
    echo "Stopping old containers"
    podman-compose down
    podman network rm build_default -f

    # Pull the latest tags of the other images
    if [[ "$1" == *"p"* ]]
    then
        echo "Checking for new images and pulling"
        podman-compose pull cloud-agent src-serve-git
    fi

    # Start the compose deployment
    echo "Starting new containers"
    podman-compose up \
        --detach \
        --no-recreate \
        --remove-orphans
        # --in-pod false \

    # Clear the terminal
    if [[ "$1" == *"c"* ]]
    then
        echo "Clearing terminal"
        # clear
        tput reset
    fi

    # Follow the container logs
    if [[ "$1" == *"f"* ]]
    then
        podman-compose logs "$container_name" -f #| jq
    fi

fi
