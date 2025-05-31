# syntax=docker/dockerfile:1
# Using version:1 means always getting the latest version of dockerfile syntax within major version 1
# https://docs.docker.com/build/dockerfile/frontend/#stable-channel
# version:1 is still the most popular version
# https://sourcegraph.com/search?q=context:global+%23+syntax%3Ddocker/dockerfile:(.*)&patternType=regexp&sm=0&expanded=&groupBy=group

# Using Ubuntu LTS
FROM ubuntu:22.04 AS base

# Using Python Slim base
# https://hub.docker.com/layers/library/python/slim/images/sha256-747576ffc7523e2cc620ae304eb7304cedc8abff915adc77f3ce53a33ad1730d
#FROM python:slim

# Avoid stuck build due to user prompt
ARG DEBIAN_FRONTEND=noninteractive

# Prevents Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering
ENV PYTHONUNBUFFERED=1

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

# Download dependencies as a separate step to take advantage of Docker's caching
# Leverage a cache mount to /root/.cache/pip to speed up subsequent builds
# Leverage a bind mount to requirements.txt to avoid having to copy them into
# into this layer
# Install requirements
# RUN --mount=type=cache,target=/root/.cache/pip \
#     --mount=type=bind,source=../requirements.txt,target=./requirements.txt \
#     python3 -m pip install --upgrade pip && \
#     python3 -m pip install -r requirements.txt


# Switching to podman compose build

# Failed builds leave buildah containers dangling in an invalid state
# See these containers with
# podman ps --all --external
# Clear these buildah containers with
# podman rmi --force --all

# This step seems to be failing on podman build, seems to require ',z' option on the bind mount as per
# https://github.com/containers/podman/issues/15423#issuecomment-1223594100

# This step is also failing due to the directory mismatch, had to remove '../' in the source bind mapping
# RUN --mount=type=cache,target=/root/.cache/pip \
#     --mount=type=bind,source=requirements.txt,target=requirements.txt,z \
#     python3 -m pip install --upgrade pip && \
#     python3 -m pip install -r requirements.txt

# Switching to podman build
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=build/requirements.txt,target=requirements.txt,z \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install --root-user-action=ignore -r requirements.txt

# Create sourcegraph user
# https://github.com/containers/podman/issues/4016
# RUN useradd sourcegraph
# USER sourcegraph

# Copy the source code into the image
WORKDIR /sourcegraph/repo-converter
COPY src/ .

# Copy the dotenv file into the image
COPY build/.env .

# Start the container
CMD ["/usr/bin/python3", "/sourcegraph/repo-converter/main.py"]
