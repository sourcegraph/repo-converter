# syntax=docker/dockerfile:1@sha256:4c68376a702446fc3c79af22de146a148bc3367e73c25a5803d453b6b3f722fb
# Using version:1 means always getting the latest version of dockerfile syntax within major version 1
# https://docs.docker.com/build/dockerfile/frontend/#stable-channel
# version:1 is still the most popular version
# https://sourcegraph.com/search?q=context:global+%23+syntax%3Ddocker/dockerfile:(.*)&patternType=regexp&sm=0&expanded=&groupBy=group

# Using Ubuntu LTS
FROM ubuntu:22.04@sha256:ed1544e454989078f5dec1bfdabd8c5cc9c48e0705d07b678ab6ae3fb61952d2 as base

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
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt

# # Create sourcegraph user
# RUN useradd sourcegraph
# USER sourcegraph

# Copy the source code into the container
WORKDIR /sourcegraph
COPY run.py .

# Start the container
CMD ["/usr/bin/python3", "/sourcegraph/run.py"]
