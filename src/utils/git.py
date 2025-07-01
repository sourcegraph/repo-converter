#!/usr/bin/env python3

# Handle repository operations for the resulting Git repos after conversion from other formats

# TODO: Refactor in Object Oriented format?
# from .base import Repo
# class converted_git(Repo):
#     """Class for Git repository operations."""

#     def __init__(self):
#         super().__init__()

#     def gc(self):
#         """Perform a Git garbage collection."""
#         pass

#     def delete(self):
#         """Delete a Git repository once it's no longer in scope."""
#         pass


# Import repo-converter modules
from utils import cmd
from utils.context import Context
from utils.log import log

# Import standard libraries
import os


def cleanup_branches_and_tags(ctx: Context, local_repo_path, cmd_git_default_branch, git_default_branch) -> None:
    """
    git svn, and git tfs, have a bad habit of creating converted branches as remote branches,
    so the Sourcegraph clone doesn't show them to users
    This function converts the remote branches to local branches, so Sourcegraph users can see them

    This function is only called after git svn fetch,
    so if the git config file doesn't exist at this point, big problem
    """

    packed_refs_file_path       = f"{local_repo_path}/.git/packed-refs"

    if not os.path.exists(packed_refs_file_path):
        log(ctx, f"cleanup_branches_and_tags; packed_refs_file_path does not exist: {packed_refs_file_path}", "error")
        return

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
    cmd.subprocess_run(ctx, cmd_git_default_branch)


def deduplicate_git_config_file(ctx: Context, git_config_file_path: str, repo_state: str) -> None:
    """
    git svn has a bad habit of appending duplicate lines to a git config file
    This function removes the duplicate lines, as a sacrifice to the git gods,
    hoping for a successful fetch

    This function is called before git svn fetch,
    so if the git config file doesn't exist for a new repo, no problem
    however, if the git config file doesn't exist for a repo that's supposed to exist and be updated, big problem
    """

    log(ctx, f"deduplicate_git_config_file; git_config_file_path: {git_config_file_path}", "debug")

    if not os.path.exists(git_config_file_path):

        log_level = "debug"
        log_message = f"deduplicate_git_config_file; git_config_file_path does not exist: {git_config_file_path}"

        if repo_state == "update":
            log_level = "error"
            log_message += f"; this is a problem, as repo_state == {repo_state}"

        elif repo_state == "create":
            log_level = "debug"
            log_message += f"; this is not a problem, as repo_state == {repo_state}"

        log(ctx, log_message, log_level)
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

        log(ctx, f"deduplicate_git_config_file; git_config_file lines before: {len(config_file_data)}", "debug")

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

        log(ctx, f"deduplicate_git_config_file; git_config_file lines after: {len(lines_seen)}", "debug")


def get_config(repo, key):
    """
    TODO: Implement as a more generic method to get a config value from a repo's config file
    """

    value = ""
    return value


def git_global_config(ctx: Context) -> None:
    """
    Configure global git configs:
        - Trust all directories
        - Default branch
    """

    cmd_git_safe_directory = ["git", "config", "--global", "--replace-all", "safe.directory", "\"*\""]
    cmd.subprocess_run(ctx, cmd_git_safe_directory)

    cmd_git_default_branch = ["git", "config", "--global", "--replace-all", "init.defaultBranch", "main"]
    cmd.subprocess_run(ctx, cmd_git_default_branch)


def set_config(repo, key, value):
    """
    TODO: Implement as a more generic method to set a config value in a repo's config file
    """
    pass

