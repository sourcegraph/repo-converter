#!/usr/bin/env python3
# Convert a Subversion repo to Git

# Import repo-converter modules
from utils.context import Context
from utils.log import log, set_job_result
from utils import cmd, git

# Import Python standard modules
import os
from pathlib import Path
import random
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

    job_start_time = int(time.time())

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
    if not _check_if_repo_exists_locally(ctx, commands):

        # If the repo doesn't exist locally, initialize it
        _initialize_git_repo(ctx, commands)

    # Get dir size of converted git repo directory
    _get_local_git_dir_stats(ctx, "start")

     # Update repo config
    _configure_git_repo(ctx, commands)

    # Check if the local repo is already up to date
    if _check_if_repo_already_up_to_date(ctx):

        # If the repo already exists, and is already up to date, then exit early
        # TODO: Set ctx.job attributes for repo state / up to date

        ### EXTERNAL COMMAND: svn log ###
        _log_recent_commits(ctx, commands)
        _cleanup(ctx)
        return

    ### EXTERNAL COMMAND: svn log ###
    # This is the big one, to count all revs remaining
    _log_number_of_revs_out_of_date(ctx, commands)

    # Calculate revision range for this fetch
    ### EXTERNAL COMMAND: svn log --limit batch-size ###
    if not _calculate_batch_revisions(ctx, commands):
        return

    # Execute the fetch
    ### EXTERNAL COMMAND: git svn fetch ###
    _execute_git_svn_fetch(ctx, commands)

    # Cleanup before exit
    _cleanup(ctx)

    # Get dir size of converted git repo
    _get_local_git_dir_stats(ctx, "end")

    ctx.job["job"]["result"]["run_time_seconds"] = int(time.time() - job_start_time)

    log(ctx, "SVN repo conversion job complete", "info")


def _extract_repo_config_and_set_default_values(ctx: Context) -> None:
    """
    Extract repo configuration parameters from the Context object and set defaults
    """

    # Get the repo key from the job context
    repo_key = ctx.job.get("job",{}).get("config",{}).get("repo_key","")

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

    processed_config["log_recent_commits"]  = ctx.env_vars["LOG_RECENT_COMMITS"]
    processed_config["log_remaining_revs"]  = ctx.env_vars["LOG_REMAINING_REVS"]
    processed_config["max_retries"]         = ctx.env_vars["MAX_RETRIES"]

    # Update the repo_config in the context with processed values
    ctx.job["job"]["config"].update(processed_config)
    log(ctx, "Repo config", "debug")


def _build_cli_commands(ctx: Context) -> dict:
    """
    Build commands for both SVN and Git CLI tools
    As lists of strings
    """

    # Get config values
    job_config                          = ctx.job.get("job",{}).get("config",{})
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
    arg_batch_end_revision                  = [f"{ctx.git_config_namespace}.batch-end-revision"]
    arg_git                                 = ["git", "-C", local_repo_path]
    arg_git_cfg                             = arg_git + ["config"]
    arg_git_svn                             = arg_git + ["svn"]

    # git commands
    cmd_git_default_branch                  = arg_git     + ["symbolic-ref", "HEAD", f"refs/heads/{git_default_branch}"]
    cmd_git_garbage_collection              = arg_git     + ["gc"]
    cmd_git_set_batch_end_revision          = arg_git_cfg + ["--replace-all"] + arg_batch_end_revision
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
        'cmd_git_set_batch_end_revision':   cmd_git_set_batch_end_revision,
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
    job_config      = ctx.job.get("job",{}).get("config",{})
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
    job_config          = ctx.job.get("job",{}).get("config",{})
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

            ctx.job["job"]["svn_info"] = svn_info.get("output","")

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

    svn_info = ctx.job.get("job",{}).get("svn_info",{})

    # Combine / cast the output lines into a string
    svn_info_output_string = " ".join(svn_info)

    # Get last changed revision for this SVN repo from the svn info output
    if not "Last Changed Rev: " in svn_info_output_string:

        log_failure_message = "Last Changed Rev not found in svn info output"
        set_job_result(ctx, "skipped", log_failure_message, False)
        log(ctx, log_failure_message, "error")
        return False


    remote_current_rev = int(svn_info_output_string.split("Last Changed Rev: ")[1].split(" ")[0])
    ctx.job["job"]["stats"]["remote"]["last_changed_revision"] = int(remote_current_rev)

    remote_last_changed_date = svn_info_output_string.split("Last Changed Date: ")[1].split(" ")[0]
    ctx.job["job"]["stats"]["remote"]["last_changed_date"] = remote_last_changed_date

    return True


def _check_if_repo_exists_locally(ctx: Context, commands: dict) -> bool:
    """
    Check if the local repo exists and we need to update it,
    or if it doesn't exist, or it's invalid, and we need to create / recreate it

    Create:
        State:
            The directory doesn't already exist
            The repo      doesn't already exist
        How did we get here:
            First run of the script
            New repo was added to the repos-to-convert.yaml file
            Repo was deleted from disk
        Approach:
            Harder to test for the negative, so let's:
            - Assume we're in the Create state,
            - Check if the repo exists and is valid, then we're in the Update state

    Update:
        State:
            Repo already exists, with a valid configuration
        How did we get here:
            A fetch job was previously run, but is not currently running
        Approach:
            Check if we're in the update state, then return true

    """

    # Get config values
    job_config                      = ctx.job.get("job",{}).get("config",{})
    svn_remote_repo_code_root_url   = job_config.get("svn_remote_repo_code_root_url","")
    svn_url                         = git.get_config(ctx, "svn-remote.svn.url", quiet=True)
    svn_url                         = " ".join(svn_url) if isinstance(svn_url, list) else svn_url

    if svn_url and svn_url in svn_remote_repo_code_root_url:
        set_job_result(ctx, "updating", "repo exists")
        return True

    else:
        set_job_result(ctx, "creating", "repo not found on disk")
        return False


def _initialize_git_repo(ctx: Context, commands: dict) -> None:
    """
    Initialize a new Git repository
    """

    # TODO: Move all the arg / command assembly to another function
    # Get config values
    job_config      = ctx.job.get("job",{}).get("config",{})
    local_repo_path = job_config.get("local_repo_path","")
    bare_clone      = job_config.get("bare_clone","")
    password        = job_config.get("password","")

    log(ctx, f"Repo not found on disk, initializing new repo", "info")

    # If the directory does exist, then it's not a valid git repo, and needs to be destroyed and recreated
    if os.path.exists(local_repo_path):
        shutil.rmtree(local_repo_path)

    # Created the needed dirs
    os.makedirs(local_repo_path)

    cmd_git_svn_init = commands["cmd_git_svn_init"].copy()

    # Initialize the repo
    # TODO: git svn shouldn't need a password to initialize a repo?
    cmd.run_subprocess(ctx, cmd_git_svn_init, password, name="cmd_git_svn_init")

    # Configure the bare clone
    if bare_clone:
        git.set_config(ctx, "core.bare", "true")

    # Initialize this config with a 0 value
    git.set_config(ctx, f"{ctx.git_config_namespace}.batch-end-revision", "0")


def _configure_git_repo(ctx: Context, commands: dict) -> None:
    """
    Configure Git repository settings
    """

    # Get config values
    job_config              = ctx.job.get("job",{}).get("config",{})
    authors_file_path       = job_config.get("authors_file_path","")
    authors_prog_path       = job_config.get("authors_prog_path","")
    git_ignore_file_path    = job_config.get("git_ignore_file_path","")
    local_repo_path         = job_config.get("local_repo_path","")

    # Set the default branch local to this repo, after init
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


def _check_if_repo_already_up_to_date(ctx: Context) -> bool:
    """
    Get the local_previous_batch_end_revision from the local git repo

    Compare it against remote_current_rev from the svn info output
    """

    remote_current_rev = ctx.job.get("job",{}).get("stats",{}).get("remote",{}).get("last_changed_revision","")

    # get_config() returns a list of strings, cast it into an int
    local_previous_batch_end_revision = git.get_config(ctx, f"{ctx.git_config_namespace}.batch-end-revision")
    local_previous_batch_end_revision = " ".join(local_previous_batch_end_revision) if isinstance(local_previous_batch_end_revision, list) else local_previous_batch_end_revision
    local_previous_batch_end_revision = int(local_previous_batch_end_revision) if local_previous_batch_end_revision else 0

    ctx.job["job"]["stats"]["local"]["previous_batch_end_revision"] = local_previous_batch_end_revision

    if local_previous_batch_end_revision == remote_current_rev:
        set_job_result(ctx, "skipped", "Repo up to date", True)
        return True

    else:
        set_job_result(ctx, "updating", "Repo out of date")
        return False


def _log_recent_commits(ctx: Context, commands: dict) -> None:
    """
    If the repo exists and is already up to date,
    run these steps to cleanup,
    then return
    """

    # Get config values
    job_config          = ctx.job.get("job",{}).get("config",{})
    log_recent_commits  = job_config.get("log_recent_commits",0)

    if log_recent_commits > 0:

        # Output the n most recent commits to visually verify the local git repo is up to date with the remote repo
        cmd_svn_log_recent_revs = commands["cmd_svn_log"] + ["--limit", f"{log_recent_commits}"]

        password = job_config.get("password","")

        ctx.job["svn_log_output"] = cmd.run_subprocess(ctx, cmd_svn_log_recent_revs, password, quiet=True, name="svn_log_recent_commits")["output"]

        log(ctx, f"LOG_RECENT_COMMITS={log_recent_commits}", "debug")

        # Remove the svn_log_output from the job context dict, so it doesn't get logged again in subsequent logs
        ctx.job.pop("svn_log_output")


def _log_number_of_revs_out_of_date(ctx: Context, commands: dict) -> None:
    """
    Run the svn log command to count the total number of revs out of date

    TODO: Eliminate this, or make it much more efficient
    Made it optional, enabled by env var, disabled by default
    """

    # Get config values
    job_config          = ctx.job.get("job",{}).get("config",{})
    log_remaining_revs  = job_config.get("log_remaining_revs","")

    if log_remaining_revs:

        local_previous_batch_end_revision   = ctx.job.get("job",{}).get("stats",{}).get("local",{}).get("previous_batch_end_revision","")
        cmd_svn_log_remaining_revs          = commands["cmd_svn_log"] + ["--revision", f"{local_previous_batch_end_revision}:HEAD"]
        password                            = job_config.get("password","")

        svn_log = cmd.run_subprocess(ctx, cmd_svn_log_remaining_revs, password, name="svn_log_remaining_revs")

        # Parse the output to get the number of remaining revs
        svn_log_output_string = " ".join(svn_log["output"])
        remaining_revs_count = svn_log_output_string.count("revision=")
        fetching_batch_count = min(remaining_revs_count, job_config.get("fetch_batch_size",""))

        # Log the results
        ctx.job["job"]["stats"]["remote"]["remaining_revs"]        = remaining_revs_count
        ctx.job["job"]["stats"]["remote"]["fetching_batch_count"]  = fetching_batch_count

        log(ctx, "Logging remaining_revs; note: this is an expensive operation", "info")


def _calculate_batch_revisions(ctx: Context, commands: dict) -> dict:
    """
    Run the svn log command to calculate batch start and end revisions for fetching

    TODO: Make this much more efficient
    """

    # Get config values
    job_config                          = ctx.job.get("job",{}).get("config",{})
    fetch_batch_size                    = job_config.get("fetch_batch_size","")
    password                            = job_config.get("password","")
    cmd_svn_log                         = commands["cmd_svn_log"]
    local_previous_batch_end_revision   = ctx.job.get("job",{}).get("stats",{}).get("local",{}).get("previous_batch_end_revision","")
    this_batch_end_revision             = None

    # Pick a revision number to start with; may or may not be a real rev number
    this_batch_start_revision           = local_previous_batch_end_revision + 1

    # Run the svn log command to get real revision numbers for this batch
    cmd_svn_log_get_this_batch_rev_range           = cmd_svn_log + ["--limit", str(fetch_batch_size), "--revision", f"{this_batch_start_revision}:HEAD"]
    cmd_svn_log_get_this_batch_rev_range_result    = cmd.run_subprocess(ctx, cmd_svn_log_get_this_batch_rev_range, password, name="cmd_svn_log_get_this_batch_rev_range")

    cmd_svn_log_get_this_batch_rev_range_output    = cmd_svn_log_get_this_batch_rev_range_result.get("output","")

    if cmd_svn_log_get_this_batch_rev_range_result["return_code"] == 0 and cmd_svn_log_get_this_batch_rev_range_output:

        # Update the this batch's starting rev to the first real rev number after the previous end rev
        this_batch_start_revision = int(" ".join(cmd_svn_log_get_this_batch_rev_range_output).split("revision=\"")[1].split("\"")[0])
        ctx.job["job"]["stats"]["local"]["this_batch_start_rev"] = this_batch_start_revision

        # Reverse the output so we can get the last revision number
        cmd_svn_log_get_this_batch_rev_range_output.reverse()
        this_batch_end_revision = int(" ".join(cmd_svn_log_get_this_batch_rev_range_output).split("revision=\"")[1].split("\"")[0])
        ctx.job["job"]["stats"]["local"]["this_batch_end_rev"] = this_batch_end_revision

        return True

    else:

        log_failure_message = "Failed to calculate batch revs"
        set_job_result(ctx, "skipped", log_failure_message, False)
        log(ctx, log_failure_message, "error")
        return False


def _execute_git_svn_fetch(ctx: Context, commands: dict) -> None:
    """
    Execute the git svn fetch operation
    """

    log(ctx, f"Repo out of date; updating", "info")

    # Get config values
    job_config              = ctx.job.get("job",{}).get("config",{})
    job_stats_local         = ctx.job.get("job",{}).get("stats",{}).get("local",{})
    batch_end_revision      = job_stats_local.get("this_batch_end_rev","")
    batch_start_revision    = job_stats_local.get("this_batch_start_rev","")
    local_repo_path         = job_config.get("local_repo_path","")
    password                = job_config.get("password","")
    cmd_git_svn_fetch       = commands["cmd_git_svn_fetch"].copy()

    # If we have batch revisions, use them
    if batch_start_revision and batch_end_revision:
        cmd_git_svn_fetch += ["--revision", f"{batch_start_revision}:{batch_end_revision}"]

    # Delete duplicate lines from the git config file, before the fetch
    git.deduplicate_git_config_file(ctx)

    # Start the fetch
    log(ctx, f'fetching with {" ".join(cmd_git_svn_fetch)}', "info")
    git_svn_fetch_result = cmd.run_subprocess(ctx, cmd_git_svn_fetch, password, name="cmd_git_svn_fetch")

    # Validate repository state
    # git_repository_state_valid, git_repository_state_message = _validate_git_repository_state(ctx, local_repo_path)
    # log(ctx, f"validate_git_repository_state result: {git_repository_state_valid}; message: {git_repository_state_message}", "debug")

    # If the fetch succeeded and we have a this_batch_end_revision
    if git_svn_fetch_result["return_code"] == 0 and batch_end_revision:

        # Store the ending revision number
        git.set_config(ctx, f"{ctx.git_config_namespace}.batch-end-revision", str(batch_end_revision))
        set_job_result(ctx, "git svn fetch complete", "fetch", True)
        log(ctx, f"git svn fetch complete", "info")

    else:

        # Check for errors
        error_messages = [
            "Can't create session", "Unable to connect to a repository at URL", "Connection refused",
            "Connection timed out", "SSL handshake failed", "Authentication failed",
            "Authorization failed", "Invalid credentials", "Error running context",
            "Repository not found", "Path not found", "Invalid repository URL",
            "fatal:", "error:", "abort:", "Permission denied", "No space left on device",
            "svn: E", "Working copy locked", "Repository is locked",
        ]

        log_failure_message = ""

        for error_message in error_messages:
            if error_message in str(git_svn_fetch_result["output"]):

                log_failure_message += f"{error_message} "

        set_job_result(ctx, "git svn fetch failed", log_failure_message, False)
        log(ctx, f"git svn fetch failed: {log_failure_message}", "error")


# def _validate_git_repository_state(ctx: Context, local_repo_path: str) -> tuple[bool, str]:
#     """
#     Validate that the Git repository is in a valid state
#     """

#     checks = []

#     # Check if git repo is valid
#     cmd_git_status = ["git", "-C", local_repo_path, "status", "--porcelain"]
#     result = cmd.run_subprocess(ctx, cmd_git_status, quiet=True, name="git_status")
#     checks.append(("git_status", result["return_code"] == 0))

#     # Check if HEAD exists
#     cmd_git_head = ["git", "-C", local_repo_path, "rev-parse", "HEAD"]
#     result = cmd.run_subprocess(ctx, cmd_git_head, quiet=True, name="git_head")
#     checks.append(("git_head", result["return_code"] == 0))

#     # Check if git-svn metadata exists
#     cmd_git_svn_info = ["git", "-C", local_repo_path, "svn", "info"]
#     result = cmd.run_subprocess(ctx, cmd_git_svn_info, quiet=True, name="git_svn_info")
#     checks.append(("git_svn_info", result["return_code"] == 0))

#     failed_checks = [name for name, passed in checks if not passed]

#     if failed_checks:
#         return False, f"Repository state validation failed: {failed_checks}"

#     return True, "Repository state validation passed"


def _cleanup(ctx: Context) -> None:
    """
    Groups up any other functions needed to clean up before exit
    """

    # Run git garbage collection and cleanup branches, even if repo is already up to date
    git.garbage_collection(ctx)
    git.cleanup_branches_and_tags(ctx)


def _get_local_git_dir_stats(ctx: Context, event: str) -> None:
    """
    Functions to collect statistics for local repo

    Called with event "start" and "end"
    """

    # Get config values
    job_config      = ctx.job.get("job",{}).get("config",{})
    job_stats_local = ctx.job.get("job",{}).get("stats",{}).get("local",{})

    # Git dir size
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


    # Commit count
    commit_count = git.count_commits_in_repo(ctx)
    job_stats_local[f"git_repo_commit_count_{event}"] = commit_count

    ctx.job["job"]["stats"]["local"].update(job_stats_local)


