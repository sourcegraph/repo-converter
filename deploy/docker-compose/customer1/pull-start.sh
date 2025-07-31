#!/bin/bash

# To be used in a cronjob to always pull and use the latest image
# so that the running container is only x minutes/hours behind the latest version of
# the docker-compose.yaml file
# and the Docker image tagged latest in GitHub packages

# crontab -e
# */30 * * * * bash /sg/repo-converter/deploy/docker-compose/customer1/pull-start.sh

## Get script args

# If an -f is passed into the script args, then try to fix the ownership and permissions of files in the src-serve-git directory
fix_perms="false"

# If a -dt or --docker-tag is passed in, then use it in the Docker Compose up command for the repo-converter
# DOCKER_TAG="latest"
DOCKER_TAG="stable"

# Create the arg to allow disabling git reset and pull
NO_GIT=""

POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    -f|--fix-perms)
      fix_perms="true"
      shift # past argument
      ;;
    -l|--latest)
      DOCKER_TAG="latest"
      shift # past argument
      ;;
    -s|--stable)
      DOCKER_TAG="stable"
      shift # past argument
      ;;
    -n|--no-git)
      NO_GIT="true"
      shift # past argument
      ;;
    -dt|--docker-tag)
      DOCKER_TAG="$2"
      shift # past argument
      shift # past value
      ;;
    -*|--*)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
done

set -- "${POSITIONAL_ARGS[@]}" # restore positional parameters


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
git_branch_cmd="$git_cmd branch -vv"
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

if [[ "$fix_perms" == "true" ]]
then
    log "Attempting to take ownership of these files/dirs"
    find "$src_serve_root_dir" \! -user "$CURRENT_USER" -exec chown "$CURRENT_UID_GID" {} \;
else
    log "Skipping attempt to take ownership of these files/dirs"
fi


log "Verifying file permissions in $src_serve_root_dir"

count_of_files_with_wrong_perms=$(find "$src_serve_root_dir" -type f \! -perm 644 -printf 1 | wc -c)
log "Found $count_of_files_with_wrong_perms files $src_serve_root_dir with incorrect permissions"

if [[ "$fix_perms" == "true" ]]
then
    log "Attempting to fix permissions on these files"
    find "$src_serve_root_dir" -type f \! -perm 644 -exec chmod 644 {} \;
else
    log "Skipping attempt to fix permissions on these files"
fi


log "Verifying directory permissions in $src_serve_root_dir"

count_of_dirs_with_wrong_perms=$(find "$src_serve_root_dir" -type d \! -perm 755 -printf 1 | wc -c)
log "Found $count_of_dirs_with_wrong_perms directories $src_serve_root_dir with incorrect permissions"

if [[ "$fix_perms" == "true" ]]
then
    log "Attempting to fix permissions on these directories"
    find "$src_serve_root_dir" -type d \! -perm 755 -exec chmod 755 {} \;
else
    log "Skipping attempt to fix permissions on these directories"
fi

## Run Git and Docker commands

log "Pruning remote git branches deleted from remote"
git fetch --prune

# Command from https://stackoverflow.com/a/17029936
branches_to_delete=$(git branch --remotes | awk '{print $1}' | grep -E -v -f /dev/fd/0 <(git branch -vv | grep origin) | awk '{print $1}')
if [[ -n "$branches_to_delete" ]]
then
    log "Pruning local git branches deleted from remote"
    echo "$branches_to_delete" | xargs git branch -D
fi

log "On branch before git pull:"
$git_branch_cmd

log "Docker compose file: $docker_compose_full_file_path"
log "docker ps before:"
$docker_cmd ps



## Formulate Git and Docker commands
git_commands="\
    $git_cmd reset --hard   &&\
    $git_cmd pull --force   &&\
"

if [[ -n "$NO_GIT" ]]
then
    git_commands=""
fi

docker_commands="\
    $docker_cmd pull &&\
    DOCKER_TAG=$DOCKER_TAG CURRENT_UID_GID=$CURRENT_UID_GID $docker_cmd up -d --remove-orphans
"

command="\
    $git_commands       \
    $docker_commands    \
    "


log "Running command in a sub shell:"
# awk command to print the command nicely with newlines
echo "$command" | awk 'BEGIN{FS="&&"; OFS="&& \n"} {$1=$1} 1'

# Run the command
bash -c "$command" >> "$log_file" 2>&1

log "On branch after git pull:"
$git_branch_cmd

log "Sleeping $docker_up_sleep_seconds seconds to give Docker containers time to start and stabilize"
sleep $docker_up_sleep_seconds

log "docker ps after:"
$docker_cmd ps

echo ""
log "Script finishing"
echo ""
