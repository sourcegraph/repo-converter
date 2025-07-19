# syntax=docker/dockerfile:1
# Using version:1 means always getting the latest version of dockerfile syntax within major version 1
# https://docs.docker.com/build/dockerfile/frontend/#stable-channel
# version:1 is still the most popular version
# https://sourcegraph.com/search?q=context:global+%23+syntax%3Ddocker/dockerfile:(.*)&patternType=regexp&sm=0&expanded=&groupBy=group

# Using Ubuntu LTS
FROM ubuntu:22.04 AS base
# TODO: Switch to Wolfi Python base

# Using Python Slim base
# https://hub.docker.com/layers/library/python/slim/images/sha256-747576ffc7523e2cc620ae304eb7304cedc8abff915adc77f3ce53a33ad1730d
#FROM python:slim

# Avoid stuck build due to user prompt
ARG DEBIAN_FRONTEND=noninteractive

# PYTHONDONTWRITEBYTECODE - Prevents Python from writing pyc files
# PYTHONUNBUFFERED - Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering
ENV \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install packages
# default-jre needed for Atlassian's svn-migration-scripts.jar
#        default-jre \
# gcc and python3-dev needed for psutils
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends -y \
        cron \
        gcc \
        git \
        git-svn \
        lsof \
        python3 \
        python3-dev \
        python3-pip \
        python3-wheel \
        subversion \
        systemctl \
        vim && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    systemctl enable cron && \
    systemctl start cron

# Set Git defaults, system-wide, in /etc/gitconfig
RUN git config --system safe.directory "*" && \
    git config --system init.defaultBranch main

# cd to /sg/repo-converter in the image
WORKDIR /sg/repo-converter

# Copy the requirements file into the image
COPY build/requirements.txt build/requirements.txt

# Install required Python modules
RUN --mount=type=cache,target=/tmp/pip-cache \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install --root-user-action=ignore -r build/requirements.txt

# Add OCI annotations to image
# These don't change often, so could be earlier in the build,
# but they're super lightweight, so the impact of being lower is low
# And we'd hate for a change in a label to cause dependency installations
# to have to run again
# NOTE: the --label args on the podman build command are a separate build step,
# so the new values for org.opencontainers.image.created and revision do not
# invalidate the cache for this LABEL block
LABEL \
    org.opencontainers.image.authors="Sourcegraph" \
    org.opencontainers.image.base.name="docker.io/library/ubuntu" \
    org.opencontainers.image.description="Container for converting non-Git repos to Git" \
    org.opencontainers.image.source="https://github.com/sourcegraph/repo-converter" \
    org.opencontainers.image.title="repo-converter" \
    org.opencontainers.image.url="https://github.com/sourcegraph/repo-converter/pkgs/container/repo-converter" \
    org.opencontainers.image.vendor="Sourcegraph"

# Copy the source code into the image
# The contents of this dir will change most builds
COPY src/ src/

# Copy the dotenv file into the image
# The contents of this file changes every build
COPY build/.env build/.env

# Create the user, with a home directory
RUN groupadd sourcegraph --gid 10002 && \
     useradd sourcegraph --uid 10001 --gid sourcegraph --create-home --home-dir /home/sourcegraph

# Give ownership of the whole /sg dir and all its contents to the new user
RUN chown -R sourcegraph:sourcegraph /sg

# Switch to the new user
USER sourcegraph

# Start the container
CMD ["/usr/bin/python3", "/sg/repo-converter/src/main.py"]
