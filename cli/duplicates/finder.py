"""
Headless duplicate finder - finds duplicate books without GUI.

Ported from kiwidude's Find Duplicates plugin with Calibre/Qt dependencies removed.
Original: https://github.com/kiwidude68/calibre_plugins/tree/main/find_duplicates

This module provides:
- DuplicateFinder: Main class for finding duplicates
- Various search algorithms (title/author, identifier, binary)

License: GPL v3
Original Copyright: 2011, Grant Drake
"""

from __future__ import unicode_literals, division, absolute_import, print_function

import time
import hashlib
from collections import OrderedDict, defaultdict
from typing import Dict, List, Set, Tuple, Optional, Callable, Any, Union

from .matching import (
    authors_to_list,
    similar_title_match,
    get_author_algorithm_fn,
    get_title_algorithm_fn,
)

__license__ = 'GPL v3'
__copyright__ = '2011, Grant Drake'


# Search mode constants
DUPLICATE_SEARCH_FOR_BOOK = 'BOOK'
DUPLICATE_SEARCH_FOR_AUTHOR = 'AUTHOR'


class ExemptionsMap:
    """
    Tracks book pairs that should not be considered duplicates.

    Users can mark certain book pairs as "not duplicates" and this
    class tracks those exemptions.
    """

    def __init__(self, exemptions: Optional[Dict[int, Set[int]]] = None):
        """
        Initialize with optional exemptions dict.

        Args:
            exemptions: Dict mapping book_id to set of book_ids it should not
                       be grouped with as duplicates
        """
        self._exemptions = exemptions or {}

    def __contains__(self, book_id: int) -> bool:
        return book_id in self._exemptions

    def merge_sets(self, book_id: int) -> Set[int]:
        """Get set of all books that should not be grouped with book_id."""
        return self._exemptions.get(book_id, set())

    def add_exemption(self, book_id1: int, book_id2: int) -> None:
        """Mark two books as not being duplicates of each other."""
        if book_id1 not in self._exemptions:
            self._exemptions[book_id1] = set()
        if book_id2 not in self._exemptions:
            self._exemptions[book_id2] = set()
        self._exemptions[book_id1].add(book_id2)
        self._exemptions[book_id2].add(book_id1)


class DuplicateGroup:
    """Represents a group of duplicate books."""

    def __init__(self, group_id: int, book_ids: List[int], match_key: str = ''):
        self.group_id = group_id
        self.book_ids = book_ids
        self.match_key = match_key

    def __repr__(self):
        return f"DuplicateGroup({self.group_id}, books={self.book_ids})"

    def __len__(self):
        return len(self.book_ids)


class DuplicateFinder:
    """
    Headless duplicate finder for Calibre libraries.

    Example usage:
        from cli.core.database import CalibreDB
        from cli.duplicates.finder import DuplicateFinder

        with CalibreDB('/path/to/library') as db:
            finder = DuplicateFinder(db)
            groups = finder.find_duplicates(
                title_match='similar',
                author_match='similar'
            )
            for group in groups:
                print(f"Group {group.group_id}: {group.book_ids}")
    """

    def __init__(self, db,
                 book_exemptions: Optional[ExemptionsMap] = None,
                 author_exemptions: Optional[ExemptionsMap] = None,
                 progress_callback: Optional[Callable[[str, int, int], None]] = None,
                 debug: bool = False):
        """
        Initialize the duplicate finder.

        Args:
            db: CalibreDB instance
            book_exemptions: Map of book pairs to exclude from grouping
            author_exemptions: Map of author pairs to exclude from grouping
            progress_callback: Optional callback(message, current, total) for progress
            debug: Enable debug output
        """
        self.db = db
        self.book_exemptions = book_exemptions or ExemptionsMap()
        self.author_exemptions = author_exemptions or ExemptionsMap()
        self.progress_callback = progress_callback
        self.debug = debug

    def _log(self, message: str) -> None:
        """Log a debug message if debug mode is enabled."""
        if self.debug:
            print(f"[DuplicateFinder] {message}")

    def _progress(self, message: str, current: int = 0, total: int = 0) -> None:
        """Report progress if callback is set."""
        if self.progress_callback:
            self.progress_callback(message, current, total)

    def find_duplicates(self,
                       search_type: str = 'title_author',
                       title_match: str = 'similar',
                       author_match: str = 'similar',
                       identifier_type: str = 'isbn',
                       include_languages: bool = False,
                       sort_by_title: bool = True,
                       book_ids: Optional[List[int]] = None) -> List[DuplicateGroup]:
        """
        Find duplicate books in the library.

        Args:
            search_type: One of 'title_author', 'identifier', 'binary', 'author_only'
            title_match: Title matching algorithm - 'identical', 'similar', 'soundex', 'fuzzy'
            author_match: Author matching algorithm - 'identical', 'similar', 'soundex', 'fuzzy', 'ignore'
            identifier_type: Identifier type for identifier search (e.g., 'isbn', 'goodreads')
            include_languages: Consider language when matching (books in different languages not duplicates)
            sort_by_title: Sort groups by title (True) or by group size (False)
            book_ids: Optional list of book IDs to check (default: all books)

        Returns:
            List of DuplicateGroup objects
        """
        start = time.time()

        # Get book IDs to consider
        if book_ids is None:
            book_ids = self.db.all_ids()

        # Ensure book_ids is a list at this point
        assert book_ids is not None

        self._log(f"Analyzing {len(book_ids)} books for duplicates")
        self._progress(f"Analyzing {len(book_ids)} books for duplicates", 0, len(book_ids))

        # Find candidate groups based on search type
        if search_type == 'identifier':
            candidates_map = self._find_identifier_candidates(book_ids, identifier_type)
        elif search_type == 'binary':
            candidates_map = self._find_binary_candidates(book_ids)
        elif search_type == 'author_only':
            return self._find_author_only_duplicates(
                book_ids, author_match, sort_by_title
            )
        else:  # title_author (default)
            candidates_map = self._find_title_author_candidates(
                book_ids, title_match, author_match, include_languages
            )

        # Remove groups with less than 2 members
        self._shrink_candidates_map(candidates_map)

        # Sort candidate groups
        candidates_map = self._sort_candidate_groups(candidates_map, sort_by_title)

        # Convert to duplicate groups, handling exemptions
        groups = self._convert_to_groups(candidates_map, self.book_exemptions)

        elapsed = time.time() - start
        self._log(f"Found {len(groups)} duplicate groups in {elapsed:.2f}s")

        return groups

    def _find_title_author_candidates(self,
                                      book_ids: List[int],
                                      title_match: str,
                                      author_match: str,
                                      include_languages: bool) -> Dict[str, Set[int]]:
        """Find candidates using title and author matching."""
        candidates_map = defaultdict(set)

        title_fn = get_title_algorithm_fn(title_match)
        author_fn = get_author_algorithm_fn(author_match) if author_match != 'ignore' else None

        for i, book_id in enumerate(book_ids):
            if i % 100 == 0:
                self._progress(f"Analyzing books", i, len(book_ids))

            title = self.db.title(book_id, index_is_id=True)
            if not title:
                continue

            lang = None
            if include_languages:
                lang = self.db.languages(book_id, index_is_id=True)

            title_hash = title_fn(title, lang)

            if author_fn:
                authors = authors_to_list(self.db, book_id)
                if authors:
                    for author in authors:
                        author_hash, rev_author_hash = author_fn(author)
                        candidates_map[title_hash + author_hash].add(book_id)
                        if rev_author_hash and rev_author_hash != author_hash:
                            candidates_map[title_hash + rev_author_hash].add(book_id)
                    continue

            # No authors or ignoring authors
            candidates_map[title_hash].add(book_id)

        return candidates_map

    def _find_identifier_candidates(self,
                                    book_ids: List[int],
                                    identifier_type: str) -> Dict[str, Set[int]]:
        """Find candidates with matching identifiers (ISBN, etc.)."""
        candidates_map = defaultdict(set)

        for i, book_id in enumerate(book_ids):
            if i % 100 == 0:
                self._progress(f"Checking identifiers", i, len(book_ids))

            identifiers = self.db.get_identifiers(book_id, index_is_id=True)
            identifier = identifiers.get(identifier_type, '')
            if identifier:
                candidates_map[identifier].add(book_id)

        return candidates_map

    def _find_binary_candidates(self, book_ids: List[int]) -> Dict[Tuple[str, int], Set[int]]:
        """Find candidates with identical file content (by hash)."""
        # First pass: group by file size
        size_map = defaultdict(set)

        for i, book_id in enumerate(book_ids):
            if i % 100 == 0:
                self._progress(f"Scanning file sizes", i, len(book_ids))

            formats = self.db.formats(book_id, index_is_id=True)
            if not formats:
                continue

            for fmt in formats.split(','):
                metadata = self.db.format_metadata(book_id, fmt)
                if metadata and 'size' in metadata:
                    size_map[metadata['size']].add((book_id, fmt))

        # Remove size groups with only one member
        size_map = {k: v for k, v in size_map.items() if len(v) > 1}
        self._log(f"Found {len(size_map)} size collisions")

        # Second pass: calculate hashes only for size collisions
        candidates_map = defaultdict(set)
        total_to_hash = sum(len(v) for v in size_map.values())
        hashed = 0

        for size, size_group in size_map.items():
            for book_id, fmt in size_group:
                hashed += 1
                if hashed % 10 == 0:
                    self._progress(f"Computing hashes", hashed, total_to_hash)

                file_hash = self.db.format_hash(book_id, fmt)
                if file_hash:
                    candidates_map[(file_hash, size)].add(book_id)

        return candidates_map

    def _find_author_only_duplicates(self,
                                     book_ids: List[int],
                                     author_match: str,
                                     sort_by_title: bool) -> List[DuplicateGroup]:
        """
        Find duplicate authors (not books).

        Groups books by author variations that match.
        """
        candidates_map = defaultdict(set)
        author_bookids_map = defaultdict(set)

        author_fn = get_author_algorithm_fn(author_match)

        for i, book_id in enumerate(book_ids):
            if i % 100 == 0:
                self._progress(f"Analyzing authors", i, len(book_ids))

            authors = authors_to_list(self.db, book_id)
            if not authors:
                continue

            for author in authors:
                author_bookids_map[author].add(book_id)
                author_hash, rev_author_hash = author_fn(author)
                candidates_map[author_hash].add(author)
                if rev_author_hash and rev_author_hash != author_hash:
                    candidates_map[rev_author_hash].add(author)

        # Remove groups with less than 2 authors
        self._shrink_candidates_map(candidates_map)

        # Sort groups
        candidates_map = self._sort_candidate_groups(candidates_map, sort_by_title)

        # Convert author groups to book groups
        groups = []
        group_id = 0

        candidates_list = self._clean_dup_groups(candidates_map)
        for author_group in candidates_list:
            partition_groups = self._partition_using_exemptions(
                list(author_group), self.author_exemptions
            )
            for partition in partition_groups:
                if len(partition) > 1:
                    # Get all books for these authors
                    book_ids_in_group = set()
                    for author in partition:
                        book_ids_in_group |= author_bookids_map[author]

                    if len(book_ids_in_group) > 1:
                        group_id += 1
                        groups.append(DuplicateGroup(
                            group_id=group_id,
                            book_ids=sorted(book_ids_in_group),
                            match_key=str(partition)
                        ))

        return groups

    def _shrink_candidates_map(self, candidates_map: Dict) -> None:
        """Remove all groups with less than 2 members."""
        keys_to_remove = [k for k, v in candidates_map.items() if len(v) < 2]
        for key in keys_to_remove:
            del candidates_map[key]

    def _sort_candidate_groups(self,
                               candidates_map: Dict,
                               by_title: bool) -> OrderedDict:
        """Sort candidate groups by title or by size."""
        if by_title:
            skeys = sorted(candidates_map.keys())
        else:
            skeys = sorted(
                candidates_map.keys(),
                key=lambda k: (len(candidates_map[k]), k),
                reverse=True
            )
        return OrderedDict((k, candidates_map[k]) for k in skeys)

    def _clean_dup_groups(self, candidates_map: Dict) -> List[Set]:
        """
        Convert dict of sets to list, removing subsets.

        If set A is a subset of set B, only keep B.
        """
        res = [set(d) for d in candidates_map.values()]
        res.sort(key=lambda x: len(x))

        candidates_list = []
        for i, a in enumerate(res):
            for b in res[i+1:]:
                if a.issubset(b):
                    break
            else:
                candidates_list.append(a)

        return candidates_list

    def _partition_using_exemptions(self,
                                    data_items: List,
                                    exemptions: ExemptionsMap) -> List[List]:
        """
        Partition a group based on exemptions.

        If items A and B are in the exemptions, they should not be
        in the same group. This splits the group accordingly.
        """
        data_items = sorted(data_items)
        results: List[Set] = [set(data_items)]
        partitioning_ids: List[Any] = [None]

        for one_dup in data_items:
            if one_dup in exemptions:
                ndm_entry = exemptions.merge_sets(one_dup)
                for i, res in enumerate(results):
                    if one_dup in res:
                        if one_dup == partitioning_ids[i]:
                            results[i] = (res - ndm_entry) | {one_dup}
                            continue

                        results[i] = (res - ndm_entry) | {one_dup}
                        for nd in ndm_entry:
                            if nd > one_dup and nd in res:
                                results.append((res - ndm_entry - {one_dup}) | {nd})
                                partitioning_ids.append(nd)

        # Filter to groups with > 1 member and sort
        sr = [sorted(list(r)) for r in results if len(r) > 1]
        sr.sort()
        return sr

    def _convert_to_groups(self,
                          candidates_map: OrderedDict,
                          exemptions: ExemptionsMap) -> List[DuplicateGroup]:
        """Convert candidates map to list of DuplicateGroup objects."""
        groups = []
        group_id = 0

        candidates_list = self._clean_dup_groups(candidates_map)

        for book_ids in candidates_list:
            partition_groups = self._partition_using_exemptions(
                list(book_ids), exemptions
            )
            for partition in partition_groups:
                if len(partition) > 1:
                    group_id += 1
                    groups.append(DuplicateGroup(
                        group_id=group_id,
                        book_ids=sorted(partition)
                    ))

        return groups

    def get_summary(self, groups: List[DuplicateGroup]) -> Dict[str, Any]:
        """
        Get summary statistics about duplicate groups.

        Args:
            groups: List of DuplicateGroup from find_duplicates()

        Returns:
            Dict with summary stats
        """
        if not groups:
            return {
                'total_groups': 0,
                'total_books': 0,
                'duplicates_to_remove': 0,
                'largest_group': 0,
                'avg_group_size': 0.0,
            }

        total_books = sum(len(g) for g in groups)
        sizes = [len(g) for g in groups]

        return {
            'total_groups': len(groups),
            'total_books': total_books,
            'duplicates_to_remove': total_books - len(groups),  # Keep 1 from each group
            'largest_group': max(sizes),
            'avg_group_size': sum(sizes) / len(sizes),
        }

    def get_detailed_groups(self, groups: List[DuplicateGroup]) -> List[Dict[str, Any]]:
        """
        Get detailed information about each duplicate group.

        Args:
            groups: List of DuplicateGroup from find_duplicates()

        Returns:
            List of dicts with book details for each group
        """
        detailed = []

        for group in groups:
            books = []
            for book_id in group.book_ids:
                books.append(self.db.get_book_info(book_id))

            detailed.append({
                'group_id': group.group_id,
                'book_count': len(group),
                'books': books,
            })

        return detailed


# Convenience function for simple usage
def find_duplicates(library_path: str,
                   title_match: str = 'similar',
                   author_match: str = 'similar',
                   **kwargs) -> List[DuplicateGroup]:
    """
    Find duplicates in a Calibre library.

    Convenience function that handles database connection.

    Args:
        library_path: Path to Calibre library folder
        title_match: Title matching algorithm
        author_match: Author matching algorithm
        **kwargs: Additional arguments passed to DuplicateFinder.find_duplicates()

    Returns:
        List of DuplicateGroup objects
    """
    # Import here to avoid circular dependency
    from ..core.database import CalibreDB

    with CalibreDB(library_path) as db:
        finder = DuplicateFinder(db)
        return finder.find_duplicates(
            title_match=title_match,
            author_match=author_match,
            **kwargs
        )
