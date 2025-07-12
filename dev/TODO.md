# TODO

## Logging

- Objective:
    - Make the conversion process go faster, and more stable, in the customer's environment
- How do we achieve this?
    - Identify which commands are taking a long time, or failing, and why
- Okay, how?
    - Done
        - Implement structured logging
        - Update customer production
        - Collect log events
        - Query log events from JSON lines to CSV, using `dev/query_logs.py`
        - Analyze log events to understand which commands are taking the longest (`svn log`, by a mile)
    - In Progress
        - Implement a better way to run the `svn log` command, to take less time
    - To Do
        - Analyze failure events:
            - Which commands are failing most?
            - Why?

- Find a tool to search / filter through logs
    - See Slack thread with Eng
    - Amped the `dev/query_logs.py` script in the meantime

- Build up log event context, ex. canonical logs, and be able to retrieve this context in cmd.log_process_status()

- Enhance error events with automatic error context capture and correlation IDs
    - Remote server response errors, ex. svn: E175012: Connection timed out
    - Decorators and context managers for logging context?

- Log a repo status event at the end of the svn.py module
    - Repo_key
    - Status (up to date / out of date)
    - Last run's status (success / fail)
    - Progress (% of revs converted)
    - Revs converted
    - Revs remaining
    - Total revs
    - Local current rev
    - Remote current rev
    - Converted repo's size on disk

- Amp's suggestion
    - Context Managers: Git operations and command execution use context managers to automatically inject relevant metadata for all logs within their scope.
    - Decorator Pattern: Command execution decorator automatically captures all command-related data (args, timing, stdout/stderr, exit codes).
    - This architecture uses a context stack pattern where different operational contexts (git operations, command execution) automatically push their metadata, making all relevant data available to every log statement within that context.

- Set up log schema and workspace settings for RedHat's [YAML](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) VS Code extension

## SVN

### Stability

- `svn log` commands
    - Longest commands, which seem to be timing out and causing issues
    - We may be able to make the conversion process much smoother if we can use fewer of these log commands
    - What do we use them for? Why?
        - Get first commit for a new repo
        - Get last commit number for a batch range
    - These commands may be duplicative?
    - This command is executed 3 times per sync job, which one is taking so long?

```log
2025-07-01; 02:35:50.400278; aa7797a; 0a93e01bc45b; run 1; DEBUG; subprocess_run() starting process: svn log --xml --with-no-revprops --non-interactive https://svn.apache.org/repos/asf/crunch/site --revision 1:HEAD
2025-07-01; 02:35:51.983007; aa7797a; 0a93e01bc45b; run 1; DEBUG; subprocess_run() starting process: svn log --xml --with-no-revprops --non-interactive https://svn.apache.org/repos/asf/crunch/site --limit 1 --revision 1:HEAD
2025-07-01; 02:35:52.695285; aa7797a; 0a93e01bc45b; run 1; DEBUG; subprocess_run() starting process: svn log --xml --with-no-revprops --non-interactive https://svn.apache.org/repos/asf/crunch/site --limit 2 --revision 1377700:HEAD

2025-07-01; 15:09:44.641140; 924a81c; 3fef96dbf2ce; run 576; DEBUG; pid 101567; still running; running for 3:07:58.451094; psutils_process_dict: {'args': '', 'cmdline': ['svn', 'log', '--xml', '--with-no-revprops', '--non-interactive', 'https://svn.apache.org/repos/asf/lucene', '--revision', '1059418:HEAD'], 'cpu_times': pcputimes(user=471.92, system=0.45, children_user=0.0, children_system=0.0, iowait=0.0), 'memory_info': pmem(rss=11436032, vms=22106112, shared=9076736, text=323584, lib=0, data=2150400, dirty=0), 'memory_percent': 0.13784979013949392, 'name': 'svn', 'net_connections_count': 1, 'net_connections': '13.90.137.153:443:CLOSE_WAIT', 'num_fds': 5, 'open_files': [], 'pid': 101567, 'ppid': 101556, 'status': 'running', 'threads': [pthread(id=101567, user_time=471.92, system_time=0.45)]};
```

- Keep the output revision numbers from `git svn log --xml` commands in a file on disk, then append to it when there are new revisions, so getting counts of revisions in each repo is slow once, fast many times
    - Use an XML parsing library or regex matches to extract revision numbers, but store as JSON in the file
- Compare svn log file against `git log` output, to ensure that each of the SVN revision numbers is found in the git log, and raise an error if any are missing or out of order
- When to run the next svn log command? When the last commit ID number in the svn log file has been converted
    - Can SVN repo history be changed? Would we need to re-run svn log periodically to update the local log file?

- Implement more accurate conversion job success validation before updating git config with latest rev
- Break down `convert()` into smaller, focused methods
- Improve state management / switching for create / update / running
- Add better error handling for subcommands with specific error types
- Use GitPython more extensively?

### Performance

- Fix batch processing logic
- SVN commands hanging
    - Add a timeout in run_subprocess() for hanging svn info and svn log commands, if data isn't transferring

- Different approach: Sync SVN-to-SVN, then convert from local SVN server
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
    - Initialize the synchronization between the remote server (https://svn.example.com/svn/internal-project) and the local SVN (svn://localhost:3690):
        ```shell
        svnsync init --sync-username "kevin" --sync-password "kevin" --source-username "kevin@example.com" --source-password "XXXXXX" svn://localhost:3690 https://svn.example.com/svn/internal-project
        ```
    - Once all of this configuration is done, we can start dumping the content of the remote repository to our local copy:
        ```shell
        svnsync --non-interactive --sync-username "kevin" --sync-password "kevin" --source-username "kevin@example.com" --source-password "XXXXXX" sync svn://localhost:3690
        ```

### Other

- .gitignore files
    - `git svn create-ignore`
    - `git svn show-ignore`
    - https://git-scm.com/docs/git-svn#Documentation/git-svn.txt-emcreate-ignoreem
- Test layout tags and branches as lists / arrays
- If list of repos is blank in repos-to-convert, try and parse the list from the server?

## Config

- Move the config schema to a separate YAML file, bake it into the image, read it into Context on container startup, and provide for each field:
    - Name
    - Description
    - Default values
    - Valid data types
    - Required? (ex. either repo-url or repo-parent-url)
    - Valid parents (global / server / repo), so child keys can be validated that they're under a valid parent key
    - Usage
    - Examples

- Make `repos_to_convert_fields` a part of Context, so the `sanitize_repos_to_convert` function can save it, to make it available to `check_required_fields`

- Implement proper type validation with clear error messages for config file inputs

- Create server-specific concurrency semaphore from repos-to-convert value, if present

- Add a fetch-interval-seconds config to repos-to-convert.yaml file
    - Under global, server, or repo config
    - For each repo in the repos_dict
        - Add a "next sync time" field in the dict
    - convert_svn_repos loop
        - Try and read it
                - next_fetch_time = repo_key.get(next-fetch-time, None)
        - If it's defined and in the future, skip this run
            - if next_fetch_time
                - if next_fetch_time >= time.now()
                    - Log.debug(repo_key next fetch time is: yyyy-mm-dd HH:MM:SS, skipping)
                    - continue
                - Else
                    - Log.debug(repo_key next fetch time was: yyyy-mm-dd HH:MM:SS, fetching)
        - Doing this before forking the process reduces zombies and debug process log noise for repos which are already up to date, and don’t get a ton of commits
    - convert_svn_repo
        - Set the next fetch time to None, so the forking loop doesn't fork again for this repo fetch interval
            - repo_key[next-fetch-time] = None
        - Check if this repo has a fetch interval defined
            - fetch_interval_seconds = repo_key.get(fetch-interval-seconds, None)
            - If yes, calculate and store the next fetch time
            - If fetch_interval_seconds
                - repo_key[next-fetch-time] = fetch_interval_seconds + time.now()

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

## Processes

- How do I get more information about the child PID which was reaped in these lines, in `./src/utils/signal_handler.py`?
    ```python
    if os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0:
        log(ctx, f"SIGCHLD handler reaped child PID {pid} with exit code {os.WEXITSTATUS(status)}", "warning")
    ```
    - Maintain a list of processes, with their metadata, from when they're launched, and updated on an interval, then look up that information in the signal handler
        - Track PIDs when launching: Store process metadata (command, start time, purpose) in a dict when creating child processes
        - Cross-reference with active processes: Check if the PID exists in ctx.active_repo_conversion_processes
    - Use process monitoring libraries

- Multiprocessing / state / zombie cleanup
    - Learn more about multiprocessing pools
    - Implement better multiprocessing status and state tracking
    - Integrate subprocess methods together
        - State tracking, in ctx.child_procs = {}
        - Cleanup of zombie processes
        - Clean up of process state
    - Improve zombie process detection and cleanup
        - Library to cleanup zombie processes, or how does Amp suggest we manage zombies?

- Add to the process status check and cleanup function to
    - Get the last lines of stdout from a running process,
    - instead of just wait with a timeout of 0.1,
    - use communicate() with a timeout and read the stdout from the return value,
    - catch the timeout exception
    - May require tracking process objects in a dict, which would prevent processes from getting auto-cleaned, which may result in higher zombie numbers

- Implement better error handling for process management

## Builds

- GitHub Action build tags
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
            -
        - Push (merge) to main
            -
        - Tag / release
            -
        - workflow_dispatch
            - gha-env-vars-workflow-dispatch.sh
- Wolfi Python base image for Docker / podman build
- Container runAs user
    - src serve-git and repo-converter both run as root, which is not ideal
    - Need to create a new user on the host, add it to the host's sourcegraph group, get the UID, and configure the runAs user for the containers with this UID

## Dev

- Add proper doc strings to all classes and methods
    - https://www.dataquest.io/blog/documenting-in-python-with-docstrings


## Expansion

- Implement TODOs strewn around the code

- Add git-to-p4 converter
    - Run it in MSP, to build up our Perforce test depots from public OSS repos

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
