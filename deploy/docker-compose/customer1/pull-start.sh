#!/bin/bash

# To be used in a cronjob to always pull and use the latest image
# so that the running container is only x minutes/hours behind the latest version of
# the docker-compose.yaml file
# and the Docker image tagged latest in GitHub packages

# crontab -e
# */30 * * * * bash /sg/repo-converter/deploy/docker-compose/customer1/pull-start.sh


## Setup
# Define file paths
repo_dir="/sg/repo-converter"
docker_compose_dir="deploy/docker-compose/customer1"
docker_compose_file_name="docker-compose.yaml"
docker_compose_full_file_path="$repo_dir/$docker_compose_dir/$docker_compose_file_name"

# Define other common variables needed
docker_cmd="docker compose -f $docker_compose_full_file_path"
docker_up_sleep_seconds=10
git_cmd="git -C $repo_dir"
log_file="/var/log/sg/pull-start.log"
src_serve_root_dir="/sg/src-serve-root"

# Define log function for consistent output format
function log() {
    echo "$(date '+%Y-%m-%d - %H:%M:%S') - $0 - $1"
}

# Log to both stdout and log file
exec > >(tee -a "$log_file") 2>&1

## Start script execution

# Get the current user's uid and gid, and export it to a shell env var
CURRENT_UID_GID=$(id -u):$(id -g)
export CURRENT_UID_GID=$CURRENT_UID_GID
CURRENT_USER=$(whoami)

log "Script starting"

## Check file permissions in src serve-git directory, shared between repo-converter and src-serve-git containers
log "Running as user: $CURRENT_USER with uid:gid: $CURRENT_UID_GID"


log "Verifying file/dir ownerships in $src_serve_root_dir"

count_of_files_not_owned_by_me=$(find "$src_serve_root_dir" \! -user "$CURRENT_USER" -printf 1 | wc -c)
log "Found $count_of_files_not_owned_by_me files/dirs in $src_serve_root_dir not owned by current user"


# If an f is passed in the args
if [[ "$1" == *"m"* ]]
then

    log "Attempting to take ownership of these files/dirs"
    find "$src_serve_root_dir" \! -user "$CURRENT_USER" -exec chown "$CURRENT_UID_GID" {} \;

fi

log "Verifying file permissions in $src_serve_root_dir"

count_of_files_with_wrong_perms=$(find "$src_serve_root_dir" -type f \! -perm 644 -printf 1 | wc -c)
log "Found $count_of_files_with_wrong_perms files $src_serve_root_dir with incorrect permissions"


# If an f is passed in the args
if [[ "$1" == *"m"* ]]
then

    log "Attempting to fix permissions on these files"
    find "$src_serve_root_dir" -type f \! -perm 644 -exec chmod 644 {} \;

fi

log "Verifying directory permissions in $src_serve_root_dir"

count_of_dirs_with_wrong_perms=$(find "$src_serve_root_dir" -type d \! -perm 755 -printf 1 | wc -c)
log "Found $count_of_dirs_with_wrong_perms directories $src_serve_root_dir with incorrect permissions"


# If an f is passed in the args
if [[ "$1" == *"m"* ]]
then

    log "Attempting to fix permissions on these directories"
    find "$src_serve_root_dir" -type d \! -perm 755 -exec chmod 755 {} \;

fi

## Run Git and Docker commands
log "On branch before git pull: $($git_cmd branch -v)"

log "Docker compose file: $docker_compose_full_file_path"
log "docker ps before:"
$docker_cmd ps

command="\
    $git_cmd reset --hard                                                && \
    $git_cmd pull --force                                                && \
    $docker_cmd pull                                                     && \
    CURRENT_UID_GID=$CURRENT_UID_GID $docker_cmd up -d --remove-orphans     \
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
