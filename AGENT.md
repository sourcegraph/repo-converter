# Agent Guidelines for repo-converter Project
- The purpose of this project is to convert repos from other repo types (ex. Subversion) to Git
- It runs in a Podman container
- src/main.py is the entrypoint for the container
- The usage of this project is described to users in `./README.md` and `./docs/repo-converter.md`

## Build/Test Commands
- Build and start all containers: `./build/build.sh`
- Build and start all containers, and follow the repo-converter container's logs: `./build/build.sh f`

## Code Style Guidelines
- Python version: 3.13.2
- Imports: local modules first, standard libs second, then third-party libs with URLs in comments
- Variables: Snake case (e.g., `local_repo_path`)
- Error handling: Use try/except blocks with specific exception types
- Logging: Use the custom `log(ctx, "message", "log_level")` function with appropriate levels
- Functions: Snake case for function names
- Security: the log function calls the `redact()` function before logging, to ensure no credentials are leaked in logs
- Documentation: Use Python best practices for docstrings
- Comments: Use `#` for comments, and add lots of comments
