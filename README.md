# Run the Sourcegraph Cloud Private Connect Agent and src serve-git together in a Docker Compose file

## Experimental - This is not a supported Sourcegraph product
This repo was created for Sourcegraph Implementation Engineering deployments, and is not intended, designed, built, or supported for use in any other scenario. Feel free to open issues or PRs, but responses are best effort.

## Why
Running src serve-git and the agent together on the same Docker network allows the agent to use Docker's DNS to reach src serve-git, and prevents src serve-git's unauthenticated HTTP endpoint from needing to be opened outside of the Docker host.

Docker compose also allows for easier upgrades, troubleshooting, monitoring, logging, flexibility of hosting, etc. than running the binaries directly on the OS.

## Setup - Sourcegraph Staff Only
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
2. Run the "Reload Instance for srcconnect config change" GitHub Action, as many containers need to be restarted to pick up tunnel connection config changes
3. Clone this repo to a customer's bridge VM, install Docker and Docker's Compose plugin
4. Copy the `config.yaml` and `service-account-key.json` files using the instructions on the instance's Cloud Ops dashboard
    - Paste them into `./config/cloud-agent-config.yaml` and `./config/cloud-agent-service-account-key.json`
5. Modify the contents of the `./config/cloud-agent-config.yaml` file:
    - `serviceAccountKeyFile: /sourcegraph/cloud-agent-service-account-key.json` so that the Go binary inside the agent container finds this file in the path that's mapped via the docker-compose.yaml files
    - Only include the `- dialAddress` entries that this cloud agent instance can reach, remove the others, so the Cloud instance doesn't try using this agent instance for code hosts it can't reach
    - Use extra caution when pasting the config.yaml in Windows, as it may use Windows' line endings or extra spaces, which breaks YAML, as a whitespace-dependent format
6. Run `docker compose up -d`
7. Add a Code Host config to the customer's Cloud instance
    - Type: src serve-git
    - `"url": "http://src-serve-git-ubuntu.local:443",`
    - or
    - `"url": "http://src-serve-git-wsl.local:443",`
    - Note the port 443, even when used with http://
8. Use the repo-converter to convert SVN, TFVC, or Git repos, to Git format, which will store them in the `src-serve-root` directory, or use any other means to get the repos into the directory
    - There are docker-compose.yaml and override files in a few different directories in this repo, separated by use case, so that each use case only needs to run `docker compose up -d` in one directory, and not fuss around with `-f` paths.
    - The only difference between the docker-compose-override.yaml files in host-ubuntu vs host-wsl is the src-serve-git container's name, which is how we get a separate `dnsName` for each.
    - If you're using the repo-converter:
        - If you're using the pre-built images, `cd ./src && docker compose up -d`
        - If you're building the Docker images, `cd ./src/build && docker compose up -d --build`
        - Either of these will start all 3 containers: cloud-agent, src-serve-git, and the repo-converter