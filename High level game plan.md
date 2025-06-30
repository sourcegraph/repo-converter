# Refactoring Plan for repo-converter/build/run.py

## Overview

The current `run.py` script (1500+ lines) performs repository conversion from SVN to Git but has several issues:

- Complex error handling scattered throughout
- No object-oriented design despite handling complex data
- Incomplete features marked with TODOs
- Duplicate code patterns

## Phase 1: Code Organization

### 1.2 Implement Base Classes

- Create a `Repository` base class with common methods
- Implement `SVNRepository`, `GitRepository`, and `TFSRepository` subclasses
- Move configuration validation to each repository type

## Phase 2: Refactor Functionality

### 2.1 Configuration Management

- Move environment variable loading to `config/environment.py`
- Move YAML parsing to `config/yaml_config.py`
- Implement proper type validation with clear error messages
- Create unified configuration object merging both sources

### 2.2 Logging Improvements

- Refactor `log()` function to use Python's logging more effectively
- Implement cleaner password redaction

### 2.3 Process Management

- Refactor subprocess handling into a cleaner utility class
- Improve zombie process detection and cleanup
- Implement better error handling for process management

## Phase 3: Repository Processing

### 3.1 SVN Repository Handling

- Break down `clone_svn_repo()` into smaller, focused methods
- Implement proper state management for create/update/running
- Add better error handling with specific error types
- Fix batch processing logic

### 3.2 Git Repository Handling

- Implement proper Git repository functionality
- Use GitPython more extensively

### 3.3 Process Concurrency

- Improve multiprocessing implementation
- Add proper resource limiting and queuing
- Implement better status tracking

## Phase 4: Testing & Documentation

### 4.1 Testing

- Add unit tests for each module
- Add integration tests for repository operations
- Implement mock objects for external dependencies

### 4.2 Documentation

- Add proper docstrings to all classes and methods
- Create usage documentation
- Document configuration options

## Phase 5: Implement TODOs

After refactoring, implement the TODOs from the original file:

1. Config file improvements
2. SVN enhancements (timeouts, gitignore handling, etc.)
3. Git SSH clone functionality
4. Add fetch interval configuration
5. Process status improvements
