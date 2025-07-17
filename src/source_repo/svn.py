#!/usr/bin/env python3
# Convert a Subversion repo to Git

# Import repo-converter modules
from utils.context import Context
from utils.log import log, set_job_result
from utils import cmd, git

# Import Python standard modules
from pathlib import Path
import os
import random
import re
import shutil
import time

# dicts for:
    # ctx, including job subdict, for both configs and logging
    # commands, separate from ctx, as they do not need to be shared / logged
    # Pass information around in these dicts ^, not other return values / dicts / strings / etc.

# Repo states:
    # Exists and is valid / doesn't exist or is invalid
    # Up to date / out of date

# Optimize control flow for:
    # Fewest svn remote commands
    # Easiest reading / maintenance
    # Fewest local commands


def convert(ctx: Context) -> None:
    """
    Entrypoint / main logic / orchestration function
    """

    # Extract repo conversion job config values from the repos list in ctx,
    # and set default values for required but undefined configs
    _extract_repo_config_and_set_default_values(ctx)

    # Build sets of repeatable commands to use each external CLI
    commands = _build_cli_commands(ctx)

    # Check if a repo cloning job is already in progress
    if _check_if_conversion_is_already_running_in_another_process(ctx, commands):
        return

    # Test connection to the SVN server
    ### EXTERNAL COMMAND: svn info ###
    if not _test_connection_and_credentials(ctx, commands):
        return

    # Get revision information from the svn_info output
    # If the svn_info output doesn't include the last changed rev, there's probably a server problem
    if not _get_remote_current_rev_from_svn_info(ctx):
        return

    # Check if the local repo exists and is valid
    # or doesn't exist / is invalid,
    # thus we need to create / recreate it
    if not _check_if_repo_exists_locally(ctx, "start"):

        # If the repo doesn't exist locally, initialize it
        _initialize_git_repo(ctx, commands)

     # Apply git repo configs
    _configure_git_repo(ctx, commands)

    # Update local repo stats in log metadata
    _get_local_git_repo_stats(ctx, "start")

    # Check if the local repo is already up to date
    if _check_if_repo_already_up_to_date(ctx):

        # If the repo already exists, and is already up to date, then exit early
        ### EXTERNAL COMMAND: svn log ###
        _cleanup(ctx, commands)
        log(ctx, "Ending svn repo conversion job; repo up to date", "info")
        return

    ### EXTERNAL COMMAND: svn log ###
    # This is the big one, to count all revs remaining
    # TODO: Separate the svn log range from calculating batch revisions
    _log_number_of_revs_out_of_date(ctx, commands)

    # Calculate revision range for this fetch
    ### EXTERNAL COMMAND: svn log --limit batch-size ###
    if not _calculate_batch_revisions(ctx, commands):
        return

    # Execute the fetch
    ### EXTERNAL COMMAND: git svn fetch ###
    git_svn_fetch_result = _git_svn_fetch(ctx, commands)

    ## Gather information needed to decide if the fetch was successful or failed
    # Cleanup before exit
    _cleanup(ctx, commands)

    ## Decide if the fetch was successful or failed
    ## Also update batch end rev in git repo config file
    _verify_git_svn_fetch_success(ctx, git_svn_fetch_result)

    log(ctx, "Ending svn repo conversion job", "info")


def _extract_repo_config_and_set_default_values(ctx: Context) -> None:
    """
    Extract repo configuration parameters from the Context object and set defaults
    """

    # Get the repo key from the job context
    repo_key = ctx.job.get("config",{}).get("repo_key","")

    # Short name for repo config dict
    repo_config = ctx.repos[repo_key]

    # Get config parameters read from repos-to-clone.yaml, and set defaults if they're not provided
    # TODO: Move this to a centralized config spec file, including setting defaults
    processed_config = {
        "authors_file_path"        : repo_config.get("authors-file-path",        None),
        "authors_prog_path"        : repo_config.get("authors-prog-path",        None),
        "bare_clone"               : repo_config.get("bare-clone",               True),
        "branches"                 : repo_config.get("branches",                 None),
        "code_host_name"           : repo_config.get("code-host-name",           None),
        "destination_git_repo_name": repo_config.get("destination-git-repo-name",None),
        "fetch_batch_size"         : repo_config.get("fetch-batch-size",         100),
        "git_default_branch"       : repo_config.get("git-default-branch",       "trunk"),
        "git_ignore_file_path"     : repo_config.get("git-ignore-file-path",     None),
        "git_org_name"             : repo_config.get("git-org-name",             None),
        "layout"                   : repo_config.get("svn-layout",               None),
        "password"                 : repo_config.get("password",                 None),
        "repo_url"                 : repo_config.get("repo-url",                 None),
        "repo_parent_url"          : repo_config.get("repo-parent-url",          None),
        "source_repo_name"         : repo_config.get("source-repo-name",         None),
        "svn_repo_code_root"       : repo_config.get("svn-repo-code-root",       None),
        "tags"                     : repo_config.get("tags",                     None),
        "trunk"                    : repo_config.get("trunk",                    None),
        "username"                 : repo_config.get("username",                 None)
    }

    # Assemble the full URL to the repo code root path on the remote SVN server
    svn_remote_repo_code_root_url = ""

    if processed_config["repo_url"]:
        svn_remote_repo_code_root_url = f'{processed_config["repo_url"]}'
    elif processed_config["repo_parent_url"]:
        svn_remote_repo_code_root_url = f'{processed_config["repo_parent_url"]}/{processed_config["source_repo_name"]}'

    if processed_config["svn_repo_code_root"]:
        svn_remote_repo_code_root_url += f'/{processed_config["svn_repo_code_root"]}'

    processed_config["svn_remote_repo_code_root_url"] = svn_remote_repo_code_root_url

    # Set local_repo_path
    src_serve_root = ctx.env_vars["SRC_SERVE_ROOT"]
    local_repo_path = f'{src_serve_root}/{processed_config["code_host_name"]}/{processed_config["git_org_name"]}/{processed_config["destination_git_repo_name"]}'
    processed_config["local_repo_path"] = local_repo_path

    # Read env vars into job config
    processed_config["log_recent_commits"]  = ctx.env_vars["LOG_RECENT_COMMITS"]
    processed_config["log_remaining_revs"]  = ctx.env_vars["LOG_REMAINING_REVS"]
    processed_config["max_retries"]         = ctx.env_vars["MAX_RETRIES"]

    # Get last run from local repo

    # Update the repo_config in the context with processed values
    ctx.job["config"].update(processed_config)
    log(ctx, "Repo config", "debug")


def _build_cli_commands(ctx: Context) -> dict:
    """
    Build commands for both SVN and Git CLI tools
    As lists of strings
    """

    # Get config values
    job_config                          = ctx.job.get("config",{})
    branches                            = job_config.get("branches","")
    git_default_branch                  = job_config.get("git_default_branch","")
    layout                              = job_config.get("layout","")
    local_repo_path                     = job_config.get("local_repo_path","")
    password                            = job_config.get("password","")
    svn_remote_repo_code_root_url       = job_config.get("svn_remote_repo_code_root_url","")
    tags                                = job_config.get("tags","")
    trunk                               = job_config.get("trunk","")
    username                            = job_config.get("username","")

    # Common svn command args
    # Also used to convert strings to lists, to concatenate lists
    arg_svn_non_interactive             = ["--non-interactive"]
    arg_svn_remote_repo_code_root_url   = [svn_remote_repo_code_root_url]

    # svn commands
    cmd_svn_info    = ["svn", "info"] + arg_svn_non_interactive + arg_svn_remote_repo_code_root_url
    cmd_svn_log     = ["svn", "log", "--xml", "--with-no-revprops"] + arg_svn_non_interactive + arg_svn_remote_repo_code_root_url

    # Common git command args
    arg_git                                 = ["git", "-C", local_repo_path]
    arg_git_svn                             = arg_git + ["svn"]

    # git commands
    cmd_git_default_branch                  = arg_git     + ["symbolic-ref", "HEAD", f"refs/heads/{git_default_branch}"]
    cmd_git_garbage_collection              = arg_git     + ["gc"]
    cmd_git_svn_fetch                       = arg_git_svn + ["fetch"]
    cmd_git_svn_init                        = arg_git_svn + ["init"] + arg_svn_remote_repo_code_root_url

     # Add authentication, if provided
    if username:
        arg_username        = ["--username", username]
        cmd_svn_info        += arg_username
        cmd_svn_log         += arg_username
        cmd_git_svn_init    += arg_username
        cmd_git_svn_fetch   += arg_username

    if password:
        arg_password        = ["--password", password]
        cmd_svn_info        += arg_password
        cmd_svn_log         += arg_password

    # git svn commands
    if layout:
        cmd_git_svn_init += ["--stdlayout"]
        # Warn the user if they provided an invalid value for the layout
        if layout not in ("standard", "std"):
            log(ctx, f"Layout shortcut provided with incorrect value {layout}, only standard is supported for the shortcut, continuing assuming standard, otherwise provide --trunk, --tags, and --branches", "warning")

    # There can only be one trunk
    if trunk:
        cmd_git_svn_init += ["--trunk", trunk]

    # Tags and branches can either be single strings or lists of strings
    if tags:
        if isinstance(tags, str):
            cmd_git_svn_init += ["--tags", tags]
        if isinstance(tags, list):
            for tag in tags:
                cmd_git_svn_init += ["--tags", tag]

    if branches:
        if isinstance(branches, str):
            cmd_git_svn_init += ["--branches", branches]
        if isinstance(branches, list):
            for branch in branches:
                cmd_git_svn_init += ["--branches", branch]

    return {
        'cmd_git_default_branch':           cmd_git_default_branch,
        'cmd_git_garbage_collection':       cmd_git_garbage_collection,
        'cmd_git_svn_fetch':                cmd_git_svn_fetch,
        'cmd_git_svn_init':                 cmd_git_svn_init,
        'cmd_svn_info':                     cmd_svn_info,
        'cmd_svn_log':                      cmd_svn_log,
    }


def _check_if_conversion_is_already_running_in_another_process(
        ctx: Context,
        commands: dict
    ) -> bool:
    """
    Check if any repo conversion-related processes are currently running in the container

    Return True if yes, to avoid multiple concurrent conversion jobs on the same repo

    TODO: This function may no longer be needed due to the new semaphore handling,
    or this logic could be vastly simplified (ex. _test_connection_and_credentials),
    and moved to the acquire_job_slot function, as it may be applicable to other repo types
    """

    # Get config values
    job_config      = ctx.job.get("config",{})
    local_repo_path = job_config.get("local_repo_path","")
    max_retries     = job_config.get("max_retries","")
    repo_key        = job_config.get("repo_key","")
    repo_type       = job_config.get("repo_type","")

    # Range 1 - max_retries + 1 for human readability in logs
    for i in range(1, max_retries + 1):

        try:

            # Get running processes, both as a list and string
            ps_command                          = ["ps", "--no-headers", "-e", "--format", "pid,args"]
            running_processes_list              = cmd.run_subprocess(ctx, ps_command, quiet=True, name="ps")["output"]
            running_processes_string            = " ".join(running_processes_list)

            # Define the list of strings we're looking for in the running processes' commands
            cmd_git_svn_fetch_string            = " ".join(commands["cmd_git_svn_fetch"])
            cmd_git_garbage_collection_string   = " ".join(commands["cmd_git_garbage_collection"])
            cmd_svn_log_string                  = " ".join(commands["cmd_svn_log"])
            process_name                        = f"convert_{repo_type}_{repo_key}"

            # In priority order
            concurrency_error_strings_and_messages = [
                (cmd_git_svn_fetch_string, "Previous fetching process still"),
                (cmd_git_garbage_collection_string, "Git garbage collection process still"),
                (cmd_svn_log_string, "Previous svn log process still"),
                (process_name, "Previous process still"),
                # Potential problem: if one repo's name is a substring of another repo's name
                (local_repo_path, "Local repo path in process"),
            ]

            log_failure_message = ""

            # Loop through the list of strings we're looking for, to check the running processes for each of them
            for concurrency_error_string_and_message in concurrency_error_strings_and_messages:

                # If this string we're looking for is found
                if concurrency_error_string_and_message[0] in running_processes_string:

                    # Find which process it's in
                    for i in range(len(running_processes_list)):

                        running_process = running_processes_list[i]
                        pid, args = running_process.lstrip().split(" ", 1)

                        # If it's this process, and this process hasn't already matched one of the previous concurrency errors
                        if (
                            concurrency_error_string_and_message[0] in args and
                            pid not in log_failure_message
                        ):

                            # Add its message to the string
                            log_failure_message += f"{concurrency_error_string_and_message[1]} running in pid {pid}; "

                            # Calculate its running time
                            # Quite often, processes will complete when get_pid_uptime() checks them,
                            # if this is the case, then try this check again
                            pid_uptime = cmd.get_pid_uptime(int(pid))
                            if pid_uptime:
                                log_failure_message += f"running for {pid_uptime}; "
                            else:
                                log(ctx, f"pid {pid} with command {args} completed while checking for concurrency collisions, will try checking again", "debug")
                                i -= 1

                            log_failure_message += f"with command: {args}; "

            if log_failure_message:
                set_job_result(ctx, "skipped", log_failure_message, False)
                log(ctx, "Skipping repo conversion job", "info")
                return True
            else:
                # No processes running, can proceed, break out of the max_retries loop
                break

        except Exception as exception:
            log(ctx, f"Failed check {i} of {max_retries} if fetching process is already running. Exception: {type(exception)}: {exception}", "warning")

    return False


def _test_connection_and_credentials(ctx: Context, commands: dict) -> bool:
    """
    Run the svn info command to test:
    - Network connectivity to the SVN server
    - Authentication credentials, if provided

    Capture the output, so we can later extract the current remote rev from it

    The svn info command should be quite lightweight, and return very quickly
    """

    # Get config values
    job_config          = ctx.job.get("config",{})
    max_retries         = job_config.get("max_retries","")
    password            = job_config.get("password","")
    cmd_svn_info        = commands["cmd_svn_info"]
    retries_attempted   = 0

    while True:

        # Run the command, capture the output
        svn_info = cmd.run_subprocess(ctx, cmd_svn_info, password, name=f"svn_info_{retries_attempted}")

        # If the command exited successfully, save the process output dict to the job context
        if svn_info["return_code"] == 0:

            if retries_attempted > 0:
                log(ctx, f"Successfully connected to repo remote after {retries_attempted} retries", "warning")

            ctx.job["svn_info"] = svn_info.get("output","")

            return True

        # If we've hit the max_retries limit, return here
        elif retries_attempted >= max_retries:

            log_failure_message = f"Failed to connect to repo remote, reached max retries {max_retries}"
            set_job_result(ctx, "skipped", log_failure_message, False)
            log(ctx, log_failure_message, "error")

            return False

        # Otherwise, prepare for retry
        else:

            retries_attempted += 1

            # Log the failure
            retry_delay_seconds = random.randrange(1, 5)
            log(ctx, f"Failed to connect to repo remote, retrying {retries_attempted} of max {max_retries} times, with a semi-random delay of {retry_delay_seconds} seconds", "debug")
            time.sleep(retry_delay_seconds)

        # Repeat the loop


def _get_remote_current_rev_from_svn_info(ctx: Context) -> bool:
    """
    Extract revision information from svn info command output
    """

    svn_info = ctx.job.get("svn_info",{})

    # Combine / cast the output lines into a string
    svn_info_output_string = " ".join(svn_info)

    # Get last changed revision for this SVN repo from the svn info output
    if not "Last Changed Rev: " in svn_info_output_string:

        log_failure_message = "Last Changed Rev not found in svn info output"
        set_job_result(ctx, "skipped", log_failure_message, False)
        log(ctx, log_failure_message, "error")
        return False


    remote_current_rev = int(svn_info_output_string.split("Last Changed Rev: ")[1].split(" ")[0])
    ctx.job["stats"]["remote"]["last_changed_revision"] = int(remote_current_rev)

    remote_last_changed_date = svn_info_output_string.split("Last Changed Date: ")[1].split(" ")[0]
    ctx.job["stats"]["remote"]["last_changed_date"] = remote_last_changed_date

    return True


def _check_if_repo_exists_locally(ctx: Context, event: str = None) -> bool:
    """
    Check if the local git repo exists on disk and has the SVN remote URL in its .git/config file
    """

    # Get config values
    job_config                          = ctx.job.get("config",{})
    job_result_action                   = ctx.job.get("result",{}).get("action",{})
    svn_remote_repo_code_root_url       = job_config.get("svn_remote_repo_code_root_url","")

    # Check if the svn-remote.svn.url matches the expected SVN remote repo code root URL
    svn_url_from_local_repo_git_config  = git.get_config(ctx, "svn-remote.svn.url", quiet=True)
    svn_url_from_local_repo_git_config  = " ".join(svn_url_from_local_repo_git_config) if isinstance(svn_url_from_local_repo_git_config, list) else svn_url_from_local_repo_git_config
    svn_remote_repo_code_root_url_in_local_repo_git_config = True if svn_url_from_local_repo_git_config and svn_url_from_local_repo_git_config in svn_remote_repo_code_root_url else False

    if "start" in event:

        if svn_remote_repo_code_root_url_in_local_repo_git_config:

            set_job_result(ctx, "fetching", "valid repo found on disk")
            return True

        else:
            set_job_result(ctx, "creating", "valid repo not found on disk")
            return False

    elif "end" in event:

        if svn_remote_repo_code_root_url_in_local_repo_git_config:
            set_job_result(ctx, f"{job_result_action} succeeded", "valid repo found on disk after fetch")
            return True

        else:
            set_job_result(ctx, f"{job_result_action} failed", "repo not valid after fetch", False)
            return False


def _initialize_git_repo(ctx: Context, commands: dict) -> None:
    """
    Initialize a new Git repository
    """

    # TODO: Move all the arg / command assembly to another function
    # Get config values
    job_config          = ctx.job.get("config",{})
    local_repo_path     = job_config.get("local_repo_path","")
    bare_clone          = job_config.get("bare_clone","")
    password            = job_config.get("password","")
    cmd_git_svn_init    = commands["cmd_git_svn_init"]

    log(ctx, f"Repo not found on disk, initializing new repo", "info")

    # If the directory does exist, then it's not a valid git repo, and needs to be destroyed and recreated
    if os.path.exists(local_repo_path):
        shutil.rmtree(local_repo_path)

    # Created the needed dirs
    os.makedirs(local_repo_path)

    # Initialize the repo
    # TODO: git svn shouldn't need a password to initialize a repo?
    cmd.run_subprocess(ctx, cmd_git_svn_init, password, name="cmd_git_svn_init")

    # Configure the bare clone
    if bare_clone:
        git.set_config(ctx, "core.bare", "true")


def _configure_git_repo(ctx: Context, commands: dict) -> None:
    """
    Configure Git repository settings
    """

    # Get config values
    job_config              = ctx.job.get("config",{})
    authors_file_path       = job_config.get("authors_file_path","")
    authors_prog_path       = job_config.get("authors_prog_path","")
    git_ignore_file_path    = job_config.get("git_ignore_file_path","")
    local_repo_path         = job_config.get("local_repo_path","")

    # Set the default branch local to this repo, after init
    # TODO: Move this to git module
    cmd.run_subprocess(ctx, commands["cmd_git_default_branch"], name="cmd_git_default_branch")

    # Set repo configs, as a list of tuples [(git config key, git config value),]
    git_config_paths = [
        ("svn.authorsfile", authors_file_path),
        ("svn.authorsProg", authors_prog_path),
    ]

    for git_config_key, git_config_value in git_config_paths:

        if git_config_value:

            # Check if these configs are already set the same before trying to set them

            # TODO: Test this
            config_already_set = git.get_config(ctx, git_config_key)
            config_already_set = " ".join(config_already_set) if isinstance(config_already_set, list) else config_already_set
            config_already_set_matches = config_already_set == git_config_value
            path_exists = os.path.exists(git_config_value)

            if path_exists and config_already_set_matches:
                continue
            elif path_exists and not config_already_set_matches:
                git.set_config(ctx, local_repo_path, git_config_key, git_config_value)
            elif not path_exists and config_already_set_matches:
                log(ctx, f"{git_config_key} already set, but file doesn't exist, unsetting it", "warning")
                git.unset_config(ctx, local_repo_path, git_config_key)
            elif not path_exists:
                log(ctx, f"{git_config_key} not found at {git_config_value}, skipping configuring it", "warning")

    # Copy the .gitignore file into place, if provided
    if git_ignore_file_path:
        if os.path.exists(git_ignore_file_path):
            # Always copy, to overwrite if any changes were made
            shutil.copy2(git_ignore_file_path, local_repo_path)
        else:
            log(ctx, f".gitignore file not found at {git_ignore_file_path}, skipping copying it", "warning")


def _get_local_git_repo_stats(ctx: Context, event: str) -> None:
    """
    Functions to collect statistics for local repo

    Called with event "start" and "end"
    """

    # Get config values
    job_config      = ctx.job.get("config",{})
    job_stats_local = ctx.job.get("stats",{}).get("local",{})

    ## dir size
    local_repo_path = job_config.get("local_repo_path","")
    total_size      = 0
    path            = Path(local_repo_path)

    for file in path.glob('**/*'): # '**/*' matches all files and directories recursively
        if file.is_file():
            total_size += file.stat().st_size

    job_stats_local[f"git_repo_dir_size_{event}"] = total_size

    if event == "end":
        git_repo_dir_size_start = job_stats_local.get("git_repo_dir_size_start",0)
        job_stats_local["git_repo_dir_size_diff"] = total_size - git_repo_dir_size_start


    ## Commit count
    commit_count = git.count_commits_in_repo(ctx)
    job_stats_local[f"git_repo_commit_count_{event}"] = commit_count

    ctx.job["stats"]["local"].update(job_stats_local)

    ## Latest commit metadata
    commit_metadata_results = git.get_latest_commit_metadata(ctx)
    log(ctx, f"commit_metadata_results:", "debug", {"process": commit_metadata_results})

    commit_metadata_results_output = list(commit_metadata_results.get("output"))

    # If we got all the results back we need
    if len(commit_metadata_results_output) >= 4:

        # Try to extract the last converted subversion revision from the commit message body
        last_converted_subversion_revision = 0
        for line in commit_metadata_results_output:
            if "git-svn-id" in line:
                last_converted_subversion_revision = int(line.split('@')[1].split()[0])

        ctx.job["stats"]["local"].update(
            {
                f"git_repo_latest_commit_date_{event}": commit_metadata_results_output[0],
                f"git_repo_latest_commit_short_hash_{event}": commit_metadata_results_output[1],
                f"git_repo_latest_commit_message_{event}": commit_metadata_results_output[2],
                f"git_repo_latest_converted_svn_rev_{event}": last_converted_subversion_revision,
            }
        )


def _check_if_repo_already_up_to_date(ctx: Context) -> bool:
    """
    Get the git_repo_latest_converted_svn_rev_start from the local git repo

    Compare it against remote_current_rev from the svn info output
    """

    job_stats = ctx.job.get("stats",{})
    git_repo_latest_converted_svn_rev_start = job_stats.get("local",{}).get("git_repo_latest_converted_svn_rev_start")
    remote_current_rev = job_stats.get("remote",{}).get("last_changed_revision")

    if git_repo_latest_converted_svn_rev_start and remote_current_rev and git_repo_latest_converted_svn_rev_start == remote_current_rev:
        set_job_result(ctx, "skipped", "repo up to date", True)
        return True

    else:
        set_job_result(ctx, "fetching", "repo out of date")
        return False


def _log_recent_commits(ctx: Context, commands: dict) -> None:
    """
    If the repo exists and is already up to date,
    run these steps to cleanup,
    then return
    """

    # Get config values
    job_config          = ctx.job.get("config",{})
    log_recent_commits  = job_config.get("log_recent_commits",0)

    if log_recent_commits > 0:

        # Output the n most recent commits to visually verify the local git repo is up to date with the remote repo
        cmd_svn_log_recent_revs = commands["cmd_svn_log"] + ["--limit", f"{log_recent_commits}"]

        password = job_config.get("password","")

        ctx.job["svn_log_output"] = cmd.run_subprocess(ctx, cmd_svn_log_recent_revs, password, quiet=True, name="svn_log_recent_commits")["output"]

        log(ctx, f"LOG_RECENT_COMMITS={log_recent_commits}", "debug")

        # Remove the svn_log_output from the job context dict, so it doesn't get logged again in subsequent logs
        ctx.job.pop("svn_log_output")


def _cleanup(ctx: Context, commands: dict) -> None:
    """
    Groups up any other functions needed to clean up before exit
    """

    # Get dir size of converted git repo
    _get_local_git_repo_stats(ctx, "end")

    _log_recent_commits(ctx, commands)

    # Run git garbage collection and cleanup branches, even if repo is already up to date
    git.cleanup_branches_and_tags(ctx)
    git.garbage_collection(ctx)


def _log_number_of_revs_out_of_date(ctx: Context, commands: dict) -> None:
    """
    Run the svn log command to count the total number of revs out of date

    TODO: Eliminate this, or make it much more efficient
    Made it optional, enabled by env var, disabled by default
    """

    # Get config values
    job_config          = ctx.job.get("config",{})
    log_remaining_revs  = job_config.get("log_remaining_revs","")

    if log_remaining_revs:

        git_repo_latest_converted_svn_rev_start = ctx.job.get("stats",{}).get("local",{}).get("git_repo_latest_converted_svn_rev_start", 1)
        cmd_svn_log_remaining_revs              = commands["cmd_svn_log"] + ["--revision", f"{git_repo_latest_converted_svn_rev_start}:HEAD"]
        password                                = job_config.get("password","")

        # Parse the output to get the number of remaining revs
        svn_log = cmd.run_subprocess(ctx, cmd_svn_log_remaining_revs, password, name="svn_log_remaining_revs")
        svn_log_output_string = " ".join(svn_log["output"])
        remaining_revs_count = svn_log_output_string.count("revision=")

        # Log the results
        ctx.job["stats"]["remote"]["remaining_revs"] = remaining_revs_count
        log(ctx, "Logging remaining_revs; note: this is an expensive operation", "info")


def _calculate_batch_revisions(ctx: Context, commands: dict) -> bool:
    """
    Run the svn log command to calculate batch start and end revisions for fetching
    """

    # Get config values
    job_config                              = ctx.job.get("config",{})
    fetch_batch_size                        = int(job_config.get("fetch_batch_size", 0))
    password                                = job_config.get("password","")
    cmd_svn_log                             = commands["cmd_svn_log"]
    git_repo_latest_converted_svn_rev_start = int(ctx.job.get("stats",{}).get("local",{}).get("git_repo_latest_converted_svn_rev_start", 0))
    this_batch_end_rev                      = 0
    log_failure_message                     = ""

    # Pick a revision number to start with; may or may not be a real rev number
    this_batch_start_rev    = int(git_repo_latest_converted_svn_rev_start + 1)

    # Run the svn log command to get real revision numbers for this batch
    cmd_svn_log_get_batch_revs  = cmd_svn_log + ["--limit", str(fetch_batch_size), "--revision", f"{this_batch_start_rev}:HEAD"]
    process_result              = cmd.run_subprocess(ctx, cmd_svn_log_get_batch_revs, password, name="cmd_svn_log_get_batch_revs")
    log_details                 = {"process": process_result}
    output_list                 = list(process_result.get("output",""))
    output_string               = " ".join(output_list)
    len_output_list             = len(output_list)
    # Start off as a set type for built-in deduplication
    list_of_revs_this_batch     = set()

    if process_result["return_code"] == 0   and \
        len_output_list > 0                 and \
        "revision" in output_string:

        ## Extract the specific revisions from the svn log output
        # "output": [
        #     "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        #     "<log>",
        #     "<logentry",
        #     "   revision=\"1636921\">",
        #     "</logentry>",
        #     "<logentry",
        #     "   revision=\"1636922\">",
        #     "</logentry>",
        #     "</log>"
        # ],

        for line in output_list:
            if "revision" in line:
                list_of_revs_this_batch.add(int(line.split("revision=\"")[1].split("\"")[0]))

        # Then convert to a list for sorting
        list_of_revs_this_batch = sorted(list_of_revs_this_batch)

        # Update the this batch's starting rev to the first real rev number after the previous end rev
        this_batch_start_rev = min(list_of_revs_this_batch)
        ctx.job["stats"]["local"]["this_batch_start_rev"] = this_batch_start_rev

        # Get the last revision number
        this_batch_end_rev = max(list_of_revs_this_batch)
        ctx.job["stats"]["local"]["this_batch_end_rev"] = this_batch_end_rev

    else:
        log_failure_message = "Failed to get batch revs from svn log"


    ## Count how many revs are in the svn log output
    len_list_of_revs_this_batch = len(list_of_revs_this_batch)
    # Grab the min, in case we are close to the current rev,
    # and there are fewer revs remaining than our current batch size
    fetching_batch_count = min(len_list_of_revs_this_batch, fetch_batch_size)
    # Store it in the job stats dict
    ctx.job["stats"]["local"]["fetching_batch_count"]       = fetching_batch_count
    ctx.job["stats"]["local"]["list_of_revs_this_batch"]    = list_of_revs_this_batch


    # ## Check if the output isn't as long as we were expecting
    # This isn't a valid check, as
    # some repos are smaller than our batch size,
    # and once the repo conversion catches up to the latest rev,
    # there will be fewer commits to convert each run
    # # Expected output number of lines for
    # # svn log --xml --with-no-revprops --non-interactive --limit 10 --revision 1:HEAD
    # # is 3 lines per revision
    # # and 3 lines for xml format start / end
    # expected_output_list_len = (fetch_batch_size * 3) + 3
    # if len_output_list < expected_output_list_len:
    #     log(ctx, f"svn log returned fewer lines: {len_output_list} than expected: {expected_output_list_len}", "warning", log_details)


    if log_failure_message:
        set_job_result(ctx, "skipped", log_failure_message, False)
        log(ctx, log_failure_message, "error", log_details)
        return False

    else:
        set_job_result(ctx, "updating")
        return True


def _git_svn_fetch(ctx: Context, commands: dict) -> dict:
    """
    Execute the git svn fetch operation
    """

    # Get config values
    cmd_git_svn_fetch       = commands["cmd_git_svn_fetch"]
    job_config              = ctx.job.get("config",{})
    job_stats_local         = ctx.job.get("stats",{}).get("local",{})
    password                = job_config.get("password","")
    repo_key                = job_config.get("repo_key","")
    this_batch_end_rev      = job_stats_local.get("this_batch_end_rev","")
    this_batch_start_rev    = job_stats_local.get("this_batch_start_rev","")
    fetching_batch_count    = job_stats_local.get("fetching_batch_count","")

    # If we have batch revisions, use them
    # It should be assumed at this point that we have these revisions
    if this_batch_start_rev and this_batch_end_rev:
        cmd_git_svn_fetch += ["--revision", f"{this_batch_start_rev}:{this_batch_end_rev}"]

    # Try setting the log window size to see if it helps with stability
    if fetching_batch_count:
        cmd_git_svn_fetch += ["--log-window-size", str(fetching_batch_count)]

    log(ctx, f"Repo out of date: {repo_key}; fetching", "info")

    # Delete duplicate lines from the git config file, before the fetch
    git.deduplicate_git_config_file(ctx)

    # Start the fetch
    log(ctx, f'fetching with {" ".join(cmd_git_svn_fetch)}', "debug")


    result = cmd.run_subprocess(ctx, cmd_git_svn_fetch, password, name="cmd_git_svn_fetch")

    # Do not store in ctx.job, because then it gets output to logs
    # ctx.job["git_svn_fetch_result"] = result

    # Return the output of the fetch, to be evaluated for success / fail in another function
    return result


def _verify_git_svn_fetch_success(ctx: Context, git_svn_fetch_result: dict) -> None:
    """
    Check the local repo clone to verify the git svn fetch command completed successfully

    Which signals do we need to base a success / fail decision on?
    - New commits in local git repo (hash_start != hash_end)
    - SVN rev numbers in new commit messages in local git repo

    What actions do we need to take in each case?

    Checks:

        Any success:
            - The repo is correctly formed
                - Has the repo URL in the .git/config file

        Complete success:
            - this_batch_end_rev is included in a git commit body

        Partial success:
            - Does git svn fetch commit converted commits to the local repo in a partial success state?
            - Some commits were synced
            - Some errors were present

    """

    ## Gather needed inputs
    action                          = "git svn fetch"
    errors                          = []
    warnings                        = []
    git_svn_fetch_output_for_errors = list(git_svn_fetch_result.get("output",""))
    git_svn_fetch_output            = list(git_svn_fetch_result.get("output",""))
    job_config                      = ctx.job.get("config","")
    job_stats_local                 = ctx.job.get("stats","").get("local","")
    structured_log_dict             = {"process": git_svn_fetch_result}


    # Check if the repo is valid after the fetch
    if not _check_if_repo_exists_locally(ctx, "end"):
        errors.append("Repo not valid")


    ## Check for any errors in the command output
    # TODO: Test the error message processing

    # Shorten the number of lines in the git svn output,
    # by removing lines which we know are not errors / may be false positives
    not_errors = [
        r"\"\\tA\\t",                   # "\tA\tdir/file.ext",          # Add a new file
        r"\"\\tM\\t",                   # "\tM\tdir/file.ext",          # Modify a file
        r"\"\\tD\\t",                   # "\tD\tdir/file.ext",          # Delete a file
        r"Checked through r[0-9]+",     # "Checked through r123456"     # Many of the lines
        "Ignoring error from SVN",      # "W: Ignoring error from SVN, path probably does not exist: (160013): Filesystem has no item: File not found..."
    ]

    # Remove the not_error lines from the output list
    for not_error in not_errors:
        git_svn_fetch_output_for_errors = [x for x in git_svn_fetch_output_for_errors if not re.search(not_error, x)]

    # Check for expected error messages
    # We should keep this list tidy, as execution time is
    # len(error_messages) x len(git_svn_fetch_result_output)

    # Dicts of lists of regex patterns
    error_message_regex_patterns_dict = {
        "timeout": [
            "Connection timed out",
        ],
        "auth": [
            "Authentication failed",
            "Authorization failed",
            "Invalid credentials",
            "Permission denied",
            "cannot fetch directory .* not authorized",
        ],
        "connectivity": [
            "Can't create session",
            "Unable to connect to a repository at URL",
            "Error running context",
            "Connection refused",
            "SVN connection failed somewhere",
            "Invalid repository URL",
            "SSL handshake failed",
            "Repository not found",
        ],
        "repo config": [
            "SVN repository location required as a command-line argument",
            "Unable to determine upstream SVN information from working tree history",
            "svn-remote .* unknown",
            "svn-remote .* not defined",
            "Failed to read .* in config",
        ],
        "data integrity": [
            "Last fetched revision of .* but we are about to fetch",
            "was not found in commit",
            "Cannot find SVN revision",
            "Checksum mismatch",
            "Failed to read object",
            "Failed to strip path",
        ],
        "local system": [
            "No space left on device",
            "Path not found",
            "Repository is locked",
            "Working copy locked",
            "Couldn't unlink index",
            "Failed to open .* for writing",
            "Failed to close",
        ],
        "other": [
            "Error from SVN",
            "svn: E",
            "Author: .* not defined in .* file",
            "failed with exit code",
            "useSvmProps set, but failed to read SVM properties",
            "useSvnsyncProps set, but failed to read svnsync property",
            "abort:",
            "error:",
            "fatal:",
        ]
    }

    # This loop could take a while, as some svn fetch jobs come back with up to 2k lines
    # Navigate down the dict structure,
    # top few loops are O(n) for the number patterns in error_message_regex_patterns_dict
    for error_category in error_message_regex_patterns_dict.keys():
        for error_message_regex_pattern in error_message_regex_patterns_dict.get(error_category):

            regex_pattern = rf".*{error_message_regex_pattern}.*"
            regex = re.compile(regex_pattern, flags=re.IGNORECASE)

            # We need the line match, but testing the match across the entire list first to reduce the exponential runtime
            list_match = regex.search(" ".join(git_svn_fetch_output_for_errors))

            if list_match:
                for match_group in list_match.groups():
                    for line in git_svn_fetch_output_for_errors:

                        # Re-running the match, as list_match may match across lines,
                        # but we only want to match within each line
                        line_match = regex.search(line)

                        if line_match:

                            errors.append(f"Error message: {error_category}: {line}")

                            # Remove the svn fetch error line from the process output list to avoid duplicate output,
                            # if one line in the error message matches multiple error_messages
                            git_svn_fetch_output_for_errors.remove(line)


    ## Get the latest commit from the git repo's commit logs
    # Update the .git/config file with the ending revision number
    latest_converted_svn_rev = int(job_stats_local.get("git_repo_latest_converted_svn_rev_end", 0))

    # If the ending revision number matches the batch end rev number,
    # then we know we succeeded
    this_batch_end_rev = int(job_stats_local.get("this_batch_end_rev",""))
    if not (latest_converted_svn_rev and this_batch_end_rev and latest_converted_svn_rev == this_batch_end_rev):
        warnings.append(f"git_repo_latest_converted_svn_rev_end: {latest_converted_svn_rev} != this_batch_end_rev: {this_batch_end_rev}")


    ## Get the batch size, and git commits before and after, to check if they add up
    fetching_batch_count        = int(job_stats_local.get("fetching_batch_count", 0))
    git_repo_commit_count_end   = int(job_stats_local.get("git_repo_commit_count_end",   0))
    git_repo_commit_count_start = int(job_stats_local.get("git_repo_commit_count_start", 0))
    git_commits_added           = int(git_repo_commit_count_end - git_repo_commit_count_start)
    git_commits_missed          = int(git_commits_added - fetching_batch_count)

    ctx.job["stats"]["local"].update({"git_commits_added": git_commits_added})
    ctx.job["stats"]["local"].update({"git_commits_missed": git_commits_missed})

    if git_commits_added == 0:
        errors.append(f"git_commits_added == 0, fetch failed to add any new commits")

    elif git_commits_added != fetching_batch_count:
        warnings.append(f"git_commits_added: {git_commits_added} != fetching_batch_count: {fetching_batch_count}; git_commits_missed {git_commits_missed}")


    ## Count how many, and which revs were checked in this fetch
    # Verify each of them are in the git log output
    # TODO: Implement this
    # git_svn_fetch_output


    


    # Assign the lists to the job result data for log output
    ctx.job["result"]["errors"]     = errors
    ctx.job["result"]["warnings"]   = warnings


    ## Make final success / fail call
    if len(errors) > 0:

        reason = "fetch failed with errors"
        set_job_result(ctx, action, reason, False)
        log(ctx, f"git svn fetch incomplete", "error", structured_log_dict)

    elif len(warnings) > 0:

        reason = "fetch passed with warnings"
        set_job_result(ctx, action, reason, True)
        log(ctx, f"git svn fetch incomplete", "error", structured_log_dict)

    else:

        reason = "fetch completed successfully"
        set_job_result(ctx, action, reason, True)
        log(ctx, f"git svn fetch complete", "info", structured_log_dict)
