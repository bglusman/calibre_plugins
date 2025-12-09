"""
Progress reporting for CLI operations.
"""

from __future__ import unicode_literals, division, absolute_import, print_function

import sys
from typing import Optional, Callable


class ProgressReporter:
    """
    Simple progress reporter for CLI operations.

    Can be used as a drop-in replacement for GUI progress dialogs.
    """

    def __init__(self,
                 total: int = 0,
                 desc: str = "Processing",
                 show_progress: bool = True,
                 file=None):
        """
        Initialize progress reporter.

        Args:
            total: Total number of items to process
            desc: Description of the operation
            show_progress: Whether to show progress output
            file: Output file (default: sys.stderr)
        """
        self.total = total
        self.desc = desc
        self.show_progress = show_progress
        self.file = file or sys.stderr
        self.current = 0
        self._last_percent = -1

    def update(self, n: int = 1, message: str = ""):
        """Update progress by n items."""
        self.current += n
        if self.show_progress and self.total > 0:
            percent = int(100 * self.current / self.total)
            if percent != self._last_percent:
                self._last_percent = percent
                bar_len = 30
                filled = int(bar_len * self.current / self.total)
                bar = '=' * filled + '-' * (bar_len - filled)
                status = f" {message}" if message else ""
                print(f"\r{self.desc}: [{bar}] {percent}%{status}",
                      end='', file=self.file, flush=True)

    def set_message(self, message: str):
        """Set current status message."""
        if self.show_progress:
            print(f"\r{self.desc}: {message}", end='', file=self.file, flush=True)

    def finish(self, message: str = "Done"):
        """Mark progress as complete."""
        if self.show_progress:
            print(f"\r{self.desc}: {message}" + " " * 20, file=self.file)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.finish()


class NullProgress:
    """No-op progress reporter for silent operation."""

    def __init__(self, *args, **kwargs):
        pass

    def update(self, n: int = 1, message: str = ""):
        pass

    def set_message(self, message: str):
        pass

    def finish(self, message: str = "Done"):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
