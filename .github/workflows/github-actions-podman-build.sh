#!/bin/bash
# Description: Podman build script for GitHub Actions

# Print commands to logs as they're called
set -x

# Exit on error
set -e

################################################################################
### Config start
################################################################################

# Name of container image for manifests / pushes
image_name="repo-converter"

# Full image registry and path
image_registry_path="ghcr.io/sourcegraph/$image_name"

# Define the platforms/architectures to build images for
# ARM build not working yet
# platform_architecture="linux/amd64,linux/arm64"
platform_architecture="linux/amd64"

################################################################################
### Config end
################################################################################

# List of image tags / env vars
# These vars are used as image tags and available inside the container as env vars
declare -a env_vars=(
    "BUILD_BRANCH"
    "BUILD_COMMIT"
    "BUILD_COMMIT_MESSAGE"
    "BUILD_DATE"
    "BUILD_TAG"
)

declare -a image_tags=(
    "BUILD_BRANCH"
    "BUILD_TAG"
    "LATEST_TAG"
)

# Fill in env vars
BUILD_BRANCH="$(git rev-parse --abbrev-ref HEAD | sed 's/[^a-zA-Z0-9]/-/g' )" # Somehow turned out to be HEAD on a tag build???
BUILD_COMMIT="$(git rev-parse --short HEAD)"
BUILD_COMMIT_MESSAGE="$(git log -1 --pretty=%s)"
BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
BUILD_TAG="$(git tag --points-at HEAD)"
LATEST_TAG="latest"

# Path to .env file to be read inside the container; values used for container logging
dot_env_file="build/.env"

# Create / clear the .env file
true > "${dot_env_file}"

# Loop through the list of env vars and write their names and values to the .env file
for env_var in "${env_vars[@]}"
do
    echo "$env_var=${!env_var}" >> "${dot_env_file}"
done

# Log the content of the .env file to confirm its content
cat "${dot_env_file}"

# Metadata to troubleshoot failing builds
whoami
pwd
ls -al
ls -al ./*
printenv | sort -u

podman_build_cache_path="$image_registry_path/podman-build-cache"

# Get the podman version number
# This is a new arg, and seems to be failing
#    --inherit-labels false \
podman version

# Run the build
podman build \
    --cache-from    "$podman_build_cache_path" \
    --cache-to      "$podman_build_cache_path" \
    --file          build/Dockerfile \
    --format        docker \
    --jobs          0 \
    --label         "org.opencontainers.image.created=$BUILD_DATE" \
    --label         "org.opencontainers.image.revision=$BUILD_COMMIT" \
    --layers        \
    --manifest      "$image_name" \
    --platform      "$platform_architecture" \
    .

# Push the builds
# Loop through the list of env vars again, and push the image with the values as tags
for image_tag in "${image_tags[@]}"
do
    # If the env var has a value
    # BUILD_TAG doesn't have a value if the current Git commit doesn't have a tag pointing to it
    if [[ -n "${!image_tag}" ]]
    then
        podman push "$image_name" "$image_registry_path":"${!image_tag}"
    fi
done
