"""
CLI duplicate detection module.

This module provides headless duplicate detection using algorithms
extracted from kiwidude's Find Duplicates plugin.
"""

from .matching import (
    # Title matching functions
    identical_title_match,
    similar_title_match,
    soundex_title_match,
    fuzzy_title_match,
    get_title_algorithm_fn,

    # Author matching functions
    identical_authors_match,
    similar_authors_match,
    soundex_authors_match,
    fuzzy_authors_match,
    get_author_algorithm_fn,

    # Core utilities
    soundex,
    fuzzy_it,
    authors_to_list,
)

from .finder import DuplicateFinder

__all__ = [
    'DuplicateFinder',
    'identical_title_match',
    'similar_title_match',
    'soundex_title_match',
    'fuzzy_title_match',
    'get_title_algorithm_fn',
    'identical_authors_match',
    'similar_authors_match',
    'soundex_authors_match',
    'fuzzy_authors_match',
    'get_author_algorithm_fn',
    'soundex',
    'fuzzy_it',
    'authors_to_list',
]
