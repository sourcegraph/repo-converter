# Agent Guidelines for Implementation Bridges Codebase
- The purpose of this project is to convert repos from Subversion to Git
- It runs in a Docker container
- src/main.py is the entrypoint for the container
- The usage of this project is described to users in `repo-converter/README.md`

## Build/Test Commands
- Build and start all containers: `cd repo-converter/build && ./build.sh`
- Build and start all containers, and view repo-converter logs: `cd repo-converter/build && ./build.sh logs`

## Code Style Guidelines
- Python version: 3.13.2
- Imports: Standard libs first, then third-party libs with URLs in comments
- Variables: Snake case (e.g., `local_repo_path`)
- Error handling: Use try/except blocks with specific exception types
- Logging: Use the custom `log()` function with appropriate levels
- Functions: Snake case for function names. Add docstrings (not yet implemented but mentioned in TODOs)
- Security: the log function calls the `redact()` function before logging, to ensure no credentials are leaked in logs
- Documentation: Use Python best practices for docstrings
- Environment variables: Set defaults with `os.environ.get("VAR", "default")`
- Comments: Use `#` for comments, and add lots of comments
