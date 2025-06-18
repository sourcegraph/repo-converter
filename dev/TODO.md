# TODO:

- repos-to-convert.yaml
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

- SVN
    - `svn log` commands
        - longest commands which seem to be timing out and causing issues are the svn log commands, which just return commit metadata
        - these commands may be duplicative
        - We may be able to make the conversion process much smoother if we can use fewer of these log commands
        - Keep an svn log file in a .git/sourcegraph directory in each repo
        - When to run the next svn log file? When the last commit ID number in the svn log file has been converted
        - Can SVN repo history be changed? Would we need to re-run svn log periodically to update the local log file cache?
        - Do we need to keep a log file of svn commands, svn server URL, repo name, execution times, response codes, response size?
        - Run git svn log --xml to store the repo's log on disk, then append to it when there are new revisions, so getting counts of revisions in each repo is slow once, fast many times
    - Try to add the batch size to the svn log command to speed it up
    - SVN commands hanging
        - Add a timeout in run_subprocess() for hanging svn info and svn log commands, if data isn't transferring
    - .gitignore files
        - git svn create-ignore
        - git svn show-ignore
        - https://git-scm.com/docs/git-svn#Documentation/git-svn.txt-emcreate-ignoreem
    - Test layout tags and branches as lists / arrays
    - If list of repos is blank in repos-to-convert, try and parse the list from the server?

- Process management
    - Found the repo-converter container dead after 691 runs, with no evidence as to why it died in the container logs
        - Next time this happens, run podman inspect <container ID>, and review state info
        - Try to get all the logs / events from the container / pod, to find why it died
        - How to have the container emit a message while it's dying?
    - Need to integrate subprocess methods together
        - State tracking, in ctx.child_procs = {}
        - Cleanup of zombie processes
        - Clean up of process state
    - Learn more about multiprocessing pools
    - Library to cleanup zombie processes, or how does Amp suggest we manage zombies?
    - Is psutils necessary?
        - May not have had a recent release, may need to replace it
        - Requires adding gcc to the Docker image build, which adds ~4 minutes to the build time, and doubles the image size
        - It would be handy if there was a workaround without it, but multiprocessing.active_children() doesn't join the intermediate processes that Python forks
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

- Logging
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
    - Switch to structured (i.e. JSON) logs?
    - Find a tool to search / filter through logs
    - Log levels
        - proc events in DEBUG logs make DEBUG level logging too noisy
        - Increase log levels of everything else?
        - Create a new lower log level named proc?
    - Debug log the list of servers and repos found in config file at the start of each run, so we can see it in the last ~1k log lines?

- Add git-to-p4 converter
    - Run it in MSP, to build up our Perforce test depots from public OSS repos

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
