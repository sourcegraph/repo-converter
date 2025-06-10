# Repo Converter

## Experimental - This is not a supported Sourcegraph product
This repo was created for Sourcegraph Implementation Engineering deployments and Managed Services, and is not intended, designed, built, or supported for use in any other scenario. Feel free to open issues or PRs, but responses are best effort.

## Why
Provides a framework to convert non-Git repos into Git format, and in combination with src serve-git (and optionally the Sourcegraph Cloud Private Connect Agent for Sourcegraph Cloud customers), provide a code host endpoint for the customer's Sourcegraph instance to clone the converted repos from.

## Requirements
1. Container host
    1. Docker Compose or Kubernetes
    2. Networking
        1. Has outbound connectivity to the code hosts
        2. Has outbound connectivity to the Sourcegraph Cloud instance (for Cloud customers)
        3. Has inbound connectivity from the Sourcegraph instance (for self-hosted customers)
    3. Storage
        1. Docker volume / Kubernetes persistent volume
        3. SSD with low latency random writes
        2. 2x the original repos' sum total size
    4. CPU
        1. The container runs a separate repo conversion process for each repo, in parallel, so maximum performance during the initial conversion process can be achieved with at least 1 thread or core for each repo in scope for conversion, plus threads for overhead
        2. Repo conversion speed is more I/O-bound than CPU or memory
    5. Memory
        1. ~ 1 GB / repo to be converted in parallel
        2. Depends on the size of the largest commit
        3. `run.py` doesn't handle the repo content; this is handled by the git and subversion CLIs
2. Code host
    1. Subversion
        1. HTTP(S)
        2. Username and password for a user account that has read access to the needed repos
        3. Support for SSH authentication hasn't been built, but could just be a matter of mounting the key, and not providing a username / password
    2. TFVC (Microsoft Team Foundation Version Control)
        1. Coming soon


## Setup

### Docker Compose
1. Clone this repo to a VM that meets the [Requirements](#requirements)
2. Install Docker and Docker's Compose plugin
3. Copy the `./config/example-repos-to-convert.yaml` file to `./config/repos-to-convert.yaml`
4. Modify the contents of the `./config/repos-to-convert.yaml` file:
    - Refer to the contents of the `input_value_types_dict` [here](https://sourcegraph.com/search?q=repo:%5Egithub%5C.com/sourcegraph/implementation-bridges$+input_value_types_dict) for the config parameters available, and the required value types
    - Note that if your code host requires credentials, the current version of this requires the credentials to be stored in this file; this file could be managed as a Docker Compose secret
    - Use extra caution when pasting the YAML files in Windows, as it may use Windows' line endings or extra spaces, which breaks YAML, as a whitespace-dependent format
5. You / we may need to write a new `docker-compose.yaml` file if you need to expose the src serve-git port outside the host / Docker network, without using the Cloud Private Connect Agent
    - There are docker-compose.yaml and override files in a few different directories in this repo, separated by use case, so that each use case only needs to run `docker compose up -d` in one directory, and not fuss around with `-f` paths.
    - The only difference between the docker-compose-override.yaml files in host-ubuntu vs host-wsl is the src-serve-git container's name, which is how we get a separate `dnsName` for each.
    - The `LOG_LEVEL` environment variable should be left undefined to use the default `INFO` in most cases; `DEBUG` is mostly just for visibility on subprocesses getting forked and cleaned up
6. Run `docker compose up -d`
7. Add a Code Host config to the customer's Cloud instance
    - Type: src serve-git
    - `"url": "http://src-serve-git-ubuntu.local:443",`
        - Match the src serve-git container's Docker container name and listening port number from the `docker-compose.yaml`
8. The repo-converter will output the converted repos in the `src-serve-root` directory, where src serve-git will serve them from

### Kubernetes
Coming soon

## Configuration
This will change in coming releases

### Environment Variables
Will likely be moved / made available in the `repos-to-convert.yaml` file

```YAML
# docker-compose.yaml
services:
  repo-converter:
    environment:
      - REPO_CONVERTER_INTERVAL_SECONDS=3600
        # Usage: how often `run.py` will check if a conversion task is already running for each repo, and start one if not already running
        # Required: No
        # Format: Int > 0
        # Default if unspecified: 3600
      - LOG_LEVEL=INFO
        # Usage: Configures the verbosity of repo-converter container logs
        # Required: No
        # Format: String
        # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
        # Default if unspecified: INFO
```

### repos-to-convert.yaml
This is the primary configuration method

```YAML
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

  svn-repo-code-root:   https://svn.apache.org/repos/asf/xmlbeans
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

  fetch-batch-size:     100
  # Usage: Number of Subversion changesets to try converting each batch; configure a higher number for initial cloning and for repos which get more than 100 changesets per REPO_CONVERTER_INTERVAL_SECONDS
  # Required: No
  # Format: Int > 0
  # Default if unspecified: 100

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


## Performance
1. The default interval and batch size are set for sane polling for new repo commits during regular operations, but would be quite slow for initial cloning
2. For initial cloning, adjust:
    1. The `REPO_CONVERTER_INTERVAL_SECONDS` environment variable
        1. This is the outer loop interval, how often `run.py` will check if a conversion task is already running for the repo, and start one if not already running
        2. Thus, the longest break between two batches would be the length of this interval
        3. Try 60 seconds, and adjust based on your source code host performance load
    2. The `fetch-batch-size` config for each repo in the `./config/repos-to-convert.yaml` file
        1. This is the number of commits the converter will try and convert in each execution. Larger batches can be more efficient as there are fewer breaks between intervals and less batch handling, however, if a batch fails, then it may need to retry a larger batch
        2. Try 1000 for larger repos, and adjust for each repo as needed

```YAML
# docker-compose.yaml
services:
  repo-converter:
    environment:
      - REPO_CONVERTER_INTERVAL_SECONDS=60
```

```YAML
# config/repos-to-convert.yaml
allura:
  type: SVN
  svn-repo-code-root: https://svn.apache.org/repos/asf/allura
  code-host-name: svn.apache.org
  git-org-name: asf
  fetch-batch-size: 1000
```