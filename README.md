# repo-converter

## Experimental - This is not a supported Sourcegraph product

This repo was created for Sourcegraph Implementation Engineering deployments, and is not intended, designed, built, or supported for use in any other scenario. Feel free to open issues or PRs, but responses are best effort.

## Why

- Sourcegraph was built with Git-native support, but customers have a variety of version control systems
- Sourcegraph has integrated the p4-fusion FOSS project into the product to support Perforce more directly
- Other version control systems are left up to the customer to convert to Git
- This project builds a framework to convert repos from other VCSes to Git

## Deployment

For Sourcegraph Cloud customers, they'll need to run the repo-converter, src serve-git, and the Sourcegraph Cloud Private Access Agent on a container platform with connectivity to both their Sourcegraph Cloud instance, and their code hosts. This can be done quite securely, as the src serve-git API endpoint does not need any ports exposed outside of the container network Running src serve-git and the agent together on the same container network allows the agent to use the container platform's local DNS service to reach src serve-git, and prevents src serve-git's unauthenticated HTTP endpoint from needing to be opened outside of the container network.

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
        1. The container runs a separate repo conversion process for each repo, in parallel, so maximum performance during the initial conversion process can be achieved with at least 1 thread or core for each repo in scope for conversion
        2. Repo conversion speed is more network-bound than CPU or memory
    5. Memory
        1. ~1 GB / repo to be converted in parallel
        2. Depends on the size of the largest commit, as `git svn fetch` seems to hold entire commits' contents in memory, and the number of parallel jobs
2. Code host
    1. Subversion
        1. HTTP(S)
        2. Username and password for a user account that has read access to the needed repos
    2. TFVC (Microsoft Team Foundation Version Control)
        1. Future, depending on availability of TFVC API clients

## Setup with Sourcegraph Cloud - Sourcegraph Staff Only

1. Follow the SG Cloud team's documentation to add the needed entries to the sourcegraphConnect targetGroups list in the Cloud instance's config.yaml, and get your PR approved and merged
2. Clone this repo to a VM on the customer's network, and either install Docker and Docker's Compose plugin, or connect to a container platform
3. Copy the `config.yaml` and `service-account-key.json` files using the instructions on the instance's Cloud Ops dashboard
    - Save them in the `./config/cloud-agent/` directory
4. Modify the contents of the `./config/cloud-agent/config.yaml` file:
    - `serviceAccountKeyFile: /sg/config/service-account-key.json` so the Go binary inside the agent container finds this file in the path as it's mapped via the docker-compose.yaml files
    - Only include the `- dialAddress` entries that this cloud agent instance can reach, remove the others, so the Cloud instance doesn't try using this agent instance for code hosts it can't reach
    - Use extra caution when pasting the `config.yaml` file in Windows, as it may use Windows' line endings or extra spaces, which breaks YAML, as a whitespace-dependent format
5. Run `docker compose up -d`
6. Add a Code Host config to the customer's Cloud instance
    - Type: src serve-git
    - The url is the name of the container, ex.
      - `"url": "http://src-serve-git-ubuntu.local:443",`
      - `"url": "http://src-serve-git-wsl.local:443",`
    - Note the port 443, even when used with http://
7. Use the repo-converter to convert SVN, ~~TFVC, or Git repos,~~ to Git format, which will store them in the `../src-serve-root` directory, or use any other means to get the repos into the directory

## Configuration

### Environment Variables

- Env vars are used for configs which need the container to restart to get new values
- See `./src/config/load_env.py` for the list of environment variables, their data types, and default values
- See `./src/config/validate_env.py` for any validation rules

### repos-to-convert.yaml

- The contents of this file can be changed while the container is running, and the current version will be read at the start of each main loop in main.py
- Note, the syntax in the below examples is quite out of date, but the explanations of each may still be useful
- See `./config/repo-converter/repos-to-convert-example.yaml` for an example of the config layout
- See `./src/config/load_repos.py` for the list of config keys
- TODO: Move the config schema to a separate file, and read it into the code

## Performance

1. The default interval and batch size are set for sane polling for new repo commits during regular operations, but would be quite slow for initial cloning
2. For initial cloning, adjust:
    1. The `REPO_CONVERTER_INTERVAL_SECONDS` environment variable
        1. This is the outer loop interval, how often the service will start a repo conversion job for each repo, if one is not already running
        2. Thus, the longest break between two batches would be the length of this interval
        3. Try 60 seconds, and adjust based on your source code host's performance
    2. The `MAX_CONCURRENT_CONVERSIONS_PER_SERVER` and `MAX_CONCURRENT_CONVERSIONS_GLOBAL` environment variables
        1. These are the maximum number of concurrent / parallel repo conversion jobs which can be run, per source code host, and total for this service
        2. The defaults are 10 each, so if you're converting repos from two Subversion servers at the same time, a maximum of 10 jobs can run in parallel, from either server

## Contributions

- Pull requests are always welcome
- See `./dev/TODO.md` for the list of tasks to be done
