# How to parse git svn's .rev_map files, in Python

From Deep Search thread: https://sourcegraph.sourcegraph.com/deepsearch/aefc2267-7fcf-4b34-a045-f17ab3f29261

Based on my analysis of the Git SVN codebase, I can provide you with a comprehensive Python script to read and parse `.rev_map` files.

## Python Script to Read .rev_map Files

Here's a complete Python implementation based on the Git SVN source code:

```python
#!/usr/bin/env python3
"""
Python script to read and parse Git SVN .rev_map files.
Based on the format defined in perl/Git/SVN.pm from the Git codebase.
"""

import struct
import os
import sys
import subprocess
from pathlib import Path
from typing import Iterator, Tuple, Optional, List

class RevMapReader:
    """Reader for Git SVN .rev_map files."""

    def __init__(self, git_dir: str = None):
        """Initialize with Git directory path."""
        self.git_dir = git_dir or self._get_git_dir()
        self.oid_length = self._get_oid_length()
        self.record_size = (self.oid_length // 2) + 4

    def _get_git_dir(self) -> str:
        """Get the Git directory path."""
        try:
            result = subprocess.run(['git', 'rev-parse', '--git-dir'],
                                  capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            raise RuntimeError("Not in a Git repository")

    def _get_oid_length(self) -> int:
        """Determine OID length (40 for SHA-1, 64 for SHA-256)."""
        try:
            result = subprocess.run(['git', 'config', '--get', 'extensions.objectformat'],
                                  capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip() == 'sha256':
                return 64
            return 40
        except subprocess.CalledProcessError:
            return 40

    def find_rev_map_files(self) -> List[str]:
        """Find all .rev_map files in the Git SVN directory."""
        svn_dir = Path(self.git_dir) / 'svn'
        if not svn_dir.exists():
            return []

        rev_map_files = []
        for file_path in svn_dir.rglob('.rev_map.*'):
            if file_path.is_file():
                rev_map_files.append(str(file_path))

        return sorted(rev_map_files)

    def read_rev_map(self, file_path: str) -> Iterator[Tuple[int, str]]:
        """
        Read and parse a .rev_map file.

        Yields tuples of (svn_revision, git_commit_hash).
        Based on the format from perl/Git/SVN.pm:
        - Format: 'NH*' in Perl pack format
        - 4 bytes: SVN revision (big-endian unsigned int)
        - oid_length/2 bytes: Git commit hash (binary)
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Rev map file not found: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return

        if file_size % self.record_size != 0:
            raise ValueError(f"Inconsistent file size: {file_size} (record size: {self.record_size})")

        with open(file_path, 'rb') as f:
            while True:
                record_data = f.read(self.record_size)
                if not record_data:
                    break

                if len(record_data) != self.record_size:
                    raise ValueError(f"Incomplete record read: {len(record_data)} bytes")

                # Unpack: 4 bytes big-endian unsigned int + binary hash
                svn_rev = struct.unpack('>I', record_data[:4])[0]
                git_hash_bytes = record_data[4:]
                git_hash = git_hash_bytes.hex()

                # Skip padding records (all-zero hashes)
                if git_hash == '0' * self.oid_length:
                    continue

                yield (svn_rev, git_hash)

    def get_max_revision(self, file_path: str) -> Optional[Tuple[int, str]]:
        """
        Get the maximum (last) revision from a .rev_map file.
        Returns (svn_revision, git_commit_hash) or None if empty.
        """
        if not os.path.exists(file_path):
            return None

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return None

        with open(file_path, 'rb') as f:
            # Read the last record
            f.seek(-self.record_size, 2)  # Seek to end - record_size
            record_data = f.read(self.record_size)

            svn_rev = struct.unpack('>I', record_data[:4])[0]
            git_hash_bytes = record_data[4:]
            git_hash = git_hash_bytes.hex()

            # Handle padding records
            if git_hash == '0' * self.oid_length:
                if file_size >= self.record_size * 2:
                    # Read the penultimate record
                    f.seek(-self.record_size * 2, 2)
                    record_data = f.read(self.record_size)
                    svn_rev = struct.unpack('>I', record_data[:4])[0]
                    git_hash_bytes = record_data[4:]
                    git_hash = git_hash_bytes.hex()

                    if git_hash == '0' * self.oid_length:
                        raise ValueError("Inconsistent .rev_map file")
                else:
                    return None

            return (svn_rev, git_hash)

    def find_revision(self, file_path: str, target_rev: int) -> Optional[str]:
        """
        Find a specific SVN revision in the .rev_map file using binary search.
        Returns the Git commit hash or None if not found.
        """
        if not os.path.exists(file_path):
            return None

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return None

        with open(file_path, 'rb') as f:
            left = 0
            right = file_size - self.record_size

            while left <= right:
                # Calculate middle position aligned to record boundary
                mid = ((left // self.record_size + right // self.record_size) // 2) * self.record_size

                f.seek(mid)
                record_data = f.read(self.record_size)

                svn_rev = struct.unpack('>I', record_data[:4])[0]
                git_hash_bytes = record_data[4:]
                git_hash = git_hash_bytes.hex()

                if svn_rev < target_rev:
                    left = mid + self.record_size
                elif svn_rev > target_rev:
                    right = mid - self.record_size
                else:  # svn_rev == target_rev
                    return git_hash if git_hash != '0' * self.oid_length else None

            return None

def main():
    """Example usage of the RevMapReader."""
    try:
        reader = RevMapReader()
        print(f"Git directory: {reader.git_dir}")
        print(f"OID length: {reader.oid_length}")
        print(f"Record size: {reader.record_size} bytes")
        print()

        # Find all .rev_map files
        rev_map_files = reader.find_rev_map_files()
        if not rev_map_files:
            print("No .rev_map files found.")
            return

        for file_path in rev_map_files:
            print(f"Processing: {file_path}")

            # Get max revision
            max_rev = reader.get_max_revision(file_path)
            if max_rev:
                print(f"  Max revision: r{max_rev[0]} -> {max_rev[1]}")

            # Read all entries (limit output for large files)
            entries = list(reader.read_rev_map(file_path))
            print(f"  Total entries: {len(entries)}")

            if entries:
                print("  First 5 entries:")
                for svn_rev, git_hash in entries[:5]:
                    print(f"    r{svn_rev} -> {git_hash}")

                if len(entries) > 5:
                    print("  Last 5 entries:")
                    for svn_rev, git_hash in entries[-5:]:
                        print(f"    r{svn_rev} -> {git_hash}")

            print()

        # Example: Find a specific revision
        if rev_map_files and len(sys.argv) > 1:
            target_rev = int(sys.argv[1])
            for file_path in rev_map_files:
                git_hash = reader.find_revision(file_path, target_rev)
                if git_hash:
                    print(f"Found r{target_rev} -> {git_hash} in {file_path}")
                    break
            else:
                print(f"Revision r{target_rev} not found in any .rev_map file")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

## Key Implementation Details

### Binary Format Translation

The Perl format `'NH*'` translates to Python as:
- `N`: 32-bit big-endian unsigned integer → `struct.unpack('>I', data[:4])`
- `H*`: Hex string → `data[4:].hex()`

### Record Structure

Based on the Git SVN source code:
- **Record size**: `(oid_length / 2) + 4` bytes
- **SVN revision**: 4 bytes, big-endian unsigned integer
- **Git hash**: `oid_length/2` bytes in binary format

### File Location

The `.rev_map` files are located at:
```
$GIT_DIR/svn/**/.rev_map.*
```

### Usage Examples

```bash
# Basic usage - read all .rev_map files
python3 revmap_reader.py

# Find specific revision
python3 revmap_reader.py 1234

# Use in another script
from revmap_reader import RevMapReader

reader = RevMapReader()
for svn_rev, git_hash in reader.read_rev_map('.git/svn/refs/remotes/git-svn/.rev_map.uuid'):
    print(f"r{svn_rev} -> {git_hash}")
```

This implementation faithfully reproduces the Git SVN `.rev_map` file format and provides efficient binary search capabilities for large files, just like the original Perl implementation.