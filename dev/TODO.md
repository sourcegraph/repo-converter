# TODO:

1. Renew Entitle requests
2. Finish the structured logging, with repo / sync job details
    1. Job start, with batch size
    2. Each command start
    3. Each command finish, with results
    4. Job finish, with results, from each command, including total run time, run times for each step, and percents of total
3. Update customer production to gather log events on which repos take how long, and why

Ask Amp
- What does SVN log get used for?
- Why would it take so long to run?
- How do you suggest we work around this?
- Should we keep a local file to track commit metadata?


- Logging

    - Objective:
        - Make the code run faster in the customer's environment
    - How do we achieve this?
        - Identify which commands are taking a long time, and why
    - Okay, how?
        - Adopt structured logging, and a log parsing method to get this data

    - Amp's suggestion
        - Context Managers: Git operations and command execution use context managers to automatically inject relevant metadata for all logs within their scope.
        - Decorator Pattern: Command execution decorator automatically captures all command-related data (args, timing, stdout/stderr, exit codes).
        - The architecture uses a context stack pattern where different operational contexts (git operations, command execution) automatically push their metadata, making all relevant data available to every log statement within that context.

    - Get details pertinent to which events are emitting logs into structured log keys
        - Git Commands
            - Repo
            - Repo status (up to date / out of date)
            - Commits behind to catch up
            - Batch size
            - Local rev
            - Remote rev
            - Remote server response errors, ex. svn: E175012: Connection timed out

    - Build up log event context, ex. canonical logs, and be able to retrieve this context in cmd.log_process_status()

    - Sort keys in logs for process and psutils subdicts
        - Have plumbing, now need to see which attributes we're actually logging, sort them in the needed order

    - How to get process execution times from logs, and analyze them

    - Log a repo status update table?
        - Repo name
        - URL
        - Status (up to date / out of date)
        - Last run's status (success / fail / timeout)
        - Progress (% of commits)
        - Commits converted
        - Commits remaining
        - Total commits
        - Local commit
        - Remote commit
        - Size on disk
    - Find a way to output a whole stack trace for each ERROR (and higher) log event
    - Log structure to include file / line number, module / function names
        - Need to make this more useful
    - Find a tool to search / filter through logs
        - See Slack thread with Eng
    - Log levels
        - proc events in DEBUG logs make DEBUG level logging too noisy
        - Increase log levels of everything else?
        - Create a new lower log level named proc?
    - Debug log the list of servers and repos found in config file at the start of each run, so we can see it in the last ~1k log lines?

    - Set up log schema and workspace settings for RedHat's [YAML](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) VS Code extension

- SVN

    - `svn info` commands
        - Lightweight, takes a ~second to run
        - Tests connectivity and credentials

    - `svn log` commands
        - Longest commands, which seem to be timing out and causing issues
        - We may be able to make the conversion process much smoother if we can use fewer of these log commands
        - What do we use them for? Why?
            - Commit metadata
            -
        - these commands may be duplicative
        - This command is executed 3 times per sync job, which one is taking so long?

2025-07-01; 02:35:50.400278; aa7797a; 0a93e01bc45b; run 1; DEBUG; subprocess_run() starting process: svn log --xml --with-no-revprops --non-interactive https://svn.apache.org/repos/asf/crunch/site --revision 1:HEAD
2025-07-01; 02:35:51.983007; aa7797a; 0a93e01bc45b; run 1; DEBUG; subprocess_run() starting process: svn log --xml --with-no-revprops --non-interactive https://svn.apache.org/repos/asf/crunch/site --limit 1 --revision 1:HEAD
2025-07-01; 02:35:52.695285; aa7797a; 0a93e01bc45b; run 1; DEBUG; subprocess_run() starting process: svn log --xml --with-no-revprops --non-interactive https://svn.apache.org/repos/asf/crunch/site --limit 2 --revision 1377700:HEAD

2025-07-01; 15:09:44.641140; 924a81c; 3fef96dbf2ce; run 576; DEBUG; pid 101567; still running; running for 3:07:58.451094; psutils_process_dict: {'args': '', 'cmdline': ['svn', 'log', '--xml', '--with-no-revprops', '--non-interactive', 'https://svn.apache.org/repos/asf/lucene', '--revision', '1059418:HEAD'], 'cpu_times': pcputimes(user=471.92, system=0.45, children_user=0.0, children_system=0.0, iowait=0.0), 'memory_info': pmem(rss=11436032, vms=22106112, shared=9076736, text=323584, lib=0, data=2150400, dirty=0), 'memory_percent': 0.13784979013949392, 'name': 'svn', 'net_connections_count': 1, 'net_connections': '13.90.137.153:443:CLOSE_WAIT', 'num_fds': 5, 'open_files': [], 'pid': 101567, 'ppid': 101556, 'status': 'running', 'threads': [pthread(id=101567, user_time=471.92, system_time=0.45)]};


        - Add new routine to run git log and svn log, to compare and ensure that each of the SVN revision numbers is found in the git log, and raise an error if any are missing or out of order

        - Keep an svn log file in a .git/sourcegraph directory in each repo
        - When to run the next svn log file? When the last commit ID number in the svn log file has been converted
        - Can SVN repo history be changed? Would we need to re-run svn log periodically to update the local log file cache?
        - Do we need to keep a log file of svn commands, svn server URL, repo name, execution times, response codes, response size?
        - Run git svn log --xml to store the repo's log on disk, then append to it when there are new revisions, so getting counts of revisions in each repo is slow once, fast many times
        - XML parsing library to store and update a local subversion log file?


- repos-to-convert.yaml

    - Move the config validation schema to a separate YAML file, bake it into image, read it into Context on container startup, and provide for each field:
        - Name
        - Description
        - Valid parents (global / server / repo)
        - Valid types
        - Required? (ex. either repo-url or repo-parent-url)
        - Usage
        - Examples
        - Default values

    - Create server-specific concurrency semaphore from repos-to-convert value, if present

    - Add parent key to repos-to-convert sanitizer, so child keys can be validated that they're under a valid parent key

    - Add a fetch-interval-seconds config to repos-to-convert.yaml file
        - under the server config
        - for each repo in the repos_dict
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
            - Doing this before forking the process reduces zombies and debug process log noise
        - convert_svn_repo
            - Set the next fetch time to None, so the forking loop doesn't fork again for this repo fetch interval
                - repo_key[next-fetch-time] = None
            - Check if this repo has a fetch interval defined
                - fetch_interval_seconds = repo_key.get(fetch-interval-seconds, None)
                - If yes, calculate and store the next fetch time
                - If fetch_interval_seconds
                    - repo_key[next-fetch-time] = fetch_interval_seconds + time.now()
    - Create env var for a map so creds don't need to be stored in files
        - server
        - username
        - password
    - Env vars vs config file
        - Read as many configs from repos-to-convert.yaml as we can, so the values can be changed without restarting the container
        - Env vars
            - Service-oriented, ex. log level
            - Cannot change without restarting the container
            - Secrets
        - repos-to-convert.yaml
            - List of repos to convert
            - Can change without restarting the container

- SVN
    - Try to add the batch size to the svn log command to speed it up
    - SVN commands hanging
        - Add a timeout in run_subprocess() for hanging svn info and svn log commands, if data isn't transferring
    - .gitignore files
        - git svn create-ignore
        - git svn show-ignore
        - https://git-scm.com/docs/git-svn#Documentation/git-svn.txt-emcreate-ignoreem
    - Test layout tags and branches as lists / arrays
    - If list of repos is blank in repos-to-convert, try and parse the list from the server?


    - Need to integrate subprocess methods together
        - State tracking, in ctx.child_procs = {}
        - Clean up of process state
    - Add to the process status check and cleanup function to
        - get the last lines of stdout from a running process,
        - instead of just wait with a timeout of 0.1,
        - use communicate() with a timeout and read the stdout from the return value,
        - catch the timeout exception
        - May require tracking process objects in a dict, which would prevent processes from getting auto-cleaned, resulting in higher zombie numbers

- Builds
    - Local builds
        - Not sure why the build is failing, trying to communicate to a closed socket, like the machine's API service died, but the machine is still running
```shell
Running podman build
+ podman build --file ./Dockerfile --format docker --jobs 0 --label 'org.opencontainers.image.created=2025-06-18 03:50:14 UTC' --label org.opencontainers.image.revision=fab91e6 --tag repo-converter:build ..
ERRO[0007] 1 error occurred:
        * lstat .../repo-converter/src-serve-root/svn.apache.org/asf/cocoon/.git/svn/refs/remotes/git-svn/index.lock: no such file or directory
Error: Post "http://d/v5.5.1/libpod/build?...": io: read/write on closed pipe
```
        - Next time it happens, Activity Monitor to see if it's using all of its memory
        - If they fail with weird messages, try podman machine commands:
            - list
            - info
            - set
            - stop
            - start
            - reset
            - init
            - inspect - Not super useful
```shell
[2025-06-17 21:52:49] build % podman machine list
NAME                     VM TYPE     CREATED      LAST UP            CPUS        MEMORY      DISK SIZE
podman-machine-default*  applehv     2 weeks ago  Currently running  5           8GiB        100GiB
[2025-06-17 21:55:18] build % podman machine info
host:
    arch: arm64
    currentmachine: podman-machine-default
    defaultmachine: podman-machine-default
    eventsdir: /var/folders/_m/lt7_4g3x12q5jlrss_vdj4140000gn/T/storage-run-501/podman
    machineconfigdir: ~/.config/containers/podman/machine/applehv
    machineimagedir: ~/.local/share/containers/podman/machine/applehv
    machinestate: Running
    numberofmachines: 1
    os: darwin
    vmtype: applehv
version:
    apiversion: 5.5.1
    version: 5.5.1
    goversion: go1.24.4
    gitcommit: ""
    builttime: Thu Jun  5 12:25:35 2025
    built: 1749147935
    buildorigin: brew
    osarch: darwin/arm64
    os: darwin

[2025-06-17 21:55:25] build % podman machine inspect
[
     {
          "ConfigDir": {
               "Path": "~/.config/containers/podman/machine/applehv"
          },
          "ConnectionInfo": {
               "PodmanSocket": {
                    "Path": "/var/folders/_m/lt7_4g3x12q5jlrss_vdj4140000gn/T/podman/podman-machine-default-api.sock"
               },
               "PodmanPipe": null
          },
          "Created": "2025-05-30T18:40:55.226032-06:00",
          "LastUp": "2025-06-17T17:22:06.514173-06:00",
          "Name": "podman-machine-default",
          "Resources": {
               "CPUs": 5,
               "DiskSize": 100,
               "Memory": 8192,
               "USBs": []
          },
          "SSHConfig": {
               "IdentityPath": "~/.local/share/containers/podman/machine/machine",
               "Port": 62020,
               "RemoteUsername": "core"
          },
          "State": "running",
          "UserModeNetworking": true,
          "Rootful": false,
          "Rosetta": true
     }
]
```
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
    - Wolfi base image for Docker / podman build
    - Container runAs user
        - src serve-git and repo-converter both run as root, which is not ideal
        - Need to create a new user on the host, add it to the host's sourcegraph group, get the UID, and configure the runAs user for the containers with this UID

- Add git-to-p4 converter
    - Run it in MSP, to build up our Perforce test depots from public OSS repos

- Switch zombie process cleanup / running process checker to the same logic as concurrency_monitor, in its own thread, on its own interval?

- Git clone
    - SSH clone
        - Move git SSH clone from outside bash script into this script
        - See if the GitPython module fetches the repo successfully, or has a way to clone multiple branches
            - Fetch (just the default branch)
            - Fetch all branches
            - Clone all branches
        - From the git remote --help
            - Imitate git clone but track only selected branches
            -     mkdir project.git
            -     cd project.git
            -     git init
            -     git remote add -f -t master -m master origin git://example.com/git.git/
            -     git merge origin

# Notes:

    - Add doc strings for each function
        - https://www.dataquest.io/blog/documenting-in-python-with-docstrings

    - authors file
        - java -jar /sourcegraph/svn-migration-scripts.jar authors https://svn.apache.org/repos/asf/eagle > authors.txt
        - Kinda useful, surprisingly fast

    - git list all config
        - git -C $local_repo_path config --list

    - Decent example of converting commit messages
        - https://github.com/seantis/git-svn-trac/blob/master/git-svn-trac.py
