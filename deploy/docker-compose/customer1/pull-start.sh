#!/bin/bash

# To be used in a cronjob to always pull and use the latest image
# so that the running container is only x minutes/hours behind the latest version of
# the docker-compose.yaml file
# and the Docker image tagged latest in GitHub packages

# crontab -e
# */30 * * * * bash /sg/implementation-bridges/deploy/docker-compose/customer1/pull-start.sh


repo_dir="/sg/implementation-bridges"
docker_compose_dir="deploy/docker-compose/customer1"
docker_compose_file_name="docker-compose.yaml"
docker_compose_full_file_path="$repo_dir/$docker_compose_dir/$docker_compose_file_name"

log_file="$repo_dir/$docker_compose_dir/pull-start.log"

docker_cmd="docker compose -f $docker_compose_full_file_path"

docker_up_sleep_seconds=10

git_cmd="git -C $repo_dir"

function log() {
    # Define log function for consistent output format
    echo "$(date '+%Y-%m-%d - %H:%M:%S') - $0 - $1"
}

# Log to both stdout and log file
exec > >(tee -a "$log_file") 2>&1

log "Script starting"
log "Running as user: $(whoami)"
log "On branch before git pull: $($git_cmd branch -v)"
log "Docker compose file: $docker_compose_full_file_path"

log "docker ps before:"
$docker_cmd ps

command="\
    $git_cmd reset --hard                && \
    $git_cmd pull --force                && \
    $docker_cmd pull                     && \
    $docker_cmd up -d --remove-orphans      \
    "

log "Running command in a sub shell:"
# awk command to print the command nicely with newlines
echo "$command" | awk 'BEGIN{FS="&&"; OFS="&& \n"} {$1=$1} 1'

# Run the command
bash -c "$command" >> "$log_file" 2>&1

log "On branch after git pull: $($git_cmd branch -v)"

log "Sleeping $docker_up_sleep_seconds seconds to give Docker containers time to start and stabilize"
sleep $docker_up_sleep_seconds

log "docker ps after:"
$docker_cmd ps

log "Script finishing"
