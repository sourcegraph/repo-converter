# TODO

## Observability

- Copy the `repo_key` attribute up, between `message` and `log_level`
    - Then remove `f"{repo_key};` from log event calls

- Only print code / container / process / etc. sections of the log events if `log_level==DEBUG`

- Add PID and PPID to all debug log events
    - Does the log function run from the same PID as the caller?

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
        - For each HTTP request to the Subversion server, the number of revs to query for
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
        - Required? (ex. either repo-url or repo-parent-url)
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

- SVN commands hanging
    - Add a timeout in run_subprocess() for hanging svn info ~~and svn log~~ commands, if data isn't transferring
        - Does the svn cli not have a timeout built in for this command?

- PID layers, from `docker exec -it repo-converter top`
    - This output was captured 14 hours into converting a repo that's up to 2 GB on disk so far, with 6 years of history left to catch up on
    - This is after removing our batch processing bubble-wrap, and just lettin'er buck
    ```
        PID    PPID nTH S   CODE   USED   SWAP    RES  %MEM nMaj nMin nDRT  OOMa OOMs  %CPU     TIME+ COMMAND
          1       0   2 S   2.7m  37.4m   1.5m  35.9m   0.5  991 8.7m    0     0  668   0.0   2:44.22 /usr/bin/python3 /sg/repo-converter/src/main.py
         85       1   1 S   2.7m  40.8m  11.6m  29.2m   0.4    0  20k    0     0  669   0.0   0:05.82  `- /usr/bin/python3 /sg/repo-converter/src/main.py
        330      85   1 S   2.7m   1.4m   0.2m   1.2m   0.0    0  364    0     0  666   0.0   0:00.00      `- git -C /sg/src-serve-root/org/repo svn fetch --quiet --username user --log-window-size 100
        331     330   1 S   1.6m 115.6m  17.8m  97.8m   1.2   56 534m    0     0  674  13.6  66:17.92          `- /usr/bin/perl /usr/lib/git-core/git-svn fetch --quiet --username user --log-window-size 100
        376     331   1 S   2.7m   1.1g   0.1m   1.1g  14.6  18k 1.4m    0     0  744   0.3   1:18.22              `- git cat-file --batch
      34015     331   1 S   2.7m  10.0m   0.0m  10.0m   0.1   17 889k    0     0  667   2.0   4:36.38              `- git hash-object -w --stdin-paths --no-filters
    1850259     331   1 S   2.7m   5.1m   0.0m   5.1m   0.1    0  499    0     0  666   0.0   0:00.00              `- git update-index -z --index-info
    ```
    - PID 1
        - Docker container entrypoint
    - PID 85
        - Spawned by `multiprocessing.Process().start()` in `convert_repos.start()`
    - PID 330
        - Spawned by `psutil.Popen()` in `cmd.run_subprocess()`
        - `git svn fetch` command, called from `_git_svn_fetch()` in `svn.convert()`
    - PID 331
        - `git-svn` perl script, which runs the `git svn fetch` workload in [sub fetch, in SVN.pm](https://github.com/git/git/blob/v2.50.1/perl/Git/SVN.pm#L2052)
        - This script is quite naive, no retries, always exits 0, even on failures
    - PID 376
        - Long-running `git cat-file` process, which stores converted content in memory
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
        - Multiprocessing cleanup fails: The FileNotFoundError at line 100 indicates the multiprocessing manager's socket connection was already closed when trying to access self.active_jobs[server_name]
    - Root Causes
        - Non-reentrant signal handling: The signal handler isn't designed to handle recursive calls safely
        - Race condition: The multiprocessing manager shuts down before all processes finish cleanup
        - Signal propagation: os.killpg() creates a cascade of signals across the process group
    - The application does eventually shut down gracefully, but the multiple signal receptions and stack traces indicate the shutdown process could be more robust.

- Multiprocessing / state / zombie cleanup
    - Implement better multiprocessing status and state tracking
        - Multiprocessing pools?
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

## Notes

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