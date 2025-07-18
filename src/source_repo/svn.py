#!/usr/bin/env python3
# Convert a Subversion repo to Git

# Import repo-converter modules
from utils.context import Context
from utils.log import log, set_job_result
from utils import cmd, git, lockfiles

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
    if not _extract_svn_remote_state_from_svn_info_output(ctx):
        return

    # Check if the local repo exists and is valid
    # or doesn't exist / is invalid,
    # thus we need to create / recreate it
    if not _check_if_repo_exists_locally(ctx, "begin"):

        # If the repo doesn't exist locally, initialize it
        _initialize_git_repo(ctx, commands)

     # Apply git repo configs
    _configure_git_repo(ctx, commands)

    # Update local repo stats in log metadata
    _get_local_git_repo_stats(ctx, "begin")

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
    # _log_number_of_revs_out_of_date(ctx, commands)

    # Calculate revision range for this fetch
    ### EXTERNAL COMMAND: svn log --limit batch-size ###
    # if not _calculate_batch_revisions(ctx, commands):
    #     return

    # Execute the fetch
    ### EXTERNAL COMMAND: git svn fetch ###
    git_svn_fetch_result = _git_svn_fetch(ctx, commands)

    ## Gather information needed to decide if the fetch was successful or failed
    # Cleanup before exit
    _cleanup(ctx, commands)

    ## Decide if the fetch was successful or failed
    ## Also update batch end rev in git repo config file
    # _check_git_svn_fetch_success(ctx, git_svn_fetch_result)

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
        # "fetch_batch_size"         : repo_config.get("fetch-batch-size",         100),
        "fetch_job_timeout"        : repo_config.get("fetch-job-timeout",        600),
        "git_default_branch"       : repo_config.get("git-default-branch",       "trunk"),
        "git_ignore_file_path"     : repo_config.get("git-ignore-file-path",     None),
        "git_org_name"             : repo_config.get("git-org-name",             None),
        "layout"                   : repo_config.get("svn-layout",               None),
        "log-window-size"          : repo_config.get("log-window-size",          100 ),
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
    cmd_git_svn_fetch                       = arg_git_svn + ["fetch", "--quiet", "--quiet"]
    # cmd_git_svn_fetch                       = arg_git_svn + ["fetch", "--no-checkout"]
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

            ctx.job["svn_info"] = svn_info.get("output",[])
            return True

        # If we've hit the max_retries limit, return here
        elif retries_attempted >= max_retries:

            log_failure_message = f"svn info failed to connect to repo remote, reached max retries {max_retries}"
            set_job_result(ctx, "skipped", log_failure_message, False)
            log(ctx, log_failure_message, "error")

            return False

        # Otherwise, prepare for retry
        else:

            retries_attempted += 1

            # Log the failure
            retry_delay_seconds = random.randrange(1, 5)
            log(ctx, f"svn info failed to connect to repo remote, retrying {retries_attempted} of max {max_retries} times, with a semi-random delay of {retry_delay_seconds} seconds", "debug")
            time.sleep(retry_delay_seconds)

        # Repeat the loop


def _extract_svn_remote_state_from_svn_info_output(ctx: Context) -> bool:
    """
    Extract revision information from svn info command output
    """

    cmd_svn_info_output = ctx.job.pop("svn_info",[])
    svn_info_dict       = {}

    for line in cmd_svn_info_output:

        line_split = line.split(': ')

        if len(line_split) > 1:

            key     = line_split[0]
            value   = line_split[1]

            svn_info_dict.update({key: value})

    # Get last changed revision for this SVN repo from the svn info output
    last_changed_rev_key    = "Last Changed Rev"
    last_changed_rev        = int(svn_info_dict.get(last_changed_rev_key))
    ctx.job["stats"]["remote"]["last_changed_revision"] = last_changed_rev

    if not last_changed_rev:

        log_failure_message = f"{last_changed_rev_key} not found in svn info output"
        set_job_result(ctx, "skipped", log_failure_message, False)
        log(ctx, log_failure_message, "error", {"svn_info_dict":svn_info_dict})
        return False

    last_changed_date = svn_info_dict.get("Last Changed Date")
    if last_changed_date:
        ctx.job["stats"]["remote"]["last_changed_date"] = last_changed_date

    repo_revision = svn_info_dict.get("Revision")
    if repo_revision:
        ctx.job["stats"]["remote"]["repo_revision"] = repo_revision

    return True


def _check_if_repo_exists_locally(ctx: Context, event: str = None) -> bool:
    """
    Check if the local git repo exists on disk and has the SVN remote URL in its .git/config file
    """

    # Get config values
    job_config          = ctx.job.get("config",{})
    job_result_action   = ctx.job.get("result",{}).get("action",{})
    remote_url          = job_config.get("svn_remote_repo_code_root_url","")

    # Check if the svn-remote.svn.url matches the expected SVN remote repo code root URL
    local_config_url    = " ".join(git.get_config(ctx, "svn-remote.svn.url", quiet=True))

    # Fail if the `git config --get svn-remote.svn.url` command failed, or if the value is invalid
    urls_match          = True if local_config_url and local_config_url in remote_url else False

    # Update repo stats, to get the last maxrev
    # If there are 0 commits in repo history, then recreate the repo
    _get_local_git_repo_stats(ctx, "begin")
    job_stats_local         = ctx.job.get("stats",{}).get("local",{})
    git_commit_count_begin  = int(job_stats_local.get("git_commit_count_begin", 0))
    has_commits             = True if git_commit_count_begin > 0 else False

    if "begin" in event:

        if urls_match and has_commits:

            set_job_result(ctx, "fetching", "valid repo found on disk, with matching URL, and some commits")
            return True

        else:
            set_job_result(ctx, "creating", "valid repo not found on disk")
            return False

    elif "end" in event:

        if urls_match and has_commits:
            set_job_result(ctx, f"{job_result_action} succeeded", "valid repo found on disk after fetch, with matching URL, and some commits")
            return True

        else:
            set_job_result(ctx, f"{job_result_action} failed", "repo not valid after fetch", False)
            return False


def _initialize_git_repo(ctx: Context, commands: dict) -> None:
    """
    Initialize a new Git repository
    """

    # Get config values
    job_config          = ctx.job.get("config",{})
    local_repo_path     = job_config.get("local_repo_path","")
    bare_clone          = job_config.get("bare_clone","")
    password            = job_config.get("password","")
    cmd_git_svn_init    = commands["cmd_git_svn_init"]

    log(ctx, f"Repo not found on disk, initializing new repo", "info")

    # If the directory does exist, then it failed the validation check, and needs to be destroyed and recreated
    if os.path.exists(local_repo_path):
        shutil.rmtree(local_repo_path)

    # Create the needed dirs
    os.makedirs(local_repo_path)

    # Initialize the repo
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
            config_already_set = " ".join(git.get_config(ctx, git_config_key))
            config_already_set_matches = config_already_set == git_config_value
            path_exists = os.path.exists(git_config_value)

            if path_exists and config_already_set_matches:
                continue
            elif path_exists and not config_already_set_matches:
                git.set_config(ctx, git_config_key, git_config_value)
            elif not path_exists and config_already_set_matches:
                log(ctx, f"{git_config_key} already set, but file doesn't exist, unsetting it", "warning")
                git.unset_config(ctx, git_config_key)
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

    Called with event "begin" and "end"
    """


    # Get config values
    job_config      = ctx.job.get("config",{})
    job_stats_local = ctx.job.get("stats",{}).get("local",{})


    ## dir size
    # TODO: Move to git module
    local_repo_path = job_config.get("local_repo_path","")
    total_size      = 0
    # path            = Path(local_repo_path)

    # for file in path.glob('**/*'): # '**/*' matches all files and directories recursively
    #     if file.is_file():
    #         total_size += file.stat().st_size


    # cmd_du_repo_size = ["du", "-s", local_repo_path]
    # cmd_du_repo_size_result = cmd.run_subprocess(ctx, cmd_du_repo_size, name="cmd_du_repo_size")
    # total_size =

    job_stats_local[f"git_dir_size_{event}"] = total_size

    if event == "end":
        git_dir_size_begin = job_stats_local.get("git_dir_size_begin",0)
        job_stats_local["git_dir_size_added"] = total_size - git_dir_size_begin


    ## Commit count
    git_commit_count = git.count_commits_in_repo(ctx)
    job_stats_local[f"git_commit_count_{event}"] = git_commit_count
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
                f"git_latest_commit_date_{event}": commit_metadata_results_output[0],
                f"git_latest_commit_short_hash_{event}": commit_metadata_results_output[1],
                f"git_latest_commit_message_{event}": commit_metadata_results_output[2],
                f"git_latest_commit_rev_{event}": last_converted_subversion_revision,
            }
        )


    ## Get metadata from previous runs of git svn
    branches_max_rev = 0
    try_branches_max_rev = git.get_config(ctx, key="svn-remote.svn.branches-maxRev", config_file_path=".git/svn/.metadata", quiet=True)

    if try_branches_max_rev:
        branches_max_rev = int(" ".join(try_branches_max_rev))

    ctx.job["stats"]["local"].update(
        {
            f"svn_metadata_branches_max_rev_{event}": branches_max_rev
        }
    )


def _check_if_repo_already_up_to_date(ctx: Context) -> bool:
    """
    Get the git_latest_commit_rev_begin from the local git repo

    Compare it against remote_current_rev from the svn info output
    """

    job_stats = ctx.job.get("stats",{})
    git_latest_commit_rev_begin = job_stats.get("local",{}).get("git_latest_commit_rev_begin")
    last_changed_revision = job_stats.get("remote",{}).get("last_changed_revision")

    if git_latest_commit_rev_begin and last_changed_revision and git_latest_commit_rev_begin == last_changed_revision:
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

    # _log_recent_commits(ctx, commands)

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

        git_latest_commit_rev_begin = ctx.job.get("stats",{}).get("local",{}).get("git_latest_commit_rev_begin", 1)
        cmd_svn_log_remaining_revs              = commands["cmd_svn_log"] + ["--revision", f"{git_latest_commit_rev_begin}:HEAD"]
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
    job_config                  = ctx.job.get("config",{})
    job_stats_local             = ctx.job.get("stats",{}).get("local",{})
    fetch_batch_size            = int(job_config.get("fetch_batch_size", 0))
    password                    = job_config.get("password","")
    cmd_svn_log                 = commands["cmd_svn_log"]
    git_latest_commit_rev_begin = int(job_stats_local.get("git_latest_commit_rev_begin", 0))
    rev_batch_end               = 0
    log_failure_message         = ""

    # Pick a revision number to start with; may or may not be a real rev number
    rev_batch_begin             = int(git_latest_commit_rev_begin + 1)

    # Run the svn log command to get real revision numbers for this batch
    cmd_svn_log_get_batch_revs  = cmd_svn_log + ["--limit", str(fetch_batch_size), "--revision", f"{rev_batch_begin}:HEAD"]
    process_result              = cmd.run_subprocess(ctx, cmd_svn_log_get_batch_revs, password, name="cmd_svn_log_get_batch_revs")
    log_details                 = {"process": process_result}
    output_list                 = list(process_result.get("output",""))
    output_string               = " ".join(output_list)
    len_output_list             = len(output_list)
    # Start off as a set type for built-in deduplication
    rev_list                    = set()

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
                rev_list.add(int(line.split("revision=\"")[1].split("\"")[0]))

        # Then convert to a list for sorting
        rev_list = sorted(rev_list)

        # Update the this batch's starting rev to the first real rev number after the previous end rev
        rev_batch_begin = min(rev_list)
        ctx.job["stats"]["local"]["rev_batch_begin"] = rev_batch_begin

        # Get the last revision number
        rev_batch_end = max(rev_list)
        ctx.job["stats"]["local"]["rev_batch_end"] = rev_batch_end

    else:
        log_failure_message = "Failed to get batch revs from svn log"


    ## Count how many revs are in the svn log output
    len_rev_list = len(rev_list)
    # Grab the min, in case we are close to the current rev,
    # and there are fewer revs remaining than our current batch size
    git_commit_count_to_add = min(len_rev_list, fetch_batch_size)
    # Store it in the job stats dict
    ctx.job["stats"]["local"]["git_commit_count_to_add"]    = git_commit_count_to_add
    ctx.job["stats"]["local"]["rev_list"]               = rev_list


    ## Ensure that this rev range won't cause a problem with branches_max_rev
    branches_max_rev = job_stats_local.get("git_svn_branches_max_rev_begin", 0)

    # if branches_max_rev > rev_batch_begin:
    #     log(ctx, f"git_svn_branches_max_rev_begin {branches_max_rev} > rev_batch_begin {rev_batch_begin}, unsetting svn-remote.svn.branches-maxRev and svn-remote.svn.tags-maxRev to remediate", "warning")
    #     git.set_config(ctx, "svn-remote.svn.branches-maxRev", "0", config_file_path=".git/svn/.metadata")
    #     git.set_config(ctx, "svn-remote.svn.tags-maxRev", "0", config_file_path=".git/svn/.metadata")

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


def _git_svn_fetch(ctx: Context, commands: dict) -> bool:
    """
    Execute the git svn fetch operation
    """

    # Get config values
    cmd_git_svn_fetch       = commands["cmd_git_svn_fetch"]
    job_config              = ctx.job.get("config",{})
    job_stats_local         = ctx.job.get("stats",{}).get("local",{})
    log_window_size         = job_config.get("log-window-size", 100)
    max_retries             = job_config.get("max_retries","")
    password                = job_config.get("password","")
    repo_key                = job_config.get("repo_key","")
    rev_batch_begin         = job_stats_local.get("rev_batch_begin","")
    rev_batch_end           = job_stats_local.get("rev_batch_end","")
    last_changed_revision   = ctx.job.get("stats",{}).get("remote",{}).get("last_changed_revision")

    # If we have batch revisions, use them
    if rev_batch_begin and rev_batch_end:
        cmd_git_svn_fetch += ["--revision", f"{rev_batch_begin}:{rev_batch_end}"]

    log(ctx, f"Repo out of date: {repo_key}; fetching", "info")

    # Do while loop for retries
    retries_attempted = 0
    while True:

        # Delete duplicate lines from the git config file, before the fetch
        git.deduplicate_git_config_file(ctx)

        _get_local_git_repo_stats(ctx, "begin")
        job_stats_local         = ctx.job.get("stats",{}).get("local",{})
        branches_max_rev_begin  = job_stats_local.get("svn_metadata_branches_max_rev_begin")

        if branches_max_rev_begin > last_changed_revision:
            log(ctx, f"branches_max_rev_begin {branches_max_rev_begin} > last_changed_revision {last_changed_revision}, unsetting svn-remote.svn.branches-maxRev and svn-remote.svn.tags-maxRev to remediate", "warning")
            git.set_config(ctx, "svn-remote.svn.branches-maxRev", "0", config_file_path=".git/svn/.metadata")
            git.set_config(ctx, "svn-remote.svn.tags-maxRev", "0", config_file_path=".git/svn/.metadata")

        # Try setting the log window size to see if it helps with stability
        cmd_git_svn_fetch_with_window = cmd_git_svn_fetch + ["--log-window-size", str(log_window_size)]

        # Start the fetch
        log(ctx, f'fetching with {" ".join(cmd_git_svn_fetch_with_window)}', "debug")

        # Run the command, capture the output
        result = cmd.run_subprocess(ctx, cmd_git_svn_fetch_with_window, password, name=f"cmd_git_svn_fetch_{retries_attempted}")
        result.update({"retries_attempted": retries_attempted})

        _get_local_git_repo_stats(ctx, "end")

        ## Check for success or failure conditions
        # Because this function is only called after determining that this repo is out of date,
        # any git svn fetch command which adds zero new commits to the local git repo was a failure,
        # regardless of what the return code says

        # If successful, break the while true loop here
        if _check_git_svn_fetch_success(ctx, result):
            return True

        # If we've hit the max_retries limit, break the while true loop with an error here
        elif retries_attempted >= max_retries:
            return False

        # Otherwise, prepare for retry
        else:

            retries_attempted += 1

            # Divide the log window size in half for the next try
            log_window_size = int(log_window_size) // 2

            # Try clearing the lock file
            lockfiles.clear_lock_files(ctx)

            # Log the failure
            retry_delay_seconds = random.randrange(1, 5)
            log(ctx, f"git svn fetch failed, retrying {retries_attempted} of max {max_retries} times, with a semi-random delay of {retry_delay_seconds} seconds", "debug")
            time.sleep(retry_delay_seconds)

        # Repeat the loop


def _check_git_svn_fetch_success(ctx: Context, git_svn_fetch_result: dict) -> None:
    """
    Check the local repo clone to verify the git svn fetch command completed successfully

    Which signals do we need to base a success / fail decision on?
    - New commits in local git repo (hash_begin != hash_end)
    - SVN rev numbers in new commit messages in local git repo

    What actions do we need to take in each case?

    Checks:

        Any success:
            - The repo is correctly formed
                - Has the repo URL in the .git/config file

        Complete success:
            - rev_batch_end is included in a git commit body

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
    max_retries                     = job_config.get("max_retries","")


    if git_svn_fetch_result["return_code"] != 0:
        errors.append(f"Exited with return_code {git_svn_fetch_result['return_code']} != 0")

    if git_svn_fetch_result["retries_attempted"] >= max_retries:
        errors.append(f"Reached max retries {max_retries}")

    # Check if the repo is valid after the fetch
    if not _check_if_repo_exists_locally(ctx, "end"):
        errors.append("Repo validity check failed")

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


    # ## Get the latest commit from the git repo's commit logs
    # # Update the .git/config file with the ending revision number
    # latest_converted_svn_rev = int(job_stats_local.get("git_latest_commit_rev_end", 0))

    # # If the ending revision number matches the batch end rev number,
    # # then we know we succeeded
    # rev_batch_end = int(job_stats_local.get("rev_batch_end",0))
    # if not (latest_converted_svn_rev and rev_batch_end and latest_converted_svn_rev == rev_batch_end):
    #     warnings.append(f"git_latest_commit_rev_end: {latest_converted_svn_rev} != rev_batch_end: {rev_batch_end}")


    ## Get the batch size, and git commits before and after, to check if they add up
    git_commit_count_end    = int(job_stats_local.get("git_commit_count_end",   0))
    git_commit_count_begin  = int(job_stats_local.get("git_commit_count_begin", 0))
    git_commit_count_added  = int(git_commit_count_end - git_commit_count_begin)
    # git_commit_count_to_add = int(job_stats_local.get("git_commit_count_to_add", 0))
    # git_commit_count_missed = int(git_commit_count_to_add - git_commit_count_added)

    ctx.job["stats"]["local"].update({"git_commit_count_added": git_commit_count_added})
    # ctx.job["stats"]["local"].update({"git_commit_count_missed": git_commit_count_missed})

    if git_commit_count_added == 0:
        errors.append(f"git_commit_count_added == 0, fetch failed to add any new commits")

    # elif git_commit_count_added != git_commit_count_to_add:
    #     warnings.append(f"git_commit_count_added: {git_commit_count_added} != git_commit_count_to_add: {git_commit_count_to_add}; git_commit_count_missed {git_commit_count_missed}")


    ## Count how many, and which revs were checked in this fetch
    # Verify each of them are in the git log output
    # TODO: Implement this
    # git_svn_fetch_output



    # Assign the lists to the job result data for log output
    ctx.job["result"]["errors"]     = errors
    ctx.job["result"]["warnings"]   = warnings


    ## Make final success / fail call
    if len(errors) > 0:

        reason = "git svn fetch failed with errors"
        success = False
        log_level = "error"

    elif len(warnings) > 0:

        reason = "git svn fetch passed with warnings"
        success = True
        log_level = "warning"

    else:

        reason = "git svn fetch completed successfully"
        success = True
        log_level = "info"

    set_job_result(ctx, action, reason, success)
    log(ctx, reason, log_level, structured_log_dict)
