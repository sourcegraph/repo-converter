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

    # Set the local repo stats into context for the beginning of the job
    _get_local_git_repo_stats(ctx, "begin")

    # Check if the local repo is already up to date
    if _check_if_repo_up_to_date(ctx):

        # If the repo already exists, and is already up to date, then exit early
        ### EXTERNAL COMMAND: svn log ###
        _cleanup(ctx, commands)
        log(ctx, f"Skipping git svn fetch; repo up to date", "info")
        return

    # Execute the fetch
    ### EXTERNAL COMMAND: git svn fetch ###
    _git_svn_fetch(ctx, commands)

    # Cleanup before exit
    _cleanup(ctx, commands)


def _extract_repo_config_and_set_default_values(ctx: Context) -> None:
    """
    Extract repo configuration parameters from the Context object and set defaults
    """

    # Get the repo key from the job context
    repo_key = ctx.job.get("config",{}).get("repo_key")

    # Short name for repo config dict
    repo_config = ctx.repos.get(repo_key)

    # Get config parameters read from repos-to-clone.yaml, and set defaults if they're not provided
    # TODO: Move this to a centralized config spec file, including setting defaults
    processed_config = {
        "authors_file_path"        : repo_config.get("authors-file-path",        None),
        "authors_prog_path"        : repo_config.get("authors-prog-path",        None),
        "bare_clone"               : repo_config.get("bare-clone",               True),
        "branches"                 : repo_config.get("branches",                 None),
        "code_host_name"           : repo_config.get("code-host-name",           None),
        "destination_git_repo_name": repo_config.get("destination-git-repo-name",None),
        "disable_tls_verification" : repo_config.get("disable-tls-verification", False),
        # "fetch_batch_size"         : repo_config.get("fetch-batch-size",         100),
        # "fetch_job_timeout"        : repo_config.get("fetch-job-timeout",        600),
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
    # processed_config["log_recent_commits"]  = ctx.env_vars["LOG_RECENT_COMMITS"]
    # processed_config["log_remaining_revs"]  = ctx.env_vars["LOG_REMAINING_REVS"]
    processed_config["max_retries"]         = ctx.env_vars["MAX_RETRIES"]

    # Get last run from local repo

    # Update the repo_config in the context with processed values
    ctx.job["config"].update(processed_config)
    # log(ctx, f"Repo config", "debug")


def _build_cli_commands(ctx: Context) -> dict:
    """
    Build commands for both SVN and Git CLI tools
    As lists of strings
    """

    # Get config values
    job_config                          = ctx.job.get("config",{})
    branches                            = job_config.get("branches")
    git_default_branch                  = job_config.get("git_default_branch")
    layout                              = job_config.get("layout")
    local_repo_path                     = job_config.get("local_repo_path")
    password                            = job_config.get("password")
    repo_key                            = job_config.get("repo_key")
    svn_remote_repo_code_root_url       = job_config.get("svn_remote_repo_code_root_url")
    tags                                = job_config.get("tags")
    trunk                               = job_config.get("trunk")
    username                            = job_config.get("username")

    # Common svn command args
    # Also used to convert strings to lists, to concatenate lists
    arg_svn_non_interactive             = ["--non-interactive"]
    arg_svn_remote_repo_code_root_url   = [svn_remote_repo_code_root_url]

    # svn commands
    cmd_svn_info    = ["svn", "info"] + arg_svn_non_interactive + arg_svn_remote_repo_code_root_url
    cmd_svn_log     = ["svn", "log", "--xml", "--with-no-revprops"] + arg_svn_non_interactive + arg_svn_remote_repo_code_root_url


    # Common git command args
    arg_git                                 = ["git", "-C", local_repo_path]

    if job_config.get("disable_tls_verification"):
        arg_git   += ["-c", "http.sslVerify=false"]

    arg_git_svn                             = arg_git + ["svn"]

    # git commands
    cmd_git_default_branch                  = arg_git     + ["symbolic-ref", "HEAD", f"refs/heads/{git_default_branch}"]
    cmd_git_garbage_collection              = arg_git     + ["gc"]
    cmd_git_svn_fetch                       = arg_git_svn + ["fetch", "--quiet"]
    cmd_git_svn_init                        = arg_git_svn + ["init"] + arg_svn_remote_repo_code_root_url

    # Skip TLS verification, if needed
    if job_config.get("disable_tls_verification"):
        cmd_svn_info        += ["--trust-server-cert"]
        cmd_svn_log         += ["--trust-server-cert"]

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
    local_repo_path = job_config.get("local_repo_path")
    max_retries     = job_config.get("max_retries")
    repo_key        = job_config.get("repo_key")
    repo_type       = job_config.get("repo_type")

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
                log(ctx, f"Skipping repo conversion job", "info")
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
    max_retries         = job_config.get("max_retries")
    password            = job_config.get("password")
    repo_key            = job_config.get("repo_key")
    cmd_svn_info        = commands["cmd_svn_info"]
    tries_attempted     = 1

    while True:

        # Run the command, capture the output
        svn_info = cmd.run_subprocess(ctx, cmd_svn_info, password, quiet=True, name=f"svn_info_{tries_attempted}")

        # If the command exited successfully, save the process output dict to the job context
        if svn_info["return_code"] == 0:

            if tries_attempted > 1:
                log(ctx, f"Successfully connected to repo remote after {tries_attempted} tries", "warning")

            ctx.job["svn_info"] = svn_info.get("output",[])
            return True

        # If we've hit the max_retries limit, return here
        elif tries_attempted >= max_retries:

            log_failure_message = f"svn info failed to connect to repo remote, reached max retries {max_retries}"
            set_job_result(ctx, "skipped", log_failure_message, False)
            log(ctx, f"{log_failure_message}", "error", {"process": svn_info})

            return False

        # Otherwise, prepare for retry
        else:

            tries_attempted += 1

            # Log the failure
            retry_delay_seconds = random.randrange(1, 5)
            log(ctx, f"svn info failed to connect to repo remote, retrying {tries_attempted} of max {max_retries} times, with a semi-random delay of {retry_delay_seconds} seconds", "debug", {"process": svn_info})
            time.sleep(retry_delay_seconds)

        # Repeat the loop


def _extract_svn_remote_state_from_svn_info_output(ctx: Context) -> bool:
    """
    Extract revision information from svn info command output
    """

    repo_key = ctx.job.get("config",{}).get("repo_key")

    cmd_svn_info_output = ctx.job.pop("svn_info",[])
    svn_info_dict       = {}

    for line in cmd_svn_info_output:

        if "E200009" in line:
            log_failure_message = f"Repo not found on svn server"
            set_job_result(ctx, "skipped", log_failure_message, False)
            log(ctx, f"{log_failure_message}", "error", {"cmd_svn_info_output":cmd_svn_info_output})
            return False

        line_split = line.split(': ')

        if len(line_split) > 1:

            key     = line_split[0]
            value   = line_split[1]

            svn_info_dict.update({key: value})

    # Get last changed revision for this SVN repo from the svn info output
    last_changed_rev_key    = "Last Changed Rev"
    last_changed_rev        = svn_info_dict.get(last_changed_rev_key)

    try:
        last_changed_rev = int(last_changed_rev)
    except:
        last_changed_rev = None

    if not last_changed_rev:

        log_failure_message = f"{last_changed_rev_key} not found in svn info output"
        set_job_result(ctx, "skipped", log_failure_message, False)
        log(ctx, f"{log_failure_message}", "error", {"cmd_svn_info_output":cmd_svn_info_output})
        return False

    ctx.job["stats"]["remote"]["last_changed_revision"] = int(last_changed_rev)

    last_changed_date = svn_info_dict.get("Last Changed Date")
    if last_changed_date:
        ctx.job["stats"]["remote"]["last_changed_date"] = last_changed_date

    repo_revision = svn_info_dict.get("Revision")
    if repo_revision:
        ctx.job["stats"]["remote"]["repo_revision"] = repo_revision

    return True


def _check_if_repo_exists_locally(ctx: Context, event: str = "") -> bool:
    """
    Check if the local git repo exists on disk and has the SVN remote URL in its .git/config file
    """

    # Get config values
    job_config          = ctx.job.get("config",{})
    job_result_action   = ctx.job.get("result",{}).get("action",{})
    remote_url          = job_config.get("svn_remote_repo_code_root_url")
    repo_key            = job_config.get("repo_key")

    # Check if the svn-remote.svn.url matches the expected SVN remote repo code root URL
    local_config_url    = git.get_config(ctx, "svn-remote.svn.url", quiet=True)

    # Convert to a string
    if isinstance(local_config_url, list):
        local_config_url    = " ".join(local_config_url)

    # Fail if the `git config --get svn-remote.svn.url` command failed, or if the value is invalid
    urls_match = False
    if local_config_url and local_config_url in remote_url:
        urls_match = True

    # If there are 0 commits in repo history, then recreate the repo
    # For conversion jobs where the svn repo subdir only has commits near the end of a long repo history,
    # deleting the repo for not having any commits does unblock the repo from past issues,
    # but also causes this job to start from rev 1 again, which can take a long time
    has_commits = False
    git_commit_count = 0
    if urls_match:
        job_stats_local     = _get_local_git_repo_stats(ctx)
        git_commit_count    = job_stats_local.get("git_commit_count")
        if isinstance(git_commit_count, int) and git_commit_count > 0:
            has_commits     = True

    if "begin" in event:

        if urls_match and has_commits:

            set_job_result(ctx, "fetching", "valid repo found on disk, with matching URL, and some commits")
            return True

        else:
            set_job_result(ctx, "creating", "valid repo not found on disk")

    elif "end" in event:

        if urls_match and has_commits:
            set_job_result(ctx, f"{job_result_action} succeeded", "valid repo found on disk after fetch, with matching URL, and some commits")
            return True

        else:
            set_job_result(ctx, f"{job_result_action} failed", "repo not valid after fetch", False)

    else:
        if urls_match and has_commits:
            return True

    return False


def _initialize_git_repo(ctx: Context, commands: dict) -> None:
    """
    Initialize a new Git repository
    """

    # Get config values
    job_config          = ctx.job.get("config",{})
    local_repo_path     = job_config.get("local_repo_path")
    bare_clone          = job_config.get("bare_clone")
    password            = job_config.get("password")
    repo_key            = job_config.get("repo_key")
    cmd_git_svn_init    = commands["cmd_git_svn_init"]

    # If the directory does exist, then it failed the validation check, and needs to be destroyed and recreated
    if os.path.exists(local_repo_path):
        log(ctx, f"Repo path {local_repo_path} exists on disk, but is not a valid repo; deleting", "warning")

        # OSError: [Errno 23] Too many open files in system: '079426a942f0583e6906f1f2fd31e703ce366d'
        # shutil.rmtree(local_repo_path)

        cmd_rm_rf = ["rm", "-rf", local_repo_path]
        cmd.run_subprocess(ctx, cmd_rm_rf, name=f"cmd_rm_rf")

    else:
        log(ctx, f"Repo not found on disk, initializing new repo", "info")

    # Create the needed dirs
    os.makedirs(local_repo_path)

    # Initialize the repo
    cmd.run_subprocess(ctx, cmd_git_svn_init, password, quiet=True, name="cmd_git_svn_init")

    # Configure the bare clone
    if bare_clone:
        git.set_config(ctx, "core.bare", "true")


def _configure_git_repo(ctx: Context, commands: dict) -> None:
    """
    Configure Git repository settings
    """

    # Get config values
    job_config              = ctx.job.get("config",{})
    authors_file_path       = job_config.get("authors_file_path")
    authors_prog_path       = job_config.get("authors_prog_path")
    git_ignore_file_path    = job_config.get("git_ignore_file_path")
    local_repo_path         = job_config.get("local_repo_path")
    repo_key                = job_config.get("repo_key")

    # Set the default branch local to this repo, after init
    # TODO: Move to git module
    cmd.run_subprocess(ctx, commands["cmd_git_default_branch"], quiet=True, name="cmd_git_default_branch")

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


def _get_local_git_repo_stats(ctx: Context, event: str = "") -> dict:
    """
    Functions to collect statistics for local repo

    This function gets called as part of checking if the repo exists on disk,
    so it needs sufficient bubble wrap to handle errors
    """

    # Get config values
    job_config      = ctx.job.get("config",{})
    job_stats_local = ctx.job.get("stats",{}).get("local",{})

    # Define return dict
    return_dict     = {}

    # Add a leading underscore for formatting
    if event:
        event = f"_{event}"

    ## dir size
    # TODO: Move to git module
    local_repo_path = job_config.get("local_repo_path")
    git_dir_size      = 0

    # Python approach
    # path            = Path(local_repo_path)
    # for file in path.glob('**/*'): # '**/*' matches all files and directories recursively
    #     if file.is_file():
    #         git_dir_size += file.stat().st_size

    # du approach
    cmd_du_repo_size                = ["du", "-s", local_repo_path]
    cmd_du_repo_size_result         = cmd.run_subprocess(ctx, cmd_du_repo_size, quiet=True, name="cmd_du_repo_size", ignore_stderr=True)
    cmd_du_repo_size_return_code    = cmd_du_repo_size_result.get("return_code")
    cmd_du_repo_size_output         = cmd_du_repo_size_result.get("output")
    len_cmd_du_repo_size_output     = len(cmd_du_repo_size_output)

    if (
        cmd_du_repo_size_return_code == 0 and
        len_cmd_du_repo_size_output > 0
    ):

        git_dir_size = " ".join(cmd_du_repo_size_result.get("output", []))
        git_dir_size = int(git_dir_size.split()[0])

        if git_dir_size:
            return_dict.update(
                {
                    f"git_dir_size{event}": git_dir_size
                }
            )

            if event == "end":
                # Not defaulting to 0, as that'd only hide a coding problem we'd need to fix
                git_dir_size_begin = job_stats_local.get("git_dir_size_begin")
                return_dict.update(
                    {
                        "git_dir_size_added": (git_dir_size - git_dir_size_begin)
                    }
                )

    ## Commit count
    git_commit_count = git.get_count_of_commits_in_repo(ctx)
    return_dict.update(
        {
            f"git_commit_count{event}": git_commit_count
        }
    )

    ## Latest commit metadata
    latest_commit_metadata = list(git.get_latest_commit_metadata(ctx))

    # If we got all the results back we need
    if len(latest_commit_metadata) >= 4:

        # Try to extract the last converted subversion revision from the commit message body
        last_converted_subversion_revision = 0
        for line in reversed(latest_commit_metadata):
            if "git-svn-id" in line:
                last_converted_subversion_revision = int(line.split('@')[1].split()[0])

        return_dict.update(
            {
                f"git_latest_commit_date{event}": latest_commit_metadata[0],
                f"git_latest_commit_short_hash{event}": latest_commit_metadata[1],
                f"git_latest_commit_message{event}": latest_commit_metadata[2],
                f"git_latest_commit_rev{event}": last_converted_subversion_revision,
            }
        )

    ## Get metadata from previous runs of git svn
    try_branches_max_rev = git.get_config(ctx, key="svn-remote.svn.branches-maxRev", config_file_path=".git/svn/.metadata", quiet=True)

    if try_branches_max_rev:

        try:

            branches_max_rev = int(" ".join(try_branches_max_rev))

            return_dict.update(
                {
                    f"svn_metadata_branches_max_rev{event}": branches_max_rev
                }
            )

        except ValueError:
            pass

    if event:
        ctx.job["stats"]["local"].update(return_dict)

    return return_dict


def _check_if_repo_up_to_date(ctx: Context, event: str = "") -> bool:
    """
    Get the git_latest_commit_rev_begin from the local git repo

    Compare it against remote_current_rev from the svn info output
    """

    job_stats                   = ctx.job.get("stats",{})
    git_latest_commit_rev_begin = job_stats.get("local", {}).get("git_latest_commit_rev_begin")
    last_changed_revision       = job_stats.get("remote",{}).get("last_changed_revision")

    if (
        git_latest_commit_rev_begin and
        last_changed_revision       and
        git_latest_commit_rev_begin == last_changed_revision
    ):
        set_job_result(ctx, "skipped", "repo up to date", True)
        return True

    else:
        set_job_result(ctx, "fetching", "repo out of date")
        return False


def _cleanup(ctx: Context, commands: dict) -> None:
    """
    Groups up any other functions needed to clean up before exit
    """

    # Get dir size of converted git repo
    _get_local_git_repo_stats(ctx, "end")

    # _log_recent_commits(ctx, commands)

    # Run git garbage collection and cleanup branches, even if repo is already up to date
    # Order is important, garbage_collection must run before cleanup_branches_and_tags
    git.garbage_collection(ctx)
    git.cleanup_branches_and_tags(ctx)


def _git_svn_fetch(ctx: Context, commands: dict) -> bool:
    """
    Execute the git svn fetch operation
    """

    log(ctx, f"Repo out of date, fetching", "info")

    # Do while loop for retries
    tries_attempted         = 1
    while True:

        # Get config values
        cmd_git_svn_fetch       = commands["cmd_git_svn_fetch"]
        job_config              = ctx.job.get("config", {})
        log_window_size         = job_config.get("log-window-size", 100)
        max_retries             = job_config.get("max_retries")
        password                = job_config.get("password")

        # Reset result values
        ctx.job["result"].update(
            {
                "action":   "git svn fetch",
                "errors":   [],
                "reason":   "",
                "success":  "",
                "try":      tries_attempted,
                "warnings":  [],
            }
        )

        # Delete duplicate lines from the git config file, before the fetch
        git.deduplicate_git_config_file(ctx)

        # Try setting the log window size to see if it helps with network timeout stability
        cmd_git_svn_fetch_with_window = cmd_git_svn_fetch + ["--log-window-size", str(log_window_size)]

        # Start the fetch
        log(ctx, f"fetching with {' '.join(cmd_git_svn_fetch_with_window)}", "debug")

        # Run the fetch command, capture the output
        git_svn_fetch_result = cmd.run_subprocess(ctx, cmd_git_svn_fetch_with_window, password, name=f"cmd_git_svn_fetch_{tries_attempted}")
        git_svn_fetch_result.update({"tries_attempted": tries_attempted})

        # Run gc + fix branches, after each try, to:
        # Make branches visible
        # Update the HEAD ref to the latest commit on the default branch
        git.garbage_collection(ctx)
        git.cleanup_branches_and_tags(ctx)

        # If successful, break the while true loop here
        if _check_git_svn_fetch_success(ctx, git_svn_fetch_result):
            return True

        # If we've hit the max_retries limit, break the while true loop with an error here
        elif tries_attempted >= max_retries:
            return False

        # Otherwise, prepare for retry
        else:

            tries_attempted += 1

            # Divide the log window size in half for the next try
            ctx.job["config"].update(
                {
                    "log-window-size": int(log_window_size) // 2
                }
            )

            # Try clearing lock files,
            # in case that was the cause of the failure,
            # or lock files may have been left behind by the failed try
            lockfiles.clear_lock_files(ctx)

            # Calculate a semi-random number of seconds to wait before trying
            # Multiply by number of retries attempted, for a bit of a backoff,
            # in case the server is busy
            retry_delay_seconds = (random.randrange(1, 5) * tries_attempted)

            # Log the failure
            log(ctx, f"retrying {tries_attempted} of max {max_retries} times, with a semi-random delay of {retry_delay_seconds} seconds", "debug")

            # Sleep the delay
            time.sleep(retry_delay_seconds)

        # Repeat the retry loop


def _check_git_svn_fetch_success(ctx: Context, git_svn_fetch_result: dict) -> bool:
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
    job_config                      = ctx.job.get("config",{})
    max_retries                     = job_config.get("max_retries")
    repo_key                        = job_config.get("repo_key")

    git_svn_fetch_output            = git_svn_fetch_result.pop("output",[])
    return_code                     = git_svn_fetch_result.get("return_code")
    tries_attempted                 = git_svn_fetch_result.get("tries_attempted")

    ## Prepare outputs
    errors                          = []
    warnings                        = []


    ## Basic checks
    if return_code != 0:
        errors.append(f"Exited with return_code {return_code} != 0")

    if tries_attempted >= max_retries:
        errors.append(f"Reached max retries {max_retries}")

    # Check if the repo is valid after the fetch
    if not _check_if_repo_exists_locally(ctx):
        errors.append("Repo validity check _check_if_repo_exists_locally failed")


    # Filter out the non-error lines from the process output
    git_svn_fetch_output = _remove_non_errors_from_git_svn_fetch_output(ctx, git_svn_fetch_output)

    # Search the remaining lines of the process output for known errors
    errors_from_output = _find_errors_in_git_svn_fetch_output(ctx, git_svn_fetch_output)
    if errors_from_output:
        errors += errors_from_output


    ## Commit count checks
    current_job_stats_local_git_repo_stats  = _get_local_git_repo_stats(ctx)
    job_stats_local                         = ctx.job.get("stats",{}).get("local",{})

    # Get the number of commits which were already in the local git repo before the job started
    git_commit_count_begin                  = job_stats_local.get("git_commit_count_begin", 0)
    if not git_commit_count_begin:
        git_commit_count_begin = 0

    # Get the current number of commits in the local git repo after this fetch attempt (includes all retries)
    current_git_commit_count                = current_job_stats_local_git_repo_stats.get("git_commit_count", 0)
    if not current_git_commit_count:
        current_git_commit_count = 0



    ## This try commit counts
    # Order is important, must be before ## Whole job commit counts,
    # because this tries to use the git_commit_count_added_whole_job from the previous retry
    # Get the count of commits from the end of the previous try
    git_commit_count_added_whole_job = job_stats_local.get("git_commit_count_added_whole_job", 0)
    git_commit_count_after_previous_try = 0

    if git_commit_count_added_whole_job and isinstance(git_commit_count_added_whole_job, int):
        git_commit_count_after_previous_try += git_commit_count_added_whole_job

    if git_commit_count_begin and isinstance(git_commit_count_begin, int):
        git_commit_count_after_previous_try += git_commit_count_begin


    # Calculate the number of commits added since the previous try
    git_commit_count_added_this_try = 0

    if current_git_commit_count and isinstance(current_git_commit_count, int):
        git_commit_count_added_this_try = current_git_commit_count - git_commit_count_after_previous_try

    # Store the number of commits from this try
    ctx.job["stats"]["local"].update({f"git_commit_count_added_try_{tries_attempted}": git_commit_count_added_this_try})
    # If no commits were added on this try, add this to the list of errors
    if git_commit_count_added_this_try == 0:
        errors.append(f"git_commit_count_added_this_try == 0, the fetch in this try failed to add any new commits")


    ## Whole job commit counts
    # Order is important, must be after ## This try commit counts
    # Calculate the number of commits added since the beginning of the job (includes all retries)
    git_commit_count_added_whole_job = 0
    git_commit_count_added_whole_job    = int(current_git_commit_count) - int(git_commit_count_begin)
    # Update the number of commits added since the beginning of the job (includes all retries)
    ctx.job["stats"]["local"].update({"git_commit_count_added_whole_job": git_commit_count_added_whole_job})
    # If no commits have been added the whole job, add this to the list of errors
    if git_commit_count_added_whole_job == 0:
        errors.append(f"git_commit_count_added_whole_job == 0, all fetches in this job so far have failed to add any new commits")


    ## Add git_dir_size
    # Same logic as commit counts

    # Get the number of commits which were already in the local git repo before the job started
    current_git_dir_size                = current_job_stats_local_git_repo_stats.get("git_dir_size",0)
    git_dir_size_begin                  = int(job_stats_local.get("git_dir_size_begin",0))
    git_dir_size_after_previous_try     = int(job_stats_local.get("git_dir_size_added_whole_job", 0)) + int(git_dir_size_begin)

    git_dir_size_added_this_try         = int(current_git_dir_size) - int(git_dir_size_after_previous_try)
    ctx.job["stats"]["local"].update({f"git_dir_size_added_try_{tries_attempted}": git_dir_size_added_this_try})

    git_dir_size_added_whole_job        = int(current_git_dir_size) - int(git_dir_size_begin)
    ctx.job["stats"]["local"].update({"git_dir_size_added_whole_job": git_dir_size_added_whole_job})


    # Check if git svn has blown past svn info's "Last Changed Rev"
    branches_max_rev            = current_job_stats_local_git_repo_stats.get("svn_metadata_branches_max_rev", 0)
    last_changed_revision       = ctx.job.get("stats",{}).get("remote",{}).get("last_changed_revision")
    git_latest_commit_rev       = current_job_stats_local_git_repo_stats.get("git_latest_commit_rev", 0)

    if (
        branches_max_rev > last_changed_revision and
        current_git_commit_count == 0
    ):

        # If git svn has blown past svn info's "Last Changed Rev"
        errors.append(f"Repo is empty, and branches_max_rev {branches_max_rev} > last_changed_revision {last_changed_revision}, unsetting svn-remote.svn.branches-maxRev and svn-remote.svn.tags-maxRev to remediate")

        # Remediate the situation
        # NOTE: This causes this run of the git svn fetch command to start back from svn repo revision 1,
        # which may take a long time
        git.set_config(ctx, "svn-remote.svn.branches-maxRev", "0", config_file_path=".git/svn/.metadata")
        git.set_config(ctx, "svn-remote.svn.tags-maxRev",     "0", config_file_path=".git/svn/.metadata")

    # If the repo is out of date,
    # and branches_max_rev is higher than the last changed rev that we're trying to sync
    # this repo will always be out of date, unless we can back up branches_max_rev to let us sync
    # the last changed rev
    if (
        branches_max_rev        > last_changed_revision and
        last_changed_revision   > git_latest_commit_rev
    ):
        # branches_max_rev_setback = last_changed_revision - 1
        # errors.append(f"branches_max_rev {branches_max_rev} > last_changed_revision {last_changed_revision} > git_latest_commit_rev {git_latest_commit_rev}, meaning this repo would never catch up; trying to remediate by resetting branches_max_rev to git_latest_commit_rev {git_latest_commit_rev}")
        # git.set_config(ctx, "svn-remote.svn.branches-maxRev", f"{branches_max_rev_setback}", config_file_path=".git/svn/.metadata")
        # git.set_config(ctx, "svn-remote.svn.tags-maxRev",     f"{branches_max_rev_setback}", config_file_path=".git/svn/.metadata")
        errors.append(f"branches_max_rev {branches_max_rev} > last_changed_revision {last_changed_revision} > git_latest_commit_rev {git_latest_commit_rev}, meaning this repo would never catch up; unsetting svn-remote.svn.branches-maxRev and svn-remote.svn.tags-maxRev to remediate")
        git.set_config(ctx, "svn-remote.svn.branches-maxRev", "0", config_file_path=".git/svn/.metadata")
        git.set_config(ctx, "svn-remote.svn.tags-maxRev",     "0", config_file_path=".git/svn/.metadata")


    # Assign the lists to the job result data for log output
    if errors:
        ctx.job["result"]["errors"]     = errors
    if warnings:
        ctx.job["result"]["warnings"]   = warnings
    action                          = "git svn fetch"
    reason                          = ""
    structured_log_dict             = {"process": git_svn_fetch_result}

    ## Make final success / fail call
    if len(errors) > 0:

        reason += "git svn fetch failed with errors"
        success = False
        log_level = "error"

    elif len(warnings) > 0:

        reason += "git svn fetch passed with warnings"
        success = True
        log_level = "warning"

    else:

        # TODO: call _get_local_git_repo_stats(ctx, "end") here? to make this a canonical event for success / max retries?
        reason += "git svn fetch completed successfully"
        success = True
        log_level = "info"

    set_job_result(ctx, action, reason, success)
    log(ctx, f"{reason}", log_level, structured_log_dict)

    return success


def _remove_non_errors_from_git_svn_fetch_output(ctx: Context, git_svn_fetch_output: list = []) -> list:
    """
    Filter out lines from the git svn fetch output which are known to not be problems
    Keep this list tidy, as execution time is len(error_messages) x len(git_svn_fetch_result_output)
    """

    if not git_svn_fetch_output:
        return []

    # log(ctx, f"before len(git_svn_fetch_output): {len(git_svn_fetch_output)}")

    ## Check for any errors in the command output
    # Note: git_svn_fetch_output can be very long
    # "output_line_count": 309940,

    # Shorten the number of lines in the git svn output,
    # by removing lines which we know are not errors / may be false positives
    # Sort in order from most lines in typical output to least, to remove the most lines earliest
    ignore_lines = [
        r"\\tA\\t.*",                       # "\tA\tdir/file.ext",          # Add a new file
        r"\\tM\\t.*",                       # "\tM\tdir/file.ext",          # Modify a file
        r"r[0-9]+ = .*",                    # r[rev] = [hash] (refs/remotes/origin/tags/[tag])
        r"Checked through r[0-9]+",         # "Checked through r123456"     # Many of the lines
        r"\\tD\\t.*",                       # "\tD\tdir/file.ext",          # Delete a file
        r"W: \+empty_dir: .*",
        r"W: -empty_dir: .*",
        r"Index mismatch: \w+ != \w+",
        r"rereading \w+",
        r"W: Ignoring error from SVN.*",     # "W: Ignoring error from SVN, path probably does not exist: (160013): Filesystem has no item: File not found..."
        r"Auto packing the repository in background for optimum performance.",
        r"See \\\"git help gc\\\" for manual housekeeping.",
        r"Authentication realm: .*",
        r"Password for '.*':",
        r"This may take a while on large repositories",
        r"W: Do not be alarmed at the above message git-svn is just searching aggressively for old history.",
        r"branch_from: .*",
        r"Found possible branch point: .*",
        r"Initializing parent: .*",
        r"Found branch parent: .*",
        r"Following parent with do_switch",
        r"Successfully followed parent",
        r"Checking svn:mergeinfo changes since r.*",
        r"W: svn cherry-pick ignored .*",
    ]

    # Compile regex patterns for efficiency
    ignore_lines_compiled_regexes = []
    for ignore_line in ignore_lines:
        compiled_regex = re.compile(ignore_line)
        ignore_lines_compiled_regexes.append((ignore_line, compiled_regex))

    # Remove the ignored lines, and empty lines from the output list
    for ignore_line, compiled_regex in ignore_lines_compiled_regexes:
        git_svn_fetch_output = [line for line in git_svn_fetch_output if line and not compiled_regex.search(line)]

    return git_svn_fetch_output


def _find_errors_in_git_svn_fetch_output(ctx: Context, git_svn_fetch_output: list = []) -> list:
    """
    Check for expected error messages
    Keep this list tidy, as execution time is len(error_messages) x len(git_svn_fetch_result_output)
    """

    if not git_svn_fetch_output:
        return []

    errors = []

    # Dicts of lists of regex patterns
    # Be sure to escape any special characters needed in this list
    # These strings get .* added both before and after
    error_message_regex_patterns_dict = {
        "Timeout": [
            "Connection timed out",
        ],
        "Connectivity issue": [
            "Connection refused",
            "Can't create session",
            "SVN connection failed somewhere",
            "Invalid repository URL",
            "SSL handshake failed",
            "Repository not found",
        ],
        "auth": [
            "Authentication failed",
            "Authorization failed",
            "Invalid credentials",
            "Permission denied",
            "cannot fetch directory .* not authorized",
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
            "Too many open files",
            "No space left on device",
            "Path not found",
            "Repository is locked",
            "Working copy locked",
            "Couldn't unlink index",
            "Failed to open .* for writing",
            "Failed to close",
        ],
        "other": [
            "Error running context",
            "Error from SVN",
            "svn: E",
            "Author: .* not defined in .* file",
            "failed with exit code",
            "useSvmProps set, but failed to read SVM properties",
            "useSvnsyncProps set, but failed to read svnsync property",
            "abort:",
            "error:",
            "fatal:",
            " at /usr/share/perl5/Git/SVN/Ra.pm line ",
        ]
    }

    # Compile all regex patterns once for efficiency
    compiled_patterns = []
    for error_category, patterns in error_message_regex_patterns_dict.items():
        for pattern in patterns:
            regex_pattern = rf".*{pattern}.*"
            compiled_regex = re.compile(regex_pattern)
            compiled_patterns.append((error_category, compiled_regex))

    # Single pass through output lines - O(lines x patterns)
    matched_lines = set()  # Track matched lines to avoid duplicates
    for line in git_svn_fetch_output:
        if line in matched_lines:
            continue

        for error_category, compiled_regex in compiled_patterns:
            if compiled_regex.search(line):
                errors.append(f"Error message: {error_category}: {line}")
                matched_lines.add(line)
                break  # Stop checking other patterns for this line

    # Remove the matched lines from the output
    remaining_output = [line for line in git_svn_fetch_output if line not in matched_lines]

    if remaining_output:
        ctx.job["result"]["remaining_output"] = remaining_output

    return errors
