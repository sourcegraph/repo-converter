# AI Agent Game Plan for Revision Tracking System Implementation

## Overview
Implement a lightweight revision tracking system to optimize SVN to Git conversion by caching revision information and tracking conversion states. This eliminates the need to run slow `svn log` commands repeatedly.

## Goals
1. **Store SVN revision data**: Store revision numbers from SVN log XML output
2. **Track conversion states**: Monitor which revisions are converted, failed, excluded, or pending
3. **Optimize performance**: Avoid repeated slow SVN log commands
4. **Enable incremental conversion**: Only convert revisions that need conversion
5. **Provide recovery**: Handle failed conversions and retry logic

## File Structure
```
<local_repo_path>/.git/
└── svn-revisions.json
```

## Data Structure

### Revision State File Format (svn-revisions.json)
```json
{
    "repo_metadata": {
        "repo_url": "https://svn.example.com/repo",
        "last_svn_check": "2025-01-10T12:00:00Z",
        "last_git_update": "2025-01-10T12:00:00Z",
        "total_revisions_count": 2500,
        "converted_revisions_count": 1200,
        "pending_revisions_count": 1000,
        "failed_revisions_count": 5,
        "excluded_revisions_count": 295
    },
    "revisions": {
        "1": {
            "state": "converted",
            "git_commit": "abc123def456",
            "timestamp": "2025-01-10T10:00:00Z",
        },
        "2": {
            "state": "excluded",
            "timestamp": "2025-01-10T10:00:00Z",
        },
        "1377700": {
            "state": "converted",
            "git_commit": "def789ghi012",
            "timestamp": "2025-01-10T11:30:00Z",
        },
        "1881028": {
            "state": "pending",
            "timestamp": "2025-01-10T12:00:00Z",
        }
    }
}
```

### Revision States
- **`converted`**: Successfully converted to Git repository
- **`pending`**: Discovered but not yet converted
- **`failed`**: Last conversion attempt failed
- **`excluded`**: Excluded by user configuration
- **`processing`**: Currently being processed (temporary state)

## Implementation Steps

### Step 1: Core Infrastructure Functions
**File**: `src/source_repo/svn.py`

#### 1.1 XML Parsing Function
```python
def parse_svn_log_xml(xml_content: str) -> List[int]:
    """Parse SVN log XML and extract revision numbers"""
```

#### 1.2 Revision State File Management
```python
def get_revision_state_file_path(local_repo_path: str) -> str:
    """Get path to revision state file"""

def load_revision_state(ctx: Context, local_repo_path: str) -> dict:
    """Load revision state from file, create if not exists"""

def save_revision_state(ctx: Context, local_repo_path: str, state: dict) -> None:
    """Save revision state to file with backup"""
```

#### 1.3 Revision Discovery and Caching
```python
def discover_all_revisions(ctx: Context, svn_remote_repo_code_root_url: str,
                          username: str, password: str) -> List[int]:
    """Get all revision numbers from SVN server and store results"""

def store_svn_log_output(ctx: Context, local_repo_path: str,
                        xml_content: str) -> None:
    """Store SVN log XML output in a file to avoid repeated queries"""
```

### Step 2: Git Repository Analysis
**File**: `src/source_repo/svn.py`

#### 2.1 Git Conversion Verification
```python
def get_converted_revisions_from_git(ctx: Context, local_repo_path: str) -> Set[int]:
    """Analyze Git log to find which SVN revisions are already converted"""

def verify_revision_converted(ctx: Context, local_repo_path: str, revision: int) -> bool:
    """Verify specific revision is properly converted in Git"""

def get_git_commit_for_revision(ctx: Context, local_repo_path: str, revision: int) -> str:
    """Get Git commit hash for a specific SVN revision"""
```

#### 2.2 State Synchronization
```python
def sync_revision_states_with_git(ctx: Context, local_repo_path: str) -> None:
    """Synchronize revision states with actual Git repository state"""

def mark_revisions_as_converted(ctx: Context, local_repo_path: str,
                               revisions: List[int]) -> None:
    """Mark revisions as converted after successful Git conversion"""
```

### Step 3: User Configuration Integration
**File**: `src/source_repo/svn.py`

#### 3.1 Exclusion Rules
```python
def apply_exclusion_rules(ctx: Context, local_repo_path: str,
                         exclusion_patterns: List[str]) -> None:
    """Apply user-defined exclusion rules to mark revisions as excluded"""

def check_revision_excluded(ctx: Context, revision: int,
                           exclusion_config: dict) -> bool:
    """Check if revision should be excluded based on config"""
```

### Step 4: Batch Processing Optimization
**File**: `src/source_repo/svn.py`

#### 4.1 Intelligent Batch Selection
```python
def get_next_conversion_batch(ctx: Context, local_repo_path: str,
                             batch_size: int) -> List[int]:
    """Get next batch of revisions to convert, prioritizing by revision number"""
```

#### 4.2 Progress Tracking
```python
def log_conversion_progress(ctx: Context, local_repo_path: str) -> None:
    """Log detailed progress information"""
```

### Step 5: Error Handling and Recovery
**File**: `src/source_repo/svn.py`

#### 5.1 Failure Management
```python
def mark_revision_failed(ctx: Context, local_repo_path: str, revision: int,
                        error_message: str) -> None:
    """Mark revision as failed with error details"""

def retry_failed_revisions(ctx: Context, local_repo_path: str,
                          max_retries: int = 3) -> None:
    """Retry previously failed revisions"""

def cleanup_stale_processing_states(ctx: Context, local_repo_path: str) -> None:
    """Clean up revisions stuck in 'processing' state"""
```

### Step 6: Main Logic Integration
**File**: `src/source_repo/svn.py`

#### 6.1 Modified convert Function
```python
def convert(ctx: Context) -> None:
    # ... existing setup code ...

    # NEW: Initialize revision tracking
    revision_state = load_revision_state(ctx, local_repo_path)

    # NEW: Check if we need to discover revisions
    if should_discover_revisions(ctx, revision_state):
        discover_and_store_revision_numbers(ctx, local_repo_path, svn_remote_repo_code_root_url)

    # NEW: Get next batch to convert
    next_batch = get_next_conversion_batch(ctx, local_repo_path, fetch_batch_size)

    if not next_batch:
        log(ctx, "No revisions need conversion, repository is up to date", "info")
        return

    # NEW: Convert batch and update states
    convert_revision_batch(ctx, local_repo_path, next_batch)

    # ... rest of existing logic ...
```

#### 6.2 New Helper Functions
```python
def should_discover_revisions(ctx: Context, revision_state: dict) -> bool:
    """Run svn info command to determine if we need to run SVN discovery"""

def discover_and_store_revision_numbers(ctx: Context, local_repo_path: str,
                                svn_url: str) -> None:
    """Discover all revisions and update locally stored list of revisions"""

def convert_revision_batch(ctx: Context, local_repo_path: str,
                          revisions: List[int]) -> None:
    """Convert a batch of revisions and update tracking"""
```

### Step 7: Performance Monitoring
**File**: `src/source_repo/svn.py`

#### 7.1 Metrics Collection
```python
def collect_conversion_metrics(ctx: Context, local_repo_path: str) -> dict:
    """Collect performance metrics for conversion process"""

def log_performance_summary(ctx: Context, local_repo_path: str) -> None:
    """Log performance summary and recommendations"""
```

## Implementation Order

### Phase 1: Core Infrastructure (Priority: High)
1. **Step 1.1**: XML parsing function
2. **Step 1.2**: Revision state file management
3. **Step 2.1**: Git conversion verification
4. **Step 5.3**: Cleanup stale states

### Phase 2: Discovery and Caching (Priority: High)
1. **Step 1.3**: Revision discovery and caching
2. **Step 2.2**: State synchronization
3. **Step 4.1**: Batch selection logic

### Phase 3: Integration (Priority: Medium)
1. **Step 6.1**: Main logic integration
2. **Step 6.2**: Helper functions
3. **Step 4.2**: Progress tracking

### Phase 4: Advanced Features (Priority: Low)
1. **Step 3.1**: Exclusion rules
2. **Step 5.1**: Failure management
3. **Step 7.1**: Performance monitoring

## Testing Strategy

### Unit Tests
- Test XML parsing with various SVN log formats
- Test revision state file operations
- Test Git log analysis functions
- Test batch optimization logic

### Integration Tests
- Test full conversion workflow with tracking
- Test recovery from failures
- Test performance improvements

### Edge Cases
- Handle empty SVN repositories
- Handle corrupted state files
- Handle network failures during discovery
- Handle Git repository corruption

## Performance Expectations

### Before Implementation
- Multiple `svn log` commands per conversion cycle
- No caching of revision information
- Limited failure recovery

### After Implementation
- Single `svn log` command for initial discovery
- Locally stored revision numbers
- Intelligent batch processing
- Comprehensive failure recovery
- Progress tracking and ETA

## Configuration Options

Using existing configuration from `repos-to-clone.yaml`:
```yaml
  fetch-batch-size: 100
```

Using existing configuration from environment variables:
```python
env_vars["MAX_RETRIES"]
```

Add new configs to `repos-to-clone.yaml`:
```yaml
  exclude-revisions:
    - 1
    - 99
```

## Monitoring and Logging

### Log Messages
- Revision discovery progress
- Conversion batch progress
- State synchronization results
- Performance metrics
- Error details with recovery actions

### Debug Information
- Revision state file changes
- Git log analysis results
- Batch optimization decisions

## Migration Strategy

### For Existing Repositories
1. Run state synchronization on first execution
2. Analyze existing Git repository to populate converted states
3. Discover remaining revisions from SVN
4. Continue with optimized workflow

### Backward Compatibility
- Rebuild tracking state file if it's corrupted
