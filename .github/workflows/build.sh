#!/bin/bash
# Description: Podman build script for GitHub Actions

# Print commands to logs as they're called
set -x

################################################################################
### Config start
################################################################################

# Name of container image for manifests / pushes
image_name="repo-converter"

# Define the platforms/architectures to build images for
# ARM build not working yet
# platarch="linux/amd64,linux/arm64"
platarch="linux/amd64"

################################################################################
### Config end
################################################################################

# List of image tags / env vars
# These vars are used as image tags and available inside the container as env vars
declare -a image_tags_and_env_vars=(
    "BUILD_BRANCH"
    "BUILD_COMMIT"
    "BUILD_DATE"
    "BUILD_TAG"
    "LATEST_TAG"
)

# Fill in env vars
BUILD_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BUILD_COMMIT="$(git rev-parse --short HEAD)"
BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
BUILD_TAG="$(git tag --points-at HEAD)"
LATEST_TAG="latest"

# Path to .env file to be read inside the container; values used for container logging
dot_env_file="build/.env"

# Create / clear the .env file
true > "${dot_env_file}"

# Loop through the list of env vars and write their names and values to the .env file
for var in "${image_tags_and_env_vars[@]}"
do
    # If the env var has a value
    if [[ -n "${!var}" ]]
    then
        echo "$var=${!var}" >> "${dot_env_file}"
    fi
done

# Log the content of the .env file to confirm its content
cat "${dot_env_file}"

# Count the number of /'s in platarch, and use that as the number of build jobs
# https://docs.podman.io/en/v5.3.2/markdown/podman-build.1.html#jobs-number
# If 0 is specified, then there is no limit in the number of jobs that run in parallel.
# jobs=$(echo $platarch | tr -cd / | wc -c)

# Metadata to troubleshoot failing builds
whoami
pwd
ls -al
ls -al ./*
printenv | sort -u

# Run the build
podman build \
    --file build/Dockerfile \
    --format docker \
    --jobs 0 \
    --label "org.opencontainers.image.created=$BUILD_DATE" \
    --label "org.opencontainers.image.revision=$BUILD_COMMIT" \
    --manifest "$image_name" \
    --platform "$platarch" \
    .

# Push the builds
# Loop through the list of env vars again, and push the image with the values as tags
for var in "${image_tags_and_env_vars[@]}"
do
    # If the env var has a value
    if [[ -n "${!var}" ]]
    then
        podman push "$image_name" ghcr.io/sourcegraph/"$image_name":"${!var}"
    fi
done
