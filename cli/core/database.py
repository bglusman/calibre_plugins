"""
Database wrapper for headless Calibre library access.

This module provides direct access to a Calibre library database without
requiring the GUI. It wraps the calibre.library.db module.
"""

from __future__ import unicode_literals, division, absolute_import, print_function

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple
from collections import defaultdict


class CalibreDB:
    """
    Headless interface to a Calibre library database.

    This class provides the same interface as the GUI's db object but works
    without Qt or the Calibre GUI. It can be used as a drop-in replacement
    for algorithms that only need database access.
    """

    def __init__(self, library_path: str, read_only: bool = True):
        """
        Initialize connection to a Calibre library.

        Args:
            library_path: Path to the Calibre library folder (containing metadata.db)
            read_only: If True, open database in read-only mode (default)
        """
        self.library_path = Path(library_path)
        self.db_path = self.library_path / 'metadata.db'

        if not self.db_path.exists():
            raise FileNotFoundError(f"Calibre database not found at {self.db_path}")

        self.read_only = read_only
        self._conn = None
        self._connect()

        # Cache for performance
        self._author_cache: Dict[int, str] = {}
        self._title_cache: Dict[int, str] = {}

    def _connect(self):
        """Establish database connection."""
        uri = f"file:{self.db_path}?mode=ro" if self.read_only else str(self.db_path)
        self._conn = sqlite3.connect(uri, uri=self.read_only)
        self._conn.row_factory = sqlite3.Row

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ----------------------------------------------------------------
    # Core query methods - matching the Calibre DB API
    # ----------------------------------------------------------------

    def all_ids(self) -> List[int]:
        """Return all book IDs in the library."""
        cursor = self._conn.execute("SELECT id FROM books ORDER BY id")
        return [row[0] for row in cursor.fetchall()]

    def title(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """Get the title for a book."""
        if book_id in self._title_cache:
            return self._title_cache[book_id]

        cursor = self._conn.execute(
            "SELECT title FROM books WHERE id = ?", (book_id,)
        )
        row = cursor.fetchone()
        if row:
            self._title_cache[book_id] = row[0]
            return row[0]
        return None

    def authors(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """
        Get authors for a book as a comma-separated string.

        Note: Returns format compatible with Calibre's db.authors() which uses
        comma separation with | for individual author name parts.
        """
        if book_id in self._author_cache:
            return self._author_cache[book_id]

        cursor = self._conn.execute("""
            SELECT GROUP_CONCAT(a.name, ',') as authors
            FROM books_authors_link bal
            JOIN authors a ON bal.author = a.id
            WHERE bal.book = ?
            ORDER BY bal.id
        """, (book_id,))
        row = cursor.fetchone()
        if row and row[0]:
            # Replace commas in names with | for compatibility
            authors = row[0]
            self._author_cache[book_id] = authors
            return authors
        return None

    def isbn(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """Get ISBN identifier for a book."""
        cursor = self._conn.execute("""
            SELECT val FROM identifiers
            WHERE book = ? AND type = 'isbn'
        """, (book_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_identifiers(self, book_id: int, index_is_id: bool = True) -> Dict[str, str]:
        """Get all identifiers for a book as a dict."""
        cursor = self._conn.execute("""
            SELECT type, val FROM identifiers WHERE book = ?
        """, (book_id,))
        return {row[0]: row[1] for row in cursor.fetchall()}

    def series(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """Get series name for a book."""
        cursor = self._conn.execute("""
            SELECT s.name FROM books_series_link bsl
            JOIN series s ON bsl.series = s.id
            WHERE bsl.book = ?
        """, (book_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def series_index(self, book_id: int, index_is_id: bool = True) -> Optional[float]:
        """Get series index for a book."""
        cursor = self._conn.execute(
            "SELECT series_index FROM books WHERE id = ?", (book_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def languages(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """Get languages for a book as comma-separated string."""
        cursor = self._conn.execute("""
            SELECT GROUP_CONCAT(l.lang_code, ',') as languages
            FROM books_languages_link bll
            JOIN languages l ON bll.lang_code = l.id
            WHERE bll.book = ?
        """, (book_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def formats(self, book_id: int, index_is_id: bool = True,
                verify_formats: bool = False) -> Optional[str]:
        """Get formats for a book as comma-separated string."""
        cursor = self._conn.execute("""
            SELECT GROUP_CONCAT(format, ',') as formats
            FROM data WHERE book = ?
        """, (book_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def format_metadata(self, book_id: int, fmt: str) -> Dict[str, Any]:
        """Get metadata for a specific format file."""
        cursor = self._conn.execute("""
            SELECT name, uncompressed_size as size
            FROM data WHERE book = ? AND format = ?
        """, (book_id, fmt.upper()))
        row = cursor.fetchone()
        if row:
            # Get actual file path and stat for mtime
            book_path = self.path(book_id, index_is_id=True)
            if book_path:
                format_path = self.library_path / book_path / f"{row[0]}.{fmt.lower()}"
                if format_path.exists():
                    stat = format_path.stat()
                    return {
                        'size': stat.st_size,
                        'mtime': stat.st_mtime,
                        'path': str(format_path)
                    }
        return {}

    def path(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """Get the relative path to a book's folder."""
        cursor = self._conn.execute(
            "SELECT path FROM books WHERE id = ?", (book_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def publisher(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """Get publisher for a book."""
        cursor = self._conn.execute("""
            SELECT p.name FROM books_publishers_link bpl
            JOIN publishers p ON bpl.publisher = p.id
            WHERE bpl.book = ?
        """, (book_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def tags(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """Get tags for a book as comma-separated string."""
        cursor = self._conn.execute("""
            SELECT GROUP_CONCAT(t.name, ',') as tags
            FROM books_tags_link btl
            JOIN tags t ON btl.tag = t.id
            WHERE btl.book = ?
        """, (book_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def cover(self, book_id: int, index_is_id: bool = True) -> Optional[str]:
        """Get path to cover image if it exists."""
        cursor = self._conn.execute(
            "SELECT has_cover, path FROM books WHERE id = ?", (book_id,)
        )
        row = cursor.fetchone()
        if row and row[0]:  # has_cover is True
            cover_path = self.library_path / row[1] / 'cover.jpg'
            if cover_path.exists():
                return str(cover_path)
        return None

    # ----------------------------------------------------------------
    # Search and query methods
    # ----------------------------------------------------------------

    def search_getting_ids(self, query: str, restriction: str = '') -> List[int]:
        """
        Simple search implementation.

        For full search capability, you'd need Calibre's search parser.
        This provides basic identifier-based searches.
        """
        if query.startswith('identifier:'):
            # Handle identifier searches like 'identifier:isbn:True'
            parts = query.split(':')
            if len(parts) >= 3 and parts[2] == 'True':
                id_type = parts[1]
                cursor = self._conn.execute("""
                    SELECT DISTINCT book FROM identifiers WHERE type = ?
                """, (id_type,))
                return [row[0] for row in cursor.fetchall()]
        elif query.startswith('formats:'):
            # Handle format searches
            if 'True' in query:
                cursor = self._conn.execute("""
                    SELECT DISTINCT book FROM data
                """)
                return [row[0] for row in cursor.fetchall()]

        # Default: return all books
        return self.all_ids()

    def all_field_for(self, field: str, book_ids: List[int]) -> Dict[int, Any]:
        """Get a field value for multiple books efficiently."""
        result = {}

        if field == 'authors':
            for book_id in book_ids:
                authors = self.authors(book_id)
                if authors:
                    # Return as tuple for compatibility
                    result[book_id] = tuple(a.strip() for a in authors.split(','))
        elif field == 'series':
            for book_id in book_ids:
                series = self.series(book_id)
                if series:
                    result[book_id] = series
        elif field == 'publisher':
            for book_id in book_ids:
                pub = self.publisher(book_id)
                if pub:
                    result[book_id] = pub
        elif field == 'tags':
            for book_id in book_ids:
                tags = self.tags(book_id)
                if tags:
                    result[book_id] = tuple(t.strip() for t in tags.split(','))

        return result

    def get_id_map(self, field: str) -> Dict[int, str]:
        """Get mapping of field IDs to names."""
        if field == 'authors':
            cursor = self._conn.execute("SELECT id, name FROM authors")
        elif field == 'series':
            cursor = self._conn.execute("SELECT id, name FROM series")
        elif field == 'publisher':
            cursor = self._conn.execute("SELECT id, name FROM publishers")
        elif field == 'tags':
            cursor = self._conn.execute("SELECT id, name FROM tags")
        else:
            return {}

        return {row[0]: row[1] for row in cursor.fetchall()}

    def get_usage_count_by_id(self, field: str) -> List[Tuple[int, int]]:
        """Get usage count for each item in a field."""
        if field == 'authors':
            cursor = self._conn.execute("""
                SELECT author, COUNT(*) FROM books_authors_link GROUP BY author
            """)
        elif field == 'series':
            cursor = self._conn.execute("""
                SELECT series, COUNT(*) FROM books_series_link GROUP BY series
            """)
        elif field == 'publisher':
            cursor = self._conn.execute("""
                SELECT publisher, COUNT(*) FROM books_publishers_link GROUP BY publisher
            """)
        elif field == 'tags':
            cursor = self._conn.execute("""
                SELECT tag, COUNT(*) FROM books_tags_link GROUP BY tag
            """)
        else:
            return []

        return [(row[0], row[1]) for row in cursor.fetchall()]

    # ----------------------------------------------------------------
    # Hash/binary comparison support
    # ----------------------------------------------------------------

    def format_hash(self, book_id: int, fmt: str) -> Optional[str]:
        """Calculate SHA hash of a format file."""
        import hashlib

        book_path = self.path(book_id)
        if not book_path:
            return None

        cursor = self._conn.execute("""
            SELECT name FROM data WHERE book = ? AND format = ?
        """, (book_id, fmt.upper()))
        row = cursor.fetchone()
        if not row:
            return None

        file_path = self.library_path / book_path / f"{row[0]}.{fmt.lower()}"
        if not file_path.exists():
            return None

        sha = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha.update(chunk)
        return sha.hexdigest()

    # ----------------------------------------------------------------
    # Custom book data (for caching hashes etc.)
    # ----------------------------------------------------------------

    def get_all_custom_book_data(self, name: str, default: Any = None) -> Dict[int, Any]:
        """
        Get custom plugin data for all books.

        Note: This is a simplified implementation that doesn't persist.
        For full persistence, you'd store in a separate JSON file.
        """
        # For now, return empty - could be extended to use a JSON sidecar
        return default if default is not None else {}

    def add_multiple_custom_book_data(self, name: str, data: Dict[int, Any]):
        """
        Store custom plugin data for multiple books.

        Note: Simplified implementation - extend for persistence.
        """
        pass  # Could write to JSON sidecar file

    # ----------------------------------------------------------------
    # Library info
    # ----------------------------------------------------------------

    def book_count(self) -> int:
        """Get total number of books in library."""
        cursor = self._conn.execute("SELECT COUNT(*) FROM books")
        return cursor.fetchone()[0]

    def get_book_info(self, book_id: int) -> Dict[str, Any]:
        """Get comprehensive info about a book."""
        return {
            'id': book_id,
            'title': self.title(book_id),
            'authors': self.authors(book_id),
            'series': self.series(book_id),
            'series_index': self.series_index(book_id),
            'publisher': self.publisher(book_id),
            'isbn': self.isbn(book_id),
            'identifiers': self.get_identifiers(book_id),
            'languages': self.languages(book_id),
            'formats': self.formats(book_id),
            'tags': self.tags(book_id),
            'path': self.path(book_id),
        }
