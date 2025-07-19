#!/usr/bin/env python3

# Handle repository operations for the resulting Git repos after conversion from other formats

# Import repo-converter modules
from utils import cmd
from utils.context import Context
from utils.log import log

# Import standard libraries
import os

def _get_and_validate_local_repo_path(
        ctx: Context,
        sub_dir: str = "",
        quiet: bool = False
    ) -> str:

    # Get the local repo path
    job_config      = ctx.job.get("config",{})
    local_repo_path = job_config.get("local_repo_path","")

    if not local_repo_path:
        if not quiet:
            log(ctx, f"No local repo path provided to function", "warning")
        return None

    # Validate the repo path exists
    if not os.path.exists(local_repo_path):
        if not quiet:
            log(ctx, f"Path {local_repo_path} provided to function doesn't exist", "warning")
        return None

    # Validate the repo path is a valid git repo
    cmd_git_validate_repo_path = [
        "git",
        "-C",
        local_repo_path,
        "rev-parse",
        "--is-inside-work-tree",
        # "--is-inside-git-dir",
    ]

    valid_repo_path = cmd.run_subprocess(ctx, cmd_git_validate_repo_path, quiet=True, name="cmd_git_validate_repo_path").get("output","")
    if not valid_repo_path:
        if not quiet:
            log(ctx, f"Not a valid repo path: {local_repo_path}", "debug")
        return None
    else:
        # log(ctx, f"Valid repo path: {local_repo_path}", "debug")
        pass

    # If a sub_dir was provided, append it
    if sub_dir:
        local_repo_path += f"/{sub_dir}"

        # Validate the repo path + sub_dir exists
        if not os.path.exists(local_repo_path):
            if not quiet:
                log(ctx, f"Path {local_repo_path} needed for function doesn't exist", "warning")
            return None

    return local_repo_path


def cleanup_branches_and_tags(ctx: Context) -> None:
    """
    git svn, and git tfs, have a bad habit of creating converted branches as remote branches,
    so the Sourcegraph clone doesn't show them to users
    This function converts the remote branches to local branches, so Sourcegraph users can see them

    This function is only called after git svn fetch,
    so if the git config file doesn't exist at this point, big problem
    """

    local_repo_path = _get_and_validate_local_repo_path(ctx)
    packed_refs_file_path = _get_and_validate_local_repo_path(ctx, ".git/packed-refs")
    if not packed_refs_file_path:
        log(ctx, "Repo missing .git/packed-refs", "error")
        return

    # Get the local repo path
    job_config                      = ctx.job.get("config",{})
    git_default_branch              = job_config.get("git_default_branch","")
    cmd_git_repo_set_default_branch = ["git", "-C", local_repo_path, "symbolic-ref", "HEAD", f"refs/heads/{git_default_branch}"]

    local_branch_prefix         = "refs/heads/"
    local_tag_prefix            = "refs/tags/"
    remote_branch_prefix        = "refs/remotes/origin/"
    remote_tag_prefix           = "refs/remotes/origin/tags/"

    remote_branch_exclusions    = [
        "@",
    ]
    remote_tag_exclusions       = [
        "@",
    ]

    # Read the file content as lines into a list
    with open(packed_refs_file_path, "r") as packed_refs_file:
        input_lines = packed_refs_file.read().splitlines()

    output_list_of_strings_and_line_number_tuples = []
    output_list_of_reversed_tuples = []

    for i in range(len(input_lines)):

        try :

            hash, path = input_lines[i].split(" ")

        except ValueError:

            output_list_of_strings_and_line_number_tuples.append([str(input_lines[i]), i])

            continue

        except Exception as exception:

            log(ctx, f"Exception while cleaning branches and tags: {exception}", "error")
            continue

        # If the path is a local tag, then delete it
        if path.startswith(local_tag_prefix):
            continue

        # If the path is a local branch, then delete it
        elif path.startswith(local_branch_prefix):
            continue

        # If the path is the git-svn's default remote branch, then keep it as is, and add a new default local branch
        elif path == "refs/remotes/git-svn":

            output_list_of_reversed_tuples.append(tuple([path,hash]))
            output_list_of_reversed_tuples.append(tuple([f"{local_branch_prefix}{git_default_branch}",hash]))

        # If the path is the default branch, then delete it, it'll get recreated later
        elif path == f"{local_branch_prefix}{git_default_branch}":
            continue

        # If the path is the incorrectly formatted default branch, then delete it
        elif path == f"{local_branch_prefix}/{git_default_branch}":
            continue

        # If the path is a remote tag, then copy it to a local path
        elif path.startswith(remote_tag_prefix):

            output_list_of_reversed_tuples.append(tuple([path,hash]))

            # Filter out the junk
            # If none of the exclusions are in this path, then use it
            filter=(exclusion in path for exclusion in remote_tag_exclusions)
            if not any(filter):

                new_path = path.replace(remote_tag_prefix, local_tag_prefix)
                output_list_of_reversed_tuples.append(tuple([new_path,hash]))

        # If the path is a remote branch, then copy it to a local path
        elif path.startswith(remote_branch_prefix):

            output_list_of_reversed_tuples.append(tuple([path,hash]))

            # Filter out the junk
            # If none of the exclusions are in this path, then use it
            filter=(exclusion in path for exclusion in remote_branch_exclusions)
            if not any(filter):

                new_path = path.replace(remote_branch_prefix, local_branch_prefix)
                output_list_of_reversed_tuples.append(tuple([new_path,hash]))

        else:

            log(ctx, f"Error while cleaning branches and tags, not sure how to handle line {input_lines[i]} in {packed_refs_file_path}", "error")
            output_list_of_strings_and_line_number_tuples.append([str(input_lines[i]), i])

    # Sort by the path in the tuple
    output_list_of_reversed_tuples.sort()

    # Reverse the tuple pairs back to "hash path"
    # Convert the tuples back to strings
    output_list_of_strings = [f"{hash} {path}" for path, hash in output_list_of_reversed_tuples]

    # Re-insert the strings that failed to split, back in their original line number
    for string, line_number in output_list_of_strings_and_line_number_tuples:
        output_list_of_strings.insert(line_number, string)

    # Write the content back to the file
    with open(packed_refs_file_path, "w") as packed_refs_file:
        for line in output_list_of_strings:
            packed_refs_file.write(f"{line}\n")

    # Reset the default branch
    cmd.run_subprocess(ctx, cmd_git_repo_set_default_branch, quiet=True, name="cmd_git_repo_set_default_branch")

def get_count_of_commits_in_repo(ctx: Context) -> int:
    """
    Count and return the total number of commits in the git repo, across all branches
    """

    local_repo_path = _get_and_validate_local_repo_path(ctx)
    if not local_repo_path:
        return

    cmd_git_count_commits = ["git", "-C", local_repo_path, "rev-list", "--all", "--count"]
    cmd_git_count_commits_result = cmd.run_subprocess(ctx, cmd_git_count_commits, quiet=True, name="cmd_git_count_commits", ignore_stderr=True)

    if cmd_git_count_commits_result["return_code"] == 0:

        count_commits = ''.join(cmd_git_count_commits_result["output"]) if isinstance(cmd_git_count_commits_result["output"], list) else cmd_git_count_commits_result["output"]
        return int(count_commits)

    else:
        return None


def deduplicate_git_config_file(ctx: Context) -> None:
    """
    git svn has a bad habit of appending duplicate lines to a git config file
    This function removes the duplicate lines, as a sacrifice to the git gods,
    hoping for a successful fetch

    This function is called before git svn fetch,
    so if the git config file doesn't exist for a new repo, no problem
    however, if the git config file doesn't exist for a repo that's supposed to exist and be updated, big problem
    """

    git_config_file_path = _get_and_validate_local_repo_path(ctx, ".git/config")
    if not git_config_file_path:
        return

    # Use a set to store lines already seen
    # as it deduplicates lines automatically
    # however, don't write the set back to the file,
    # because it's unordered
    lines_seen = set()

    # Open the config file, in read/write mode, so we can overwrite its contents
    with open(git_config_file_path, "r+") as config_file:

        # Read the whole file's contents into memory
        config_file_data = config_file.readlines()

        log(ctx, f"git_config_file lines before: {len(config_file_data)}", "debug")

        # Move the file pointer back to the beginning of the file to start overwriting from there
        config_file.seek(0)

        # Iterate through the lines in their existing order
        for line in config_file_data:

            # If we haven't seen this line before / isn't a duplicate / isn't empty
            if line and (not line.isspace()) and line not in lines_seen:

                # Write it back to the config file
                config_file.write(line)

                # Add it to the set of lines we've seen
                lines_seen.add(line)

        # Delete the rest of the file's contents
        config_file.truncate()

        log(ctx, f"git_config_file lines after: {len(lines_seen)}", "debug")


def garbage_collection(ctx: Context) -> None:
    """
    Garbage collection routine
    """

    local_repo_path = _get_and_validate_local_repo_path(ctx)
    if not local_repo_path:
        return

    cmd_git_garbage_collection = ["git", "-C", local_repo_path, "gc"]
    cmd.run_subprocess(ctx, cmd_git_garbage_collection, quiet=True, name="cmd_git_garbage_collection")


def get_config(ctx: Context, key: str, config_file_path: str = "", quiet: bool=False) -> list:
    """
    A more generic method to get a config value from a repo's config file
    """

    # Validate if the config_file_path exists, but do not use it
    if config_file_path and not _get_and_validate_local_repo_path(ctx, sub_dir=config_file_path, quiet=quiet):
        return

    local_repo_path = _get_and_validate_local_repo_path(ctx, quiet=quiet)
    if not local_repo_path:
        return

    cmd_git_get_config = ["git", "-C", local_repo_path, "config"]

    if config_file_path:
        cmd_git_get_config += ["--file", config_file_path]

    cmd_git_get_config += ["--get", key]

    value = []
    result = cmd.run_subprocess(ctx, cmd_git_get_config, quiet=True, name="cmd_git_get_config")

    if result["return_code"] == 0:

        value = list(result.get("output",""))
        # log(ctx, f"git.get_config succeeded; key: {key}; value: {value}; cmd_git_get_config: {cmd_git_get_config}; result: {value}", "info")

    else:

        # log(ctx, f"git.get_config failed; key: {key}; value: {value}; cmd_git_get_config: {cmd_git_get_config}; result: {value}", "error")
        pass

    return value


def get_latest_commit_metadata(ctx: Context, commit_metadata_field_list: list[str] = None) -> list:
    """
    Get metadata from the most recent commit from the local git repo
    Args:
        commit_metadata_field_list
        See https://git-scm.com/docs/git-for-each-ref#_field_names
    """

    local_repo_path = _get_and_validate_local_repo_path(ctx, quiet=True)
    if not local_repo_path:
        return

    # Set a default value if none is provided
    if not commit_metadata_field_list:
        commit_metadata_field_list = [
            "committerdate:short",
            "objectname:short",
            "contents:subject",
            "contents:body"
        ]

    # Approach 1:
        # Run this command once, with all the metadata fields in one list
        # All of the metadata would come from the same commit,
        # but no assurance that the field has a value,
        # therefore no assurance that the return list matches the input list

    # Approach 2:
        # Run this command in a loop, for each field in the input field list
        # Some assurance that the return list should match the input list
        # But different fields may come back from different commits,
        # if a new commit is committed between executions

    # Approach 3:
        # Switch to GitPython

    # Approach 1:
    commit_metadata_string = ")%0a%(".join(commit_metadata_field_list)
    cmd_git_get_latest_ref = [
        "git", "-C", local_repo_path,
        "for-each-ref", "--count=1", "--sort=-committerdate", f"--format=%({commit_metadata_string})"
    ]

    commit_metadata_return_list = []
    result = cmd.run_subprocess(ctx, cmd_git_get_latest_ref, name="cmd_git_get_latest_ref")

    if result["return_code"] == 0:

        commit_metadata_return_list = list(result.get("output",""))
        # log(ctx, f"git.get_latest_commit_metadata succeeded; result: {commit_metadata_return_list}", "info")

    else:

        # log(ctx, f"git.get_latest_commit_metadata failed; result: {commit_metadata_return_list}", "error")
        pass

    return commit_metadata_return_list

def git_global_config(ctx: Context) -> None:
    """
    Configure global git configs:
        - Trust all directories
        - Default branch = main
    """

    cmd_git_safe_directory = ["git", "config", "--global", "--replace-all", "safe.directory", "\"*\""]
    cmd.run_subprocess(ctx, cmd_git_safe_directory, quiet=True, name="cmd_git_safe_directory")

    cmd_git_default_branch = ["git", "config", "--global", "--replace-all", "init.defaultBranch", "main"]
    cmd.run_subprocess(ctx, cmd_git_default_branch, quiet=True, name="cmd_git_default_branch")


def set_config(ctx: Context, key: str, value: str, config_file_path: str = "") -> bool:
    """
    A more generic method to set a config value in a repo's config file

    Returns True only if the command doesn't fail
    Returns False only if the command failed
    """

    # Validate if the config_file_path exists, but do not use it
    if config_file_path and not _get_and_validate_local_repo_path(ctx, sub_dir=config_file_path):
        return

    local_repo_path = _get_and_validate_local_repo_path(ctx)
    if not local_repo_path:
        return

    cmd_git_set_config = ["git", "-C", local_repo_path, "config"]

    if config_file_path:
        cmd_git_set_config += ["--file", config_file_path]

    cmd_git_set_config += ["--replace-all", key, value]

    result = {
        "empty_dict": "true"
    }

    try:
        result = cmd.run_subprocess(ctx, cmd_git_set_config, quiet=False, name="cmd_git_set_config")
        log(ctx, f"git.set_config succeeded; key: {key}; value: {value}; cmd_git_set_config: {cmd_git_set_config}; result: {result}", "info", result)
        return True
    except:
        log(ctx, f"git.set_config failed; key: {key}; value: {value}; cmd_git_set_config: {cmd_git_set_config}; result: {result}", "error", result)
        return False


def unset_config(ctx: Context, key: str, config_file_path: str = "") -> bool:
    """
    A more generic method to unset a config value from a repo's config file

    Returns True only if the command doesn't fail, not to confirm that the value was in place and removed
    Returns False only if the command failed
    """

    # Validate if the config_file_path exists, but do not use it
    if config_file_path and not _get_and_validate_local_repo_path(ctx, sub_dir=config_file_path):
        return

    local_repo_path = _get_and_validate_local_repo_path(ctx)
    if not local_repo_path:
        return

    cmd_git_unset_config = ["git", "-C", local_repo_path, "config"]

    if config_file_path:
        cmd_git_unset_config += ["--file", config_file_path]

    cmd_git_unset_config += ["--unset", key]

    before = get_config(ctx, key, config_file_path)
    log(ctx, f"git.unset_config before: {before}")

    result = cmd.run_subprocess(ctx, cmd_git_unset_config, quiet=True, name="cmd_git_unset_config")

    after = get_config(ctx, key, config_file_path)
    log(ctx, f"git.unset_config after: {after}")

    if result["return_code"] == 0:
        return True
    else:
        return False