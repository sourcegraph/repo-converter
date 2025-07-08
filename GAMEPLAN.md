# Game Plan: Python Structured Logging Implementation

### 4. Implementation Strategy

#### Phase 2: Gradual Enhancement
- [ ] Add structured fields to key operations:
  - Repository operations: `repo_key`, `repo_type`, `server_hostname`

#### Phase 3: Advanced Features
- [ ] Add correlation IDs for tracking related operations
- [ ] Add structured error context (stack traces, error codes)
- [ ] Create log filtering (aggregation?) utilities

### 5. Automatic Field Collection Architecture

#### Core Logger Enhancement Strategy
**Automatic Context Injection**: Enhance the logging system to automatically capture contextual information without requiring manual field specification in each log call.


#### Command Context Auto-Capture
**Architecture**: Decorator-based command logging that automatically captures execution metadata.

The `@log_command_execution` decorator is a Python decorator that wraps command execution functions to automatically capture and log execution metadata without requiring manual logging code in every command function.

##### Decorator Implementation
```python
def log_command_execution(func):
    """Decorator that automatically logs command execution details"""
    def wrapper(*args, **kwargs):
        # Extract command info from function arguments
        ctx, command, args_list = args[0], args[1], args[2]

        # Start timing and capture initial state
        start_time = time.time()
        process_info = {
            "command": command,
            "args": args_list,
            "command_full": f"{command} {' '.join(args_list)}",
            "start_time": datetime.utcnow().isoformat(),
            "pid": None
        }

        # Push command context to logging system
        logger.push_context(process_info)

        try:
            # Execute the actual command function
            result = func(*args, **kwargs)

            # Capture success metrics
            end_time = time.time()
            execution_data = {
                "end_time": datetime.utcnow().isoformat(),
                "execution_time_ms": int((end_time - start_time) * 1000),
                "success": True,
                "returncode": getattr(result, 'returncode', 0),
                "stdout_lines": len(result.stdout.splitlines()) if result.stdout else 0,
                "stderr_lines": len(result.stderr.splitlines()) if result.stderr else 0,
                "stdout_preview": result.stdout[:200] if result.stdout else "",
                "stderr_preview": result.stderr[:200] if result.stderr else "",
                "memory_peak_kb": _get_memory_usage()
            }

            # Log successful completion
            log(ctx, f"Command completed: {command}", "INFO")
            return result

        except Exception as e:
            # Capture error metrics
            end_time = time.time()
            error_data = {
                "end_time": datetime.utcnow().isoformat(),
                "execution_time_ms": int((end_time - start_time) * 1000),
                "success": False,
                "error_type": type(e).__name__,
                "error_message": str(e)
            }

            # Log failed execution
            log(ctx, f"Command failed: {command}", "ERROR")
            raise  # Re-raise the exception

        finally:
            # Always clean up context
            logger.pop_context()

    return wrapper
```

##### Usage Example
```python
@log_command_execution
def run_git_command(ctx, command, args):
    """Run a git command with automatic logging"""
    # This function focuses on command execution only
    # All logging metadata is handled by the decorator

    full_command = [command] + args
    result = subprocess.run(
        full_command,
        capture_output=True,
        text=True,
        cwd=ctx.repo_path
    )

    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, full_command)

    return result

# Usage (unchanged from current code)
result = run_git_command(ctx, "git", ["clone", "--depth", "1", repo_url])
```

##### Automatic Structured Fields Captured
Every decorated function execution automatically adds these fields to ALL log entries within that function:
```python
{
    "command": "git",
    "args": ["clone", "--depth", "1", "https://github.com/user/repo.git"],
    "command_full": "git clone --depth 1 https://github.com/user/repo.git",
    "pid": 12345,
    "start_time": "2025-06-30T14:23:45.123456Z",
    "end_time": "2025-06-30T14:23:47.456789Z",
    "execution_time_ms": 2333,
    "returncode": 0,
    "success": true,
    "stdout_lines": 15,
    "stderr_lines": 0,
    "stdout_preview": "Cloning into 'repo'...",  # First 200 chars
    "stderr_preview": "",
    "memory_peak_kb": 45234
}
```

##### Benefits of Decorator Pattern
- **Zero Code Changes**: Existing command functions work unchanged
- **Automatic Metrics**: Timing, success/failure, output sizes captured automatically
- **Consistent Logging**: Every command gets the same metadata structure
- **Error Handling**: Exceptions are logged with context before re-raising
- **Context Propagation**: All logs within the decorated function include command context

#### Git Operation Context Auto-Capture
**Architecture**: Context manager that automatically injects git-specific metadata for git operations.

```python
with git_operation_context(repo_path, operation="sync") as git_ctx:
    # All logs within this block auto-include:
    {
        "repo_key": "customer-xyz/main-repo",
        "repo_type": "git",
        "repo_path": "/tmp/repos/customer-xyz/main-repo",
        "remote_url": "https://github.com/customer-xyz/main-repo.git",
        "local_rev": "a1b2c3d4",
        "remote_rev": "e5f6g7h8",
        "commits_behind": 3,
        "repo_status": "out_of_date",
        "batch_size": 50,
        "operation": "sync",
        "server_hostname": "git.company.com"
    }
```

#### Automatic Error Context Capture
```python
# On exception, auto-capture error context:
{
    "error_type": "subprocess.CalledProcessError",
    "error_code": "SVN_E175012",
    "error_message": "Connection timed out",
    "remote_error": "svn: E175012: Connection timed out",
    "traceback": "...",
    "correlation_id": "uuid-1234-5678"
}
```

### 6. Implementation Architecture Details

#### Enhanced Logger Class Structure with Structlog
```python
import structlog
from structlog.processors import JSONRenderer

class StructuredLogger:
    def __init__(self):
        self.base_context = self._capture_container_metadata()
        self.context_stack = []  # For nested contexts

        # Configure structlog for JSON Lines output
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.processors.add_log_level,
                structlog.processors.add_logger_name,
                self._add_automatic_context,  # Custom processor for auto-context
                structlog.processors.JSONRenderer()
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        self.logger = structlog.get_logger()

    def log(self, ctx, message, level="DEBUG", extra=None):
        # Auto-inject all context layers
        structured_data = {
            **self.base_context,           # Container metadata
            **self._capture_code_location(), # File/line/function
            **self._capture_timing(),       # Timestamps
            **self._merge_context_stack(),  # Git/command contexts
            **(extra or {})                # Manual overrides
        }
        # Apply redaction and emit via structlog
        redacted_data = self._redact_sensitive_data(structured_data)
        getattr(self.logger, level.lower())(message, **redacted_data)
```

#### Context Manager Pattern for Automatic Metadata
```python
# Git operations automatically inject metadata
@contextmanager
def git_operation_context(repo_path, operation):
    git_metadata = _inspect_git_repo(repo_path)
    logger.push_context(git_metadata)
    try:
        yield git_metadata
    finally:
        logger.pop_context()

# Command execution automatically captured
@contextmanager
def command_execution_context(command, args):
    cmd_metadata = {
        "command": command,
        "args": args,
        "start_time": datetime.utcnow().isoformat(),
        "pid": None  # Set when process starts
    }
    logger.push_context(cmd_metadata)
    try:
        yield cmd_metadata
    finally:
        # Update with execution results
        cmd_metadata.update({
            "end_time": datetime.utcnow().isoformat(),
            "execution_time_ms": ...,
            # other completion data
        })
        logger.pop_context()
```

#### Automatic Code Location Capture
```python
def _capture_code_location(self, skip_frames=2):
    frame = inspect.currentframe()
    for _ in range(skip_frames):
        frame = frame.f_back

    return {
        "module": frame.f_globals.get('__name__', 'unknown'),
        "function": frame.f_code.co_name,
        "file": os.path.basename(frame.f_code.co_filename),
        "line": frame.f_lineno
    }
```

### 7. Benefits
- **Machine readable**: Enable log aggregation, alerting, dashboards
- **Searchable**: Query by specific fields (repo_key, error_type, etc.)
- **Backwards compatible**: Existing log API unchanged
- **Security maintained**: `redact()` function continues to work
- **Performance insights**: Duration, memory usage tracking
- **Debugging**: Correlation IDs link related operations

### 8. Migration Strategy
- **Zero-disruption deployment**: Existing `log(ctx, message, level)` calls work unchanged
- **Automatic enhancement**: New structured fields appear automatically without code changes
- **Direct implementation**: Deploy structured logging as the primary output format
- **Validation**: Test structured logging output matches expected schema and includes all required fields

### 9. Implementation Priority & Phases

#### Phase 1: Foundation (Week 1-2)
1. **Logger infrastructure**: Enhanced `StructuredLogger` class with context stack
2. **Automatic basics**: Code location, timing, container metadata capture
3. **Backwards compatibility**: Ensure existing log calls work identically

#### Phase 2: Command & Git Context (Week 3-4)
1. **Command decorator**: `@log_command_execution` for automatic command metadata
2. **Git context manager**: `git_operation_context()` for repository operations
3. **Error enhancement**: Automatic error context capture and correlation IDs

#### Phase 3: Advanced Features (Week 5-6)
1. **Performance monitoring**: Memory usage, execution timing, queue metrics
3. **Correlation tracing**: Link related operations across function boundaries

### 10. Example Usage Patterns

#### Current Code (Unchanged)
```python
# Existing code continues to work exactly as before
log(ctx, "Starting repo sync", "INFO")
```

#### Enhanced Automatic Output
```json
{
  "timestamp": "2025-06-30T14:23:45.123456Z",
  "unix_timestamp": 1719763425.123456,
  "level": "INFO",
  "message": "Starting repo sync",
  "module": "repo_converter.sync_manager",
  "function": "sync_repository",
  "file": "sync_manager.py",
  "line": 89,
  "build_tag": "v2.1.4",
  "container_uptime_seconds": 3600
}
```

#### With Context Managers (Automatic)
```python
# Git context automatically captured for all logs in this block
with git_operation_context("/tmp/repos/acme-corp/main", "sync"):
    log(ctx, "Checking for updates", "DEBUG")  # Auto-includes git metadata

    # Command context automatically captured
    with command_execution_context("git", ["fetch", "origin"]):
        result = run_git_command(...)  # Auto-includes command metadata
        log(ctx, "Fetch completed", "INFO")
```

This architecture provides comprehensive structured logging with minimal code changes and maximum automation.
