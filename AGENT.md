# Agent Guidelines for Implementation Bridges Codebase

## Build/Test Commands
- Build and start all containers: `cd repo-converter/build && docker compose up -d --build`
- View repo-converter logs: `cd repo-converter/build && ./build.sh logs`
- Update requirements: `cd repo-converter/build && pipreqs --force --mode gt .`
- Run single test: No tests in codebase

## Code Style Guidelines
- Python version: 3.13.2
- Imports: Standard libs first, then third-party libs with URLs in comments
- Variables: Snake case (e.g., `local_repo_path`)
- Error handling: Use try/except blocks with specific exception types
- Logging: Use the custom `log()` function with appropriate levels
- Functions: Snake case for function names. Add docstrings (not yet implemented but mentioned in TODOs)
- Security: Use `redact_password()` before logging, if the input contains a password
- Documentation: Use Python best practices for docstrings
- Environment variables: Set defaults with `os.environ.get("VAR", "default")`
- Comments: Use `#` for comments, and add lots of comments

The purpose of this script is to convert repos from Subversion to Git
`repo-converter/build/run.py` is the only file in this repo which runs application code
It runs in a Docker container, and is the entrypoint for the container

The usage of this product is described to users in `repo-converter/README.md`
