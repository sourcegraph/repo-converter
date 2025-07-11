# repo-converter

## Experimental - This is not a supported Sourcegraph product
This repo was created for Sourcegraph Implementation Engineering deployments, and is not intended, designed, built, or supported for use in any other scenario. Feel free to open issues or PRs, but responses are best effort.

## Why
- Sourcegraph was built with Git-native support, but customers have a variety of version control systems
- Sourcegraph has integrated the p4-fusion FOSS project into the product to support Perforce more directly
- Other version control systems are left up to the customer to convert to Git
- This project builds a framework to convert repos from other VCS to Git

## Deployment
For Sourcegraph Cloud customers, they'll need to run the repo-converter, src serve-git, and the Sourcegraph Cloud Private Access Agent on a container platform with connectivity to both their code hosts, and their Sourcegraph Cloud instance. This can be done quite securely, as the src serve-git API endpoint does not need any ports exposed outside of the container network Running src serve-git and the agent together on the same container network allows the agent to use the container platform's local DNS service to reach src serve-git, and prevents src serve-git's unauthenticated HTTP endpoint from needing to be opened outside of the container network.

For Self-hosted Sourcegraph customers, they'll need to run the repo-converter and src serve-git together in a location that can reach their code hosts, and their Sourcegraph instance can reach the src serve-git API.

The repo-converter and src serve-git containers need to share a storage volume, as repo-converter stores the cloned Git repos locally, and src serve-git serves them to the Sourcegraph instance from the same storage volume.

Deploying via containers allows for easier upgrades, troubleshooting, monitoring, logging, flexibility of hosting, etc. than running the binaries directly on the OS.

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
        1. Future, depending on availability of third party TFVC API clients

## Setup with Sourcegraph Cloud - Sourcegraph Staff Only
1. Add the needed entries to the sourcegraphConnect targetGroups list in the Cloud instance's config.yaml, and get your PR approved and merged
```yaml
        - dnsName: src-serve-git-ubuntu.local
          listeningAddress: 100.100.100.0
          name: src-serve-git-ubuntu-local
          ports:
          - 443
        - dnsName: src-serve-git-wsl.local
          listeningAddress: 100.100.100.1
          name: src-serve-git-wsl-local
          ports:
          - 443
```
2. Clone this repo to a VM on the customer's network, and either install Docker and Docker's Compose plugin, or connect to a container platform
3. Copy the `config.yaml` and `service-account-key.json` files using the instructions on the instance's Cloud Ops dashboard
    - Paste them into `./config/cloud-agent-config.yaml` and `./config/cloud-agent-service-account-key.json`
4. Modify the contents of the `./config/cloud-agent-config.yaml` file:
    - `serviceAccountKeyFile: /sourcegraph/cloud-agent-service-account-key.json` so that the Go binary inside the agent container finds this file in the path that's mapped via the docker-compose.yaml files
    - Only include the `- dialAddress` entries that this cloud agent instance can reach, remove the others, so the Cloud instance doesn't try using this agent instance for code hosts it can't reach
    - Use extra caution when pasting the config.yaml in Windows, as it may use Windows' line endings or extra spaces, which breaks YAML, as a whitespace-dependent format
5. Run `docker compose up -d`
6. Add a Code Host config to the customer's Cloud instance
    - Type: src serve-git
    - `"url": "http://src-serve-git-ubuntu.local:443",`
    - or
    - `"url": "http://src-serve-git-wsl.local:443",`
    - Note the port 443, even when used with http://
7. Use the repo-converter to convert SVN, TFVC, or Git repos, to Git format, which will store them in the `src-serve-root` directory, or use any other means to get the repos into the directory
    - There are docker-compose.yaml and override files in a few different directories in this repo, separated by use case, so that each use case only needs to run `docker compose up -d` in one directory, and not fuss around with `-f` paths.
    - The only difference between the docker-compose-override.yaml files in host-ubuntu vs host-wsl is the src-serve-git container's name, which is how we get a separate `dnsName` for each.
    - If you're using the repo-converter:
        - If you're using the pre-built images, `cd ./deploy && docker compose up -d`
        - If you're building the Docker images, `cd ./build && docker compose up -d --build`
        - Either of these will start all 3 containers: cloud-agent, src-serve-git, and the repo-converter


## Configuration

### Environment Variables
- Env vars are used for configs which need the container to restart to get new values

### ./config/repos-to-convert.yaml
- The contents of this file can be changed while the container is running, and the current version will be read at the start of each main loop in main.py
- Note, the syntax in the below examples is quite out of date, but the explanations of each may still be useful

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
  fetch-batch-size: 1000
```