#!/usr/bin/env bash

# Usage: ./sg_maintenance.sh REPOSITORY_ROOT_DIRECTORY [GIT_REPACK_WINDOW_MEMORY]
# Usage: ./sg_maintenance.sh /repos/perforce/repo 10g
# Usage: ./sg_maintenance.sh /repos/github/repo 100m

###############################################################################
# WARNING
# This script was created for Sourcegraph Implementation Engineering deployments
# and is not intended, designed, built, or supported for use in any other scenario.
# Feel free to open issues or PRs, but responses are best effort.
###############################################################################

# Description:
# Custom implementation of sg_maintenance.sh
# For a customer running p4-fusion to convert massive repos from Perforce to Git
# p4-fusion does not duplicate Git CLI functionality, including garbage collection
# Originally written on 2022-08-04, using v3.40 version of sg_maintenance.sh as a base
# https://github.com/sourcegraph/sourcegraph/blob/3.40/cmd/gitserver/server/sg_maintenance.sh
# Retrieved from customer Slack channel on 2024-12-13
# The base sg_maintenance.sh script hasn't changed up to v5.10.2832
# https://github.com/sourcegraph/sourcegraph/blob/v5.10.2832/cmd/gitserver/internal/sg_maintenance.sh
# However, since migrating to Bazel, the script has been built into the gitserver Go binary,
# and is no longer on gitserver's volume to find and execute manually,
# so, customers need to copy this script from here, and paste it into their
# gitserver's sourcegraph user's home directory, at /home/sourcegraph/sg_maintenance.sh

# The customizations are to make the script more ergonomic to execute manually
# for customers who have disabled Git's garbage collection
# 1. This script can be stored in /home/sourcegraph on gitserver's volume,
# and executed from there
# 2. The path to the needed git repo can be passed in as a script parameter,
# ex. ~/sg_maintenance.sh /data/repos/perforce/repo
# 3. Most importantly, this script creates the SG_PAUSE and gc.pid lock files in the repo's directory,
# which should prevent Sourcegraph's background processes from running on the repo while this script is running,
# and git gc

###############################################################################
# sg_maintenance.sh additions start here
###############################################################################

# Configure Bash options
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
# -e Exit if there are any errors
# -u Exit if a variable is referenced before assigned
# -x Print out commands before they are executed
# -o pipefail Include non-zero exit codes, even if a command piped into another command fails
# -o pipefail seems to cause all piping to fail
#set -euxo pipefail
set -eux

# Get the repo's root directory as the first parameter
# Assumes this directory has a .git subdirectory
# Bash string manipulation to set the variable value as empty if no parameters are provided
REPOSITORY_DIRECTORY="${1:-""}"

# Get the git repack window memory as the second parameter
# Bash string manipulation to default the variable value to 100m if second parameter isn't provided
# git repack -d -A --unpack-unreachable=now --write-bitmap-index -l --window-memory 100m
GIT_REPACK_WINDOW_MEMORY="${2:-"100m"}"

# If the directory doesn't exist, or doesn't have a .git subdirectory, exit
if [ ! -d "${REPOSITORY_DIRECTORY}" ] || [ ! -d "${REPOSITORY_DIRECTORY}/.git" ]; then

  # Print usage instructions and exit
  echo "Usage: $(basename "${BASH_SOURCE[0]}") REPOSITORY_ROOT_DIRECTORY [GIT_REPACK_WINDOW_MEMORY]"
  echo "Usage: REPOSITORY_ROOT_DIRECTORY (required) must have a .git subdirectory"
  echo "Usage: GIT_REPACK_WINDOW_MEMORY (optional) should match the format of the git repack --window-memory arg, ex. 100m, 1g"
  exit 1

fi

# cd to the provided repo directory
cd "$REPOSITORY_DIRECTORY"

# Print the sizes of files in the repo's directory
echo "Sizes in the repo's .git directory, before garbage collection:"
du -sc .git/*
start_size="$(du -s .git | awk '{print $1}')"

# Track files to be cleaned up on exit
declare -a files_to_cleanup

# Cleanup function to be run on exit
# This function may fail to remove files, if removing a previous file fails?
function cleanup() {
  for file in "${files_to_cleanup[@]}"; do
    rm "$file" || true
  done
}

# Configure the exit trap to run the cleanup function
trap cleanup EXIT

# Enable noclobber, so output redirection will not overwrite existing files
set -o noclobber

# Create the SG_PAUSE lock file in the repo directory
# to prevent concurrent Sourcegraph cleanup jobs from starting
# With noclobber enabled, this should fail and exit the script if the file already exists,
# i.e. if a Sourcegraph cleanup job is already running
echo "running sg maintenance manually" >SG_PAUSE

# Cleanup the SG_PAUSE file once the script is done
files_to_cleanup+=("SG_PAUSE")

# Create the gc.pid lock file in the repo directory
# to prevent concurrent git garbage collection jobs from starting
# With noclobber enabled, this should fail and exit the script if the file already exists,
# i.e. if a Sourcegraph cleanup job is already running
echo "1 $(hostname)" >.git/gc.pid

# Disable noclobber, so output redirection will overwrite existing files
set +o noclobber

# Test running a concurrent 'git gc', expecting to it fail, to validate that our lock file works as expected
# Exit the script if git gc doesn't fail
if git gc &>/dev/null; then
  echo "expected 'git gc' to fail, but it didn't. Please inspect the .git/gc.pid lockfile to confirm that it contains the correct contents."
  exit 1
fi

# Cleanup the 'git gc' lock file once the script is done
files_to_cleanup+=(".git/gc.pid")

###############################################################################
# sg_maintenance.sh additions mostly end here
# Run sg_maintenance.sh steps from
# https://github.com/sourcegraph/sourcegraph/blob/v5.10.2832/cmd/gitserver/internal/sg_maintenance.sh
# with minor changes, as noted
###############################################################################

#!/usr/bin/env sh
# This script runs several git commands with the goal to optimize the
# performance of git for large repositories.
#
# Relation to git gc and git maintenance:
#
# git-gc
# ------
# The order of commands in this script is based on the order in which git gc
# calls the same commands. The following is a list of commands based on running
# "GIT_TRACE2=1 git gc".
#
# git pack-refs --all --prune
# git reflog expire --all
# git repack -d -l --cruft --cruft-expiration=2.weeks.ago
# -> git pack-objects --local --delta-base-offset .git/objects/pack/.tmp-73874-pack --keep-true-parents --honor-pack-keep --non-empty --all --reflog --indexed-objects
# -> git pack-objects --local --delta-base-offset .git/objects/pack/.tmp-73874-pack --cruft --cruft-expiration=2.weeks.ago --honor-pack-keep --non-empty --max-pack-size=0
# git prune --expire 2.weeks.ago
# git worktree prune --expire 3.months.ago
# git rerere gc
# commit-graph (not traced)
#
# We deviate from git gc like follows:
# - For "git repack" and "git commit-graph write" we choose a different set of
# flags.
# - We omit the commands "git rerere" and "git worktree prune" because they
# don't apply to our use-case.
#
# git-maintenance
# ---------------
# As of git 2.34.1, it is not possible to sufficiently fine-tune the tasks git
# maintenance runs. The tasks are configurable with git config, but not all
# flags are exposed as config parameters. For example, the task
# "incremental-repack" does not allow setting --geometric=2. If future releases
# of git allow us to set more parameters for "git maintenance", we should
# consider switching from this script to "git maintenance".

###############################################################################
# sg_maintenance.sh customization
# set -xe
# Commented out because Bash options were set in earlier additions
###############################################################################

# Usually run by git gc. Pack heads and tags for efficient repository access.
# --all Pack branch tips as well. Useful for a repository with many branches of
# historical interest.
###############################################################################
# Marc's notes from https://git-scm.com/docs/git-pack-refs
# --all to pack all refs (branches, tags, and HEAD)
# There's no arg for --prune, this seems to be the default behaviour
# There is an arg for --no-prune, but that's not what we need
# Marc to test if the --prune arg causes any issues
###############################################################################
git pack-refs --all --prune

# Usually run by git gc. The "expire" subcommand prunes older reflog entries.
# Entries older than expire time, or entries older than expire-unreachable time
# and not reachable from the current tip, are removed from the reflog.
# --all Process the reflogs of all references
###############################################################################
# Comment from Eng:
# We may want to revisit expiring objects immediately
#
# Marc's notes from https://git-scm.com/docs/git-reflog
# Reference logs ("reflogs"), record when the tips of branches and other references
# were updated in the local repository.
# Reflogs are useful in various Git commands, to specify the old value of a reference.
# For example,
#   HEAD@{2} means "where HEAD used to be, two moves ago",
#   master@{one.week.ago} means "where master used to point to, one week ago"
#
# The "expire" subcommand prunes older reflog entries.
# Entries older than expire time, or
# entries older than expire-unreachable time and not reachable from the current tip,
# are removed from the reflog.
#
# --expire=<time>
# Prune entries older than the specified time.
# If this option is not specified, the expiration time is taken from
# the configuration setting gc.reflogExpire,
# which in turn defaults to 90 days.
# --expire=all prunes entries regardless of their age;
# --expire=never turns off pruning of reachable entries
#
# --expire-unreachable=<time>
# Prune entries older than <time> that are not reachable from the current tip of the branch.
# If this option is not specified, the expiration time is taken from
# the configuration setting gc.reflogExpireUnreachable,
# which in turn defaults to 30 days.
# --expire-unreachable=all prunes unreachable entries regardless of their age;
# --expire-unreachable=never turns off early pruning of unreachable entries
#
# We are not specifying --expire <timestamp>, or --expire-unreachable <timestamp>,
# so this command uses the default values,
# or gc.reflogExpire and gc.reflogExpireUnreachable,
# of 90 days and 30 days, respectively.
#
# We may want to print out the values of gc.reflogExpire and gc.reflogExpireUnreachable
# to verify which values are being used
# Continue the script if this command fails
set +e
# Try to get the git config values, if they exist
# If they don't exist, git config returns a non-zero exit code
reflogExpire=$(git config get gc.reflogExpire)
reflogExpireUnreachable=$(git config get gc.reflogExpireUnreachable)
echo "gc.reflogExpire: $reflogExpire"
echo "gc.reflogExpireUnreachable: $reflogExpireUnreachable"
# Revert back to the previous Bash options
set -e
#
# We are specifying --all, so this command processes the reflogs of all references,
# i.e., all branches, tags, and HEAD
###############################################################################
git reflog expire --all

# Usually run by git gc. Here with the additional options:
# --write-bitmap-index
# --window-memory
# We previously set the option --geometric=2, however this turned out to be
# too memory intensive for monorepos on some customer instances.
# Restricting the memory consumption by setting
# pack.windowMemory
# pack.deltaCacheSize
# pack.threads
# in addition to --geometric=2 seemed to have no effect.
###############################################################################
# Marc's notes from https://git-scm.com/docs/git-repack
# combine all objects that do not currently reside in a "pack", into a pack.
# It can also be used to re-organize existing packs into a single, more efficient pack.
# A pack is a collection of objects, individually compressed, with delta compression applied,
# stored in a single file, with an associated index file.
# Packs are used to reduce the load on mirror systems, backup engines, disk storage, etc.
#
# By specifying -d -A --unpack-unreachable=now, we:
# Pack everything into a single pack
#   Any unreachable objects in a previous pack get removed from the pack, and become loose, unpacked objects
#   But don't bother writing them to disk, because unreachable, loose, unpacked objects
#   would just get pruned after this command finishes anyway, as
#   -d calls git prune-packed to remove redundant loose object files
# After packing, REMOVE REDUNDANT PACKS
# And then, run git prune-packed, to remove REDUNDANT LOOSE OBJECT FILES
# But, leave unreachable, loose, unpacked object files which are not redundant
#
# --window-memory should be adjustable depending on the customer's:
#   - Memory available to gitserver
#   - Size of repo
#   - Patience
#
# Will need to test with --path-walk once it becomes available in https://github.com/gitgitgadget/git/pull/1813
###############################################################################
git repack -d -A --unpack-unreachable=now --write-bitmap-index -l --window-memory "$GIT_REPACK_WINDOW_MEMORY"

# --reachable - Generate the new commit graph by walking commits starting at all refs
# --changed-paths - Compute and write information about the paths changed, between a commit and its first parent
# This operation can take a while on large repositories
# It provides significant performance gains for getting history of a directory or a file with git log -- <path>
###############################################################################
# sg_maintenance.sh customizations
# Added
# --progress
# to
# git commit-graph write --reachable --changed-paths
# --progress - Turn progress on explicitly, even if stderr is not connected to a terminal
git commit-graph write --reachable --changed-paths --progress

# Reset Bash option for pipefail, because it seems to break piping git | head
# set +o pipefail

# Test if the repo is corrupted
git show HEAD     | head -n 1
git log           | head -n 1
git ls-tree HEAD  | head -n 1
git log --all     | head -n 1

# Print the sizes of files in the repo's directory
echo "Sizes in the repo's .git directory, after garbage collection:"
du -sc .git/*

# Subtract 4 KB for the lock files which haven't been removed yet
end_size="$(du -s .git | awk '{print $1}')"
end_size="$((end_size - 4))"

echo "Repo $REPOSITORY_DIRECTORY"
echo "Size before garbage collection: $start_size KB"
echo "Size after garbage collection: $end_size KB"
echo "Storage saved: $((start_size - end_size)) KB"
###############################################################################
