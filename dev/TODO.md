# TODO

## Usability

- Update examples

## Observability

- Implement canonical log events
    - Designate specific events as canonical
        - Job finish
    - Add a specific `"canonical_event": true` attribute, to make these easier to filter on
    - Add enough information to the log event to evaluate:
        - If the job succeeded / failed
        - Job execution time
        - Execution time of remote commands
        - Remote errors / timeouts

- Add to the status monitor thread loop:
    - Details of each running repo conversion job
        - Count of commits at the beginning
        - Count of commits added in the current job
        - Most recently converted revision number and commit date
        - svn info Last Changed Rev and Last Changed Date
        - "svn-remote.svn.branches-maxRev"
        - retries_attempted

- A running list, as these values change
    - Date, Time, repo_key, Dir Size (B), Dir Size Change (B), Latest Converted Commit SVN Rev, Latest Converted Commit Date, SVN Repo Remote Last Changed Rev, branches-maxRev, SVN Repo Remote Current Revision (current index of entire repo)

- Implement OpenTelemetry

- Find a tool to search / filter through logs
    - See Slack thread with Eng
    - Amp'ed the `dev/query_logs.py` script in the meantime
        - These kinds of scripts are throwaway work, as AI has a hard time maintaining them as the log JSON schema changes

- Amp's suggestions
    - Enhance error events with automatic error context capture and correlation IDs
        - Remote server response errors, ex. svn: E175012: Connection timed out
    - Context Managers: Git operations and command execution use context managers to automatically inject relevant metadata for all logs within their scope.
    - Decorator Pattern: Command execution decorator automatically captures all command-related data (args, timing, stdout/stderr, exit codes).
    - This architecture uses a context stack pattern where different operational contexts (git operations, command execution) automatically push their metadata, making all relevant data available to every log statement within that context.

- Set up log schema and workspace settings for RedHat's [YAML](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) VS Code extension

## SVN

### Stability

- Maybe we don't need to handle batch processing, just infinite retries?
    - We still need rev numbers to show progress of conversion jobs
    - It'd be much simpler if we could use the data already stored by `git svn fetch`, than have to query this data from the server
    - These rev numbers are available:
        - Done - Last Changed Rev from `svn info` output
        - Done - Last converted rev from `git for-each-ref -limit=1` output
        - Done - Count of commits from local git repo history
        - Done - Last rev checked, from the `.git/svn/.metadata` file
    - So we have all the data we need, what's stopping us from using it instead of `svn log` data?
    - But wait... isn't the situation we started in?
        - Jobs timed out, because they were trying to boil the ocean / convert the entire repo in one go
        - This was a big problem, because the script only ran in series, so it'd hold up all the other repos
        - The script now runs in parallel, so other job slots can continue processing
    - `git svn fetch` does actually commit each individual revision / save it on disk, as its converted
        - The git.garbage_collection() then git.cleanup_branches_and_tags() functions need to run to make the branches visible (convert remote branches to local)
    - Initial scan through repo rev index, at `--log-window-size n` number of revs per network request, can take a really long time
    - Current state: letting the `git svn fetch` command run as long as it needs to, convert as many commits as it can till it dies, then restart the job, either on retry, or the next time the main loop hits this repo again

- `git svn fetch --log-window-size [100] --revision [BASE:HEAD]`
    - log-window-size
        - For each network request to the Subversion server, the number of revs to query for
    - Absolutely intolerant of invalid revs in the `--revisions` range
        - ex. if the start of the range is prior in the local repo's history, it'll just exit 0 with no output, and no changes
    - BASE
        - If any local commits, BASE is the most recent commit (local git HEAD)
        - If no local commits, BASE defaults to 0, which is super inefficient, as it has to make (first_rev/log-window-size) requests to the SVN server, just to find the starting rev
    - HEAD
        - (remote)
        - Matches "Last Changed Rev" from the `svn info` command output

- `cat .git/svn/.metadata`
    ```
    ; This file is used internally by git-svn
    ; You should not have to edit it
    [svn-remote "svn"]
            reposRoot = https://svn.apache.org/repos/asf
            uuid = 13f79535-47bb-0310-9956-ffa450edef68
            branches-maxRev = 1886214
            tags-maxRev = 1886140
    ```
    - branches-maxRev
    - tags-maxRev
        - The last revs that git svn has checked for branches / tags
        - Future iterations can start at this number, to prevent duplicate work, checking old revs
        - If the user changes the branches in scope, this number must be reset

### Other

- .gitignore files
    - `git svn create-ignore`
    - `git svn show-ignore`
    - https://git-scm.com/docs/git-svn#Documentation/git-svn.txt-emcreate-ignoreem

- Test layout tags and branches as lists / arrays

## Config

- Create server-specific concurrency semaphore from repos-to-convert value, if present

- Move the config schema to a separate YAML file
    - Bake it into the image
    - Read it into Context on container startup, so the `sanitize_repos_to_convert` function can update it, to make it available to `check_required_fields`
    - Provide, for each field:
        - Name
        - Description
        - Default values
        - Valid data types
        - Required? (ex. either url or repo-url)
        - Valid parents (global / server / repo), so child keys can be validated that they're under a valid parent key
        - Usage
        - Examples

- Implement proper type validation with clear error messages for config file inputs

- Env vars vs config file
    - Env vars
        - Service-oriented, ex. log level
        - Cannot change without restarting the container
        - Create env var for a map so creds don't need to be stored in files
            - server
            - username
            - password
    - repos-to-convert.yaml
        - Content-oriented
        - List of repos to convert
        - Can change without restarting the container

## Process Management

- Look into children = sub_process.children(recursive=True) to help track child procs / grand child / great grand child, etc.

- Change all commands to strings, and use shlex.split(args_string) to split them for cmd.run_subprocess()?
    - https://realpython.com/python-subprocess/#processes-and-subprocesses:~:text=use%20the%20shlex-,module,-to%20help%20you

- Some repo sync job processes seem to get stuck / not get cleaned up
    - This seems to hang the main loop, stopping further cycles
    - STATUS_MONITOR_INTERVAL=60 is defined, but even the status monitor doesn't seem to be firing
    - These events were consecutive in the logs
    - Amp suggests its a deadlock from the status_monitor log event calling the get_status() command, added a timeout to the acquire semaphore
    - Note the huge gaps in time
        ```
        {"date": "2025-07-21", "time": "10:26:34.621418", "cycle": 346, "message": "Starting main loop run", "level": "debug", "env_vars": {"BUILD_BRANCH": "marc-fix-svn-fetch-error-processing", "BUILD_COMMIT": "e98ecd4", "BUILD_COMMIT_MESSAGE": "Add git_dir_size math", "BUILD_DATE": "2025-07-21T04:33:07Z", "BUILD_TAG_OR_COMMIT_FOR_LOGS": "e98ecd4", "LOG_LEVEL": "DEBUG", "MAX_CONCURRENT_CONVERSIONS_GLOBAL": 10, "MAX_CONCURRENT_CONVERSIONS_PER_SERVER": 10, "MAX_CYCLES": 0, "MAX_RETRIES": 3, "REPOS_TO_CONVERT": "/sg/repos-to-convert.yaml", "REPO_CONVERTER_INTERVAL_SECONDS": 60, "SRC_SERVE_ROOT": "/sg/src-serve-root", "STATUS_MONITOR_INTERVAL": 60, "TRUNCATED_OUTPUT_MAX_LINES": 20, "TRUNCATED_OUTPUT_MAX_LINE_LENGTH": 200}, "code": {"caller": {"module": "__main__", "function": "main", "file": "/sg/repo-converter/src/main.py", "line": 57}}, "container": {"id": "af4e65adb143", "start_datetime": "2025-07-21 04:40:00", "uptime": "5h 46m 33s"}, "image": {"build_date": "2025-07-21T04:33:07Z", "build_tag": "e98ecd4"}, "timestamp": "1753093594.6214"}
        {"date": "2025-07-21", "time": "10:26:34.624270", "cycle": 346, "message": "Adding secret password to set of secrets to redact", "level": "debug", "code": {"caller": {"module": "config.load_repos", "function": "check_types_recursive", "file": "/sg/repo-converter/src/config/load_repos.py", "line": 201}, "parent_1": {"module": "config.load_repos", "function": "check_types_recursive", "file": "/sg/repo-converter/src/config/load_repos.py", "line": 140}, "parent_2": {"module": "config.load_repos", "function": "check_types_recursive", "file": "/sg/repo-converter/src/config/load_repos.py", "line": 140}}, "container": {"id": "af4e65adb143", "start_datetime": "2025-07-21 04:40:00", "uptime": "5h 46m 33s"}, "image": {"build_date": "2025-07-21T04:33:07Z", "build_tag": "e98ecd4"}, "timestamp": "1753093594.6243"}
        {"date": "2025-07-21", "time": "10:26:34.624820", "cycle": 346, "message": "Repos to convert", "level": "debug", "repos": {...
        {"date": "2025-07-21", "time": "10:26:34.663753", "cycle": 346, "message": "repo; Starting repo conversion job", "level": "debug", "job": {"config": {"repo_key":...
        {"date": "2025-07-22", "time": "11:13:29.010333", "cycle": 1, "message": "SIGCHLD handler reaped child PID 377 with exit code 1", "level": "debug", "job": {"config": {"bare_clone": true, "code_host_name":...
        {"date": "2025-07-22", "time": "11:13:29.179983", "cycle": 1, "message": "Process finished", "level": "debug", "process": {"args": "git -C /sg/src-serve-root/repo svn fetch...
        {"date": "2025-07-22", "time": "11:14:32.350086", "cycle": 1, "message": "before len(git_svn_fetch_output): 267287", "level": "debug", "job": {"config": {"bare_clone": true, "code_host_name":...
        {"date": "2025-07-22", "time": "11:14:32.844138", "cycle": 1, "message": "repo; git svn fetch failed with errors", "level": "error", "process": {"args": "git -C /sg/src-serve-root/repo svn fetch...
        {"date": "2025-07-22", "time": "11:14:32.864019", "cycle": 1, "message": "repo; retrying 2 of max 3 times, with a semi-random delay of 6 seconds", "level": "debug", "job": {"config": {"bare_clone": true, "code_host_name":...
        {"date": "2025-07-22", "time": "11:14:38.883261", "cycle": 1, "message": "repo; fetching with git -C /sg/src-serve-root/repo svn fetch...
        {"date": "2025-07-22", "time": "11:14:38.892069", "cycle": 1, "message": "Process started ", "level": "debug", "process": {"args": "git -C /sg/src-serve-root/repo svn fetch...
        {"date": "2025-07-23", "time": "00:01:02.655521", "cycle": 345, "message": "Received signal SIGTERM (15), initiating graceful shutdown", "level": "info", "job": {"config": {"bare_clone": true, "code_host_name":...
        ```

- Make child process reap events more usable
    - Find all the data we can get from a child process reap event
        - If not enough data
            - What data can we make use of, to lookup other data from a dict, ex. `ctx.processes`?
                - PPID? PPID of the PPID?
            - Store job sub-tasks' metadata in `ctx.processes`
    - To be retrieved in `cmd.log_process_status()`

- Determine if it's safe to timeout long-running `git svn fetch` commands, ex. interrupting branch / tag operations on large repos
    - If no, then don't implement a long-running process timeout
    - If yes, then find a way to determine if long-running processes are actively working
        - If the `/usr/bin/perl /usr/lib/git-core/git-svn fetch` command has been sitting flat at 0% CPU for an hour, then it may be safe to kill
    - https://realpython.com/python-subprocess/#timeoutexpired-for-processes-that-take-too-long

- SVN commands hanging
    - Add a timeout in run_subprocess() for hanging svn info ~~and svn log~~ commands, if data isn't transferring
        - Does the svn cli not have a timeout built in for this command?

- Process tree
    - Copied from the output of `docker exec -it repo-converter top`
    ```
    top - 03:39:24 up 6 days,  4:37,  0 users,  load average: 0.89, 1.60, 1.83
    Tasks:  14 total,   1 running,  13 sleeping,   0 stopped,   0 zombie
    %Cpu(s):  8.7 us, 10.7 sy,  0.0 ni, 80.2 id,  0.2 wa,  0.0 hi,  0.3 si,  0.0 st
    GiB Mem :      7.8 total,      2.0 free,      1.2 used,      4.5 buff/cache
    GiB Swap:      2.0 total,      1.9 free,      0.1 used.      6.3 avail Mem

        SID    PGRP     PID    PPID  VIRT    RES    SHR  %MEM OOMs  %CPU     TIME+ COMMAND
          1       1       1       0  0.1g   0.0g   0.0g   0.4  668   0.0   0:02.41 /usr/bin/python3 /sg/repo-converter/src/main.py
          1       1       7       1  0.5g   0.0g   0.0g   0.2  668   0.0   0:00.45  `- /usr/bin/python3 /sg/repo-converter/src/main.py
         81      81      81       1  0.1g   0.0g   0.0g   0.3  668   0.0   0:00.40  `- /usr/bin/python3 /sg/repo-converter/src/main.py
         81      81     527      81  0.0g   0.0g   0.0g   0.0  666   0.0   0:00.00      `- git -C /sg/src-serve-root/repo1 svn fetch --quiet --username user --log-window-size 100
         81      81     529     527  0.0g   0.0g   0.0g   0.5  668   0.3   2:52.51          `- /usr/bin/perl /usr/lib/git-core/git-svn fetch --quiet --username user --log-window-size 100
         81      81     880     529  2.1g   0.2g   0.1g   2.6  680   0.0   0:02.23              `- git cat-file --batch
         81      81    6267     529  0.0g   0.0g   0.0g   0.1  667   0.0   0:09.38              `- git hash-object -w --stdin-paths --no-filters
         81      81  305238     529  0.0g   0.0g   0.0g   0.1  666   0.0   0:00.00              `- git update-index -z --index-info
        144     144     144       1  0.1g   0.0g   0.0g   0.4  668   0.0   0:00.92  `- /usr/bin/python3 /sg/repo-converter/src/main.py
        144     144     478     144  0.0g   0.0g   0.0g   0.0  666   0.0   0:00.00      `- git -C /sg/src-serve-root/repo2 -c http.sslVerify=false svn fetch --quiet --username user --log-window-size 100
        144     144     479     478  0.2g   0.1g   0.0g   1.8  676  12.3   7:21.52          `- /usr/bin/perl /usr/lib/git-core/git-svn fetch --quiet --username user --log-window-size 100
        144     144     709     479  0.0g   0.0g   0.0g   0.4  668   0.0   0:02.79              `- git cat-file --batch
        144     144    1015     479  0.0g   0.0g   0.0g   0.1  666   0.0   0:08.89              `- git hash-object -w --stdin-paths --no-filters
    ```
    - PID 1
        - Docker container entrypoint
    - PID 7
        - Probably the `status_monitor.start` function
    - PIDs 81 and 144
        - Notice that the SID (Session ID) and PGRP (Process Group) match the PID 81 and 144 numbers, i.e. this process is its session and group leader, as a result of the `os.setsid()` call in `fork_conversion_processes.py`, this makes it much easier to find PGRP values in the container's logs to track which processes are getting cleaned up as they finish
        - Spawned by `multiprocessing.Process().start()` in `fork_conversion_processes.start()`
    - PIDs 527 and 478
        - `git svn fetch` command, called from `_git_svn_fetch()` in `svn.convert()`
        - Spawned by `psutil.Popen()` in `cmd.run_subprocess()`
    - PIDs 529 and 479
        - `git-svn` perl script, which runs the `git svn fetch` workload in [sub fetch, in SVN.pm](https://github.com/git/git/blob/v2.50.1/perl/Git/SVN.pm#L2052)
        - This perl script is quite naive, no retries, always exits 0, even on failures
    - PIDs 880 and 709
        - Long-running `git cat-file` process, which stores converted content in memory
        - This process usually has a higher than average OOMs (OOMkill score)
        - It seems quite likely that this process doesn't free up memory after each commit, so memory requirements for this process alone would be some large portion of a repo's size
        - The minimum memory requirements for this process would be the contents of the largest commit in the repo's history, otherwise the conversion would never progress beyond this commit
        - This process' CPU state is usually Sleeping, because it spends almost all of its time receiving content from the subversion server

- How do I get more information about the child PID which was reaped in these lines, in `./src/utils/signal_handler.py`?

    ```python
    if os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0:
        # "message": "SIGCHLD handler reaped child PID 10747 with exit code 129",
        log(ctx, f"SIGCHLD handler reaped child PID {pid} with exit code {os.WEXITSTATUS(status)}", "warning")
    ```
    - Maintain a list of processes, with their metadata, from when they're launched, and updated on an interval, then look up the PID's information in the signal handler from the list
        - Track PIDs when launching: Store process metadata (command, start time, purpose) in a dict when creating child processes
        - Cross-reference with active processes: Check if the PID exists in ctx.active_repo_conversion_processes
    - Use process monitoring libraries?

- Prevent stack traces during shutdown; from Amp:
    - The SIGTERM signals are received across different cycles (11, 0, 1) because:
        - Signal handler registers itself recursively: In signal_handler.py:19, the handler is registered as a lambda that calls itself
        - Process group kill triggers more signals: When the handler calls os.killpg() at line 39, it sends SIGTERM to all processes in the group, including itself
        - Multiple threads/processes receive signals: Each active process/thread receives its own SIGTERM and logs the "Received signal" message
    - Stack Trace During Shutdown occur because:
        - Signal handler called during JSON logging: The signal handler interrupts the logging process while it's serializing JSON data (line 51-52 in traceback)
        - Recursive signal handling: The handler tries to log while already handling a signal, creating a nested call
        - Multiprocessing cleanup fails: The FileNotFoundError at line 100 indicates the multiprocessing manager's socket connection was already closed when trying to access `self.active_jobs[server_name]`
    - Root Causes
        - Non-reentrant signal handling: The signal handler isn't designed to handle recursive calls safely
        - Race condition: The multiprocessing manager shuts down before all processes finish cleanup
        - Signal propagation: os.killpg() creates a cascade of signals across the process group
    - The application does eventually shut down gracefully, but the multiple signal receptions and stack traces indicate the shutdown process could be more robust.

- Multiprocessing / state / zombie cleanup
    - Integrate subprocess methods together
        - State tracking, in ctx.child_procs = {}
        - Cleanup of zombie processes, and richer process status updates, in cmd.status_update_and_cleanup_zombie_processes()?
        - svn._check_if_conversion_is_already_running_in_another_process() vs concurrency_manager.acquire_job_slot()
        - Clean up of process state

- Add to the process status check and cleanup function to
    - Get the last lines of stdout from a running process,
    - instead of just wait with a timeout of 0.1,
    - use communicate() with a timeout and read the stdout from the return value,
    - catch the timeout exception
    - May require tracking process objects in a dict, which would prevent processes from getting auto-cleaned, which may result in higher zombie numbers

- Implement better error handling for process management

## Builds

- GitHub Actions build tags
    - Want
        - latest: Latest release tag
        - insiders: Latest of any build
        - main: Latest commit on main
        - feature-branch: Latest commit on each feature branch
        - v0.1.1: Release tag
    - Getting
        - HEAD: On release tag build, value of BUILD_BRANCH; this build also gets the correct BUILD_TAG=v0.1.1 tag
    - Difference in GitHub Actions worker node env vars between:
        - Push to feature branch
            - gha-env-vars-push-to-branch.sh
        - PR
            - TODO
        - Push (merge) to main
            - TODO
        - Tag / release
            - TODO
        - workflow_dispatch
            - gha-env-vars-workflow-dispatch.sh
- GitHub Actions cleanup jobs
- Wolfi Python base image for Docker / podman build
- Container runAs user
    - It seems like the only way this works for both Podman and Docker Compose, is to:
        - Bake the image with a specific UID/GID,
        - and change the app service user account's UID/GID on the host OS to match
    - Changed the UID of the service account on the host to 10001, and GID to 10002
    - I hope I'm wrong on this limitation, adding this to the TODO list to figure out later

## Dev

- Add proper doc strings to all classes and methods
    - https://www.dataquest.io/blog/documenting-in-python-with-docstrings

- Switch most git commands in the git module from git cli to GitPython

- Count lines of code
    ```shell
    cloc --exclude-lang=JSON,CSV,Text --exclude-dir=.venv,notes,examples,logs --quiet --by-file-by-lang .
    ```

## Expansion

- Implement TODOs strewn around the code

- Add git-to-p4 converter
    - Run it in MSP, to build up our Perforce test depots from public OSS repos from GitHub.com

- Git clone
    - Move Git SSH clone Bash script into this containers
    - See if the GitPython module fetches the repo successfully, or has a way to clone multiple branches
        - Fetch (just the default branch)
        - Fetch all branches
        - Clone all branches
    - From the git remote --help
        - Imitate git clone but track only selected branches
            - mkdir project.git
            - cd project.git
            - git init
            - git remote add -f -t master -m master origin git://example.com/git.git/
            - git merge origin

## Podman Issues

- Install Podman Desktop from https://podman.io/
    - Need command line tab completions

- "too many files open in system" error message when running with podman
    - Create a new /etc/security/limits.d/30-nofile.conf file in the Podman VM, as per instructions in https://github.com/containers/podman/issues/5526#issuecomment-1440363593

- Executing external compose provider "/usr/local/bin/docker-compose". Please see podman-compose(1) for how to disable this message. <<<<
    - Configure compose_warning_logs=true, as per https://github.com/containers/common/blob/main/docs/containers.conf.5.md
    - Edit / create the file at `~/.config/containers/containers.conf`, and add
        ```toml
        [engine]
        compose_warning_logs=false
        ```

## Notes

- Subversion seems to have two different meanings for the word "repo"
    - Server side:
        - Repository Root and Repository UUID
    - User side:
        - trunk / branches / tags directories
    - We don't actually care about the server-side meaning of a repo
    - All we care about is:
        - A "base" URL where to start the paths from
        - A list of paths from that base URL

- Authors file
    - java -jar /sg/svn-migration-scripts.jar authors https://svn.apache.org/repos/asf/eagle > authors.txt
    - Kinda useful, surprisingly fast

- git list all config for a repo
    - git -C $local_repo_path config --list

- Decent example of converting commit messages
    - https://github.com/seantis/git-svn-trac/blob/master/git-svn-trac.py

- Totally different approach: Run our own Subversion server in the Docker Compose deployment
    - Sync SVN-to-SVN
    - Then convert from local SVN server
    - I had initially tried running a Subversion server in a Docker container, and didn't have any luck with it
    - https://kevin.deldycke.com/2012/how-to-create-local-copy-svn-repository
        - Create an empty local SVN repository:
            ```shell
            rm -rf ./svn-repo
            svnadmin create ./svn-repo
            sed -i 's/# password-db = passwd/password-db = passwd/' ./svn-repo/conf/svnserve.conf
            echo "kevin = kevin" >> ./svn-repo/conf/passwd
            kill `ps -ef | grep svnserve | grep -v grep | awk '{print $2}'`
            svnserve --daemon --listen-port 3690 --root ./svn-repo
            ```
        - Give the synchronization utility permission on the local repository:
            ```shell
            echo "#!/bin/sh" > ./svn-repo/hooks/pre-revprop-change
            chmod 755 ./svn-repo/hooks/pre-revprop-change
            ```
        - Initialize the synchronization between the remote server `https://svn.example.com/svn/internal-project` and the local SVN `svn://localhost:3690`:
            ```shell
            svnsync init --sync-username "kevin" --sync-password "kevin" --source-username "kevin@example.com" --source-password "XXXXXX" svn://localhost:3690 https://svn.example.com/svn/internal-project
            ```
        - Once all of this configuration is done, we can start dumping the content of the remote repository to our local copy:
            ```shell
            svnsync --non-interactive --sync-username "kevin" --sync-password "kevin" --source-username "kevin@example.com" --source-password "XXXXXX" sync svn://localhost:3690
            ```


## Old Doc

- Need to clean this up, and put it somewhere

```yaml
xmlbeans:
# Usage: This key is used as the converted Git repo's name
# Required: Yes
# Format: String of YAML / git / filepath / URL-safe characters [A-Za-z0-9_-.]
# Default if unspecified: Invalid

  type:                 SVN
  # Usage: The type of repo to be converted, which determines the code path, binaries, and options used
  # Required: Yes
  # Format: String
  # Options: SVN, TFVC
  # Default if unspecified: Invalid

  url:   https://svn.apache.org/repos/asf/xmlbeans
  # Usage: The root of the Subversion repo to be converted to a Git repo, thus the root of the Git repo
  # Required: Yes
  # Format: URL
  # Default if unspecified: Invalid

  code-host-name:       svn.apache.org
  git-org-name:         asf
  # Usage: The Sourcegraph UI shows users the repo path as code-host-name/git-org-name/repo-name for ease of navigation, and the repos are stored on disk in the same tree structure
  # Required: Yes; this hasn't been tested without it, but it's highly encouraged for easier user navigation
  # Format: String of filepath / URL-safe characters [A-Za-z0-9_-.]
  # Default if unspecified: Empty

  username:             super_secret_username
  password:             super_secret_password
  # Usage: Username and password to authenticate to the code host
  # Required: If code host requires authentication
  # Format: String
  # Default if unspecified: Empty

  git-default-branch:   main
  # Usage: Sets the name of the default branch in the resulting git repo; this is the branch that Sourcegraph users will see first, and will be indexed by default
  # Required: No
  # Format: String, git branch name
  # Default if unspecified: main

  layout:               standard
  trunk:                trunk
  branches:             branches
  tags:                 tags
  # Usage: Match these to your Subversion repo's directory layout.
  # Use `layout: standard` by default when trunk, branches, and tags are all top level directories in the repo root
  # Or, specify the relative paths to these directories from the repo root
  # These values are just passed to the subversion CLI as command args
  # Required: Either layout or trunk, branches, tags
  # Formats:
    # trunk: String
    # branches: String, or list of strings
    # tags: String, or list of strings
  # Default if unspecified: layout:standard

  git-ignore-file-path: /path/mounted/inside/container/to/.gitignore
  authors-file-path:    /path/mounted/inside/container/to/authors-file-path
  authors-prog-path:    /path/mounted/inside/container/to/authors-prog-path
  # Usage: If you need to use .gitignore, an author's file, or an author's program in the repo conversion, then mount them as a volume to the container, and provide the in-container paths here
  # Required: No
  # Format: String, file path
  # Default if unspecified: empty

  bare-clone:           true
  # Usage: If you need to keep a checked out working copy of the latest commit on disk for debugging purposes, set this to false
  # Required: No
  # Format: String
  # Options: true, false
  # Default if unspecified: true
```