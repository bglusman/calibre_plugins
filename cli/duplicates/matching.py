"""
Duplicate detection matching algorithms - headless version.

Ported from kiwidude's Find Duplicates plugin with Calibre dependencies removed.
Original: https://github.com/kiwidude68/calibre_plugins/tree/main/find_duplicates

This module provides pure Python implementations of:
- Title matching: identical, similar, soundex, fuzzy
- Author matching: identical, similar, soundex, fuzzy
- Series, publisher, tag matching algorithms
- Soundex phonetic algorithm

License: GPL v3
Original Copyright: 2011, Grant Drake
"""

from __future__ import unicode_literals, division, absolute_import, print_function

import re
import unicodedata
from typing import Optional, List, Tuple, Generator, Callable, Dict, Any

__license__ = 'GPL v3'
__copyright__ = '2011, Grant Drake'


# ----------------------------------------------------------------
#           Configuration - Soundex lengths
# ----------------------------------------------------------------

title_soundex_length = 6
author_soundex_length = 8
publisher_soundex_length = 6
series_soundex_length = 6
tags_soundex_length = 4

# Words to ignore in author names
ignore_author_words = ['von', 'van', 'jr', 'sr', 'i', 'ii', 'iii', 'second', 'third',
                       'md', 'phd']
IGNORE_AUTHOR_WORDS_MAP = dict((k, True) for k in ignore_author_words)

# Default title sort articles (replaces calibre.utils.config.tweaks)
# This matches Calibre's default - can be customized
DEFAULT_TITLE_SORT_ARTICLES = r'^(a|the|an)\s+'


# ----------------------------------------------------------------
#           Unicode normalization (replaces get_udc())
# ----------------------------------------------------------------

def decode_unicode(text: str) -> str:
    """
    Decode/normalize unicode text by converting accented characters to ASCII equivalents.

    This replaces Calibre's get_udc().decode() which uses unidecode.
    We use unicodedata.normalize with NFD decomposition and strip combining marks.

    Examples:
        "Miéville" -> "Mieville"
        "naïve" -> "naive"
        "Brontë" -> "Bronte"
    """
    if not text:
        return text

    # Normalize to NFD (decomposed form) - separates base chars from combining marks
    normalized = unicodedata.normalize('NFD', text)

    # Remove combining diacritical marks (category 'Mn')
    ascii_text = ''.join(
        char for char in normalized
        if unicodedata.category(char) != 'Mn'
    )

    return ascii_text


# ----------------------------------------------------------------
#           Soundex Length Configuration
# ----------------------------------------------------------------

def set_soundex_lengths(title_len: int, author_len: int) -> None:
    """Set soundex lengths for title and author matching."""
    global title_soundex_length, author_soundex_length
    title_soundex_length = title_len
    author_soundex_length = author_len


def set_title_soundex_length(title_len: int) -> None:
    """Set soundex length for title matching."""
    global title_soundex_length
    title_soundex_length = title_len


def set_author_soundex_length(author_len: int) -> None:
    """Set soundex length for author matching."""
    global author_soundex_length
    author_soundex_length = author_len


def set_publisher_soundex_length(publisher_len: int) -> None:
    """Set soundex length for publisher matching."""
    global publisher_soundex_length
    publisher_soundex_length = publisher_len


def set_series_soundex_length(series_len: int) -> None:
    """Set soundex length for series matching."""
    global series_soundex_length
    series_soundex_length = series_len


def set_tags_soundex_length(tags_len: int) -> None:
    """Set soundex length for tags matching."""
    global tags_soundex_length
    tags_soundex_length = tags_len


# ----------------------------------------------------------------
#           Helper Functions
# ----------------------------------------------------------------

def authors_to_list(db, book_id: int) -> List[str]:
    """
    Get authors for a book as a list.

    Args:
        db: CalibreDB instance
        book_id: Book ID

    Returns:
        List of author names
    """
    authors = db.authors(book_id, index_is_id=True)
    if authors:
        return [a.strip().replace('|', ',') for a in authors.split(',')]
    return []


def fuzzy_it(text: str, patterns: Optional[List[Tuple[re.Pattern, str]]] = None) -> str:
    """
    Apply fuzzy normalization to text.

    Removes punctuation, articles (a, the, an), normalizes whitespace.

    Args:
        text: Text to normalize
        patterns: Optional custom regex patterns (list of (pattern, replacement) tuples)

    Returns:
        Normalized text
    """
    fuzzy_title_patterns = [
        (re.compile(pat, re.IGNORECASE), repl) for pat, repl in [
            (r'[\[\](){}<>\'";,:#]', ''),
            (DEFAULT_TITLE_SORT_ARTICLES, ''),
            (r'[-._]', ' '),
            (r'\s+', ' ')
        ]
    ]

    if not patterns:
        patterns = fuzzy_title_patterns

    text = text.strip().lower()
    for pat, repl in patterns:
        text = pat.sub(repl, text)
    return text.strip()


# ----------------------------------------------------------------
#           Soundex Algorithm
# ----------------------------------------------------------------

def soundex(name: str, length: int = 4) -> str:
    """
    Soundex phonetic algorithm conforming to Knuth's algorithm.

    Implementation 2000-12-24 by Gregory Jorgensen (public domain)
    http://code.activestate.com/recipes/52213-soundex-algorithm/

    Args:
        name: Name to convert to soundex code
        length: Length of output soundex code (default 4)

    Returns:
        Soundex code
    """
    # Digits hold the soundex values for the alphabet
    #         ABCDEFGHIJKLMNOPQRSTUVWXYZ
    digits = '01230120022455012623010202'
    sndx = ''
    fc = ''
    orda = ord('A')
    ordz = ord('Z')

    # Translate alpha chars in name to soundex digits
    for c in name.upper():
        ordc = ord(c)
        if orda <= ordc <= ordz:
            if not fc:
                fc = c  # Remember first letter
            d = digits[ordc - orda]
            # Duplicate consecutive soundex digits are skipped
            if not sndx or (d != sndx[-1]):
                sndx += d

    # Replace first digit with first alpha character
    sndx = fc + sndx[1:]

    # Remove all 0s from the soundex code
    sndx = sndx.replace('0', '')

    # Return soundex code padded to length characters
    return (sndx + (length * '0'))[:length]


# ----------------------------------------------------------------
#           Title Matching Algorithm Functions
# ----------------------------------------------------------------

def get_title_tokens(title: str, strip_subtitle: bool = True,
                     decode_non_ascii: bool = True) -> Generator[str, None, None]:
    """
    Take a title and return a list of tokens useful for an AND search query.

    Excludes subtitles (optionally), punctuation and a, the.

    Args:
        title: Book title
        strip_subtitle: Remove subtitle portion (default True)
        decode_non_ascii: Convert accented chars to ASCII (default True)

    Yields:
        Lowercase tokens
    """
    if title:
        # Strip sub-titles
        if strip_subtitle:
            subtitle = re.compile(r'([\(\[\{].*?[\)\]\}]|[/:\\].*$)')
            if len(subtitle.sub('', title)) > 1:
                title = subtitle.sub('', title)

        title_patterns = [
            (re.compile(pat, re.IGNORECASE), repl) for pat, repl in [
                # Remove things like: (2010) (Omnibus) etc.
                (r'(?i)[({\[](\d{4}|omnibus|anthology|hardcover|paperback|mass\s*market|edition|ed\.)[\])}]', ''),
                # Remove any strings that contain the substring edition inside parentheses
                (r'(?i)[({\[].*?(edition|ed.).*?[\]})]', ''),
                # Remove commas used as separators in numbers
                (r'(\d+),(\d+)', r'\1\2'),
                # Remove hyphens only if they have whitespace before them
                (r'(\s-)', ' '),
                # Remove single quotes not followed by 's'
                (r"'(?!s)", ''),
                # Replace other special chars with a space
                (r'''[:,;+!@#$%^&*(){}.`~"\s\[\]/]''', ' ')
            ]
        ]

        for pat, repl in title_patterns:
            title = pat.sub(repl, title)

        if decode_non_ascii:
            title = decode_unicode(title)

        tokens = title.split()
        for token in tokens:
            token = token.strip()
            if token and (token.lower() not in ('a', 'the')):
                yield token.lower()


def identical_title_match(title: str, lang: Optional[str] = None) -> str:
    """
    Create hash for identical title matching.

    Only matches exact titles (case-insensitive).
    """
    if lang:
        return lang + title.lower()
    return title.lower()


def similar_title_match(title: str, lang: Optional[str] = None) -> str:
    """
    Create hash for similar title matching.

    Normalizes unicode, removes articles/punctuation.
    """
    title = decode_unicode(title)
    result = fuzzy_it(title)
    if lang:
        return lang + result
    return result


def soundex_title_match(title: str, lang: Optional[str] = None) -> str:
    """
    Create hash for soundex title matching.

    Matches titles that sound similar (handles typos).
    """
    # Convert to an equivalent of "similar" title first before applying the soundex
    title = similar_title_match(title)
    result = soundex(title, title_soundex_length)
    if lang:
        return lang + result
    return result


def fuzzy_title_match(title: str, lang: Optional[str] = None) -> str:
    """
    Create hash for fuzzy title matching.

    Very aggressive - truncates at 'and', 'or', 'aka'.
    Matches titles with different subtitles.
    """
    title_tokens = list(get_title_tokens(title))
    # Strip everything after "and", "or" provided it is not first word - very aggressive!
    for i, tok in enumerate(title_tokens):
        if tok in ['&', 'and', 'or', 'aka'] and i > 0:
            title_tokens = title_tokens[:i]
            break
    result = ''.join(title_tokens)
    if lang:
        return lang + result
    return result


# ----------------------------------------------------------------
#           Author Matching Algorithm Functions
#
#  Note that these return two hashes:
#  - first is based on the author name supplied
#  - second (if not None) is based on swapping name order
# ----------------------------------------------------------------

def get_author_tokens(author: str, decode_non_ascii: bool = True,
                      strip_initials: bool = False) -> Generator[str, None, None]:
    """
    Take an author and return tokens useful for duplicate hash comparisons.

    This function tries to return tokens in first name middle names last name order,
    by assuming that if a comma is in the author name, the name is in
    lastname, other names form.

    Args:
        author: Author name
        decode_non_ascii: Convert accented chars to ASCII (default True)
        strip_initials: Remove single-letter initials (default False)

    Yields:
        Lowercase tokens
    """
    if author:
        # Ensure Last,First is treated same as Last, First
        comma_no_space_pat = re.compile(r',([^\s])')
        author = comma_no_space_pat.sub(', \\1', author)
        replace_pat = re.compile(r'[-+.:;]')
        au = replace_pat.sub(' ', author)

        if decode_non_ascii:
            au = decode_unicode(au)

        parts = au.split()
        if ',' in au:
            # au probably in ln, fn form
            parts = parts[1:] + parts[:1]

        # Leave ' in there for Irish names
        remove_pat = re.compile(r'[,!@#$%^&*(){}`~"\s\[\]/]')
        # We will ignore author initials of only one character
        min_length = 1 if strip_initials else 0

        for tok in parts:
            tok = remove_pat.sub('', tok).strip()
            if len(tok) > min_length and tok.lower() not in IGNORE_AUTHOR_WORDS_MAP:
                yield tok.lower()


def identical_authors_match(author: str) -> Tuple[str, Optional[str]]:
    """
    Create hash for identical author matching.

    Returns:
        Tuple of (hash, reversed_hash or None)
    """
    return author.lower(), None


def similar_authors_match(author: str) -> Tuple[str, Optional[str]]:
    """
    Create hash for similar author matching.

    Handles "First Last" vs "Last, First" equivalence.
    """
    author_tokens = list(get_author_tokens(author, strip_initials=True))
    ahash = ' '.join(author_tokens)
    rev_ahash = None
    if len(author_tokens) > 1:
        author_tokens = author_tokens[1:] + author_tokens[:1]
        rev_ahash = ' '.join(author_tokens)
    return ahash, rev_ahash


def soundex_authors_match(author: str) -> Tuple[str, Optional[str]]:
    """
    Create hash for soundex author matching.

    Matches authors with similar-sounding names.
    """
    # Convert to an equivalent of "similar" author first before applying the soundex
    author_tokens = list(get_author_tokens(author))
    if len(author_tokens) <= 1:
        return soundex(''.join(author_tokens)), None

    # Put the last name at front - soundex should focus on surname
    new_author_tokens = [author_tokens[-1]]
    new_author_tokens.extend(author_tokens[:-1])
    ahash = soundex(''.join(new_author_tokens), author_soundex_length)

    rev_ahash = None
    if len(author_tokens) > 1:
        rev_ahash = soundex(''.join(author_tokens), author_soundex_length)
    return ahash, rev_ahash


def fuzzy_authors_match(author: str) -> Tuple[str, Optional[str]]:
    """
    Create hash for fuzzy author matching.

    Uses initial + surname for very aggressive matching.
    """
    author_tokens = list(get_author_tokens(author))
    if not author_tokens:
        return '', None
    elif len(author_tokens) == 1:
        return author_tokens[0], None

    # Multiple tokens - create initial plus last token as surname
    # A. Bronte should return "ABronte" and "", not "BA"!
    new_author_tokens = [author_tokens[0][0], author_tokens[-1]]
    ahash = ''.join(new_author_tokens)
    return ahash, None


# ----------------------------------------------------------------
#           Series Matching Algorithm Functions
# ----------------------------------------------------------------

def get_series_tokens(series: str, decode_non_ascii: bool = True) -> Generator[str, None, None]:
    """
    Take a series and return tokens useful for duplicate hash comparisons.
    """
    ignore_words = ['the', 'a', 'and']
    if series:
        remove_pat = re.compile(r'[,!@#$%^&*(){}`~\'"\s\[\]/]')
        replace_pat = re.compile(r'[-+.:;]')
        s = replace_pat.sub(' ', series)
        if decode_non_ascii:
            s = decode_unicode(s)
        parts = s.split()
        for tok in parts:
            tok = remove_pat.sub('', tok).strip()
            if len(tok) > 0 and tok.lower() not in ignore_words:
                yield tok.lower()


def similar_series_match(series: str) -> str:
    """Create hash for similar series matching."""
    series_tokens = list(get_series_tokens(series))
    return ' '.join(series_tokens)


def soundex_series_match(series: str) -> str:
    """Create hash for soundex series matching."""
    series_tokens = list(get_series_tokens(series))
    if len(series_tokens) <= 1:
        return soundex(''.join(series_tokens))
    return soundex(''.join(series_tokens), series_soundex_length)


def fuzzy_series_match(series: str) -> str:
    """Create hash for fuzzy series matching - just first word."""
    series_tokens = list(get_series_tokens(series))
    if not series_tokens:
        return ''
    return series_tokens[0]


# ----------------------------------------------------------------
#           Publisher Matching Algorithm Functions
# ----------------------------------------------------------------

def get_publisher_tokens(publisher: str, decode_non_ascii: bool = True) -> Generator[str, None, None]:
    """
    Take a publisher and return tokens useful for duplicate hash comparisons.
    """
    ignore_words = ['the', 'inc', 'ltd', 'limited', 'llc', 'co', 'pty',
                    'usa', 'uk']
    if publisher:
        remove_pat = re.compile(r'[,!@#$%^&*(){}`~\'"\s\[\]/]')
        replace_pat = re.compile(r'[-+.:;]')
        p = replace_pat.sub(' ', publisher)
        if decode_non_ascii:
            p = decode_unicode(p)
        parts = p.split()
        for tok in parts:
            tok = remove_pat.sub('', tok).strip()
            if len(tok) > 0 and tok.lower() not in ignore_words:
                yield tok.lower()


def similar_publisher_match(publisher: str) -> str:
    """Create hash for similar publisher matching."""
    publisher_tokens = list(get_publisher_tokens(publisher))
    return ' '.join(publisher_tokens)


def soundex_publisher_match(publisher: str) -> str:
    """Create hash for soundex publisher matching."""
    publisher_tokens = list(get_publisher_tokens(publisher))
    if len(publisher_tokens) <= 1:
        return soundex(''.join(publisher_tokens))
    return soundex(''.join(publisher_tokens), publisher_soundex_length)


def fuzzy_publisher_match(publisher: str) -> str:
    """
    Create hash for fuzzy publisher matching.

    Just first name, unless single letter then first two.
    """
    publisher_tokens = list(get_publisher_tokens(publisher))
    if not publisher_tokens:
        return ''
    first = publisher_tokens[0]
    if len(first) > 1 or len(publisher_tokens) == 1:
        return first
    return ' '.join(publisher_tokens[:2])


# ----------------------------------------------------------------
#           Tag Matching Algorithm Functions
# ----------------------------------------------------------------

def get_tag_tokens(tag: str, decode_non_ascii: bool = True) -> Generator[str, None, None]:
    """
    Take a tag and return tokens useful for duplicate hash comparisons.
    """
    ignore_words = ['the', 'and', 'a']
    if tag:
        remove_pat = re.compile(r'[,!@#$%^&*(){}`~\'"\s\[\]/]')
        replace_pat = re.compile(r'[-+.:;]')
        t = replace_pat.sub(' ', tag)
        if decode_non_ascii:
            t = decode_unicode(t)
        parts = t.split()
        for tok in parts:
            tok = remove_pat.sub('', tok).strip()
            if len(tok) > 0 and tok.lower() not in ignore_words:
                yield tok.lower()


def similar_tags_match(tag: str) -> str:
    """Create hash for similar tag matching."""
    tag_tokens = list(get_tag_tokens(tag))
    return ' '.join(tag_tokens)


def soundex_tags_match(tag: str) -> str:
    """Create hash for soundex tag matching."""
    tag_tokens = list(get_tag_tokens(tag))
    if len(tag_tokens) <= 1:
        return soundex(''.join(tag_tokens))
    return soundex(''.join(tag_tokens), publisher_soundex_length)


def fuzzy_tags_match(tag: str) -> str:
    """Create hash for fuzzy tag matching - just first word."""
    tag_tokens = list(get_tag_tokens(tag))
    if not tag_tokens:
        return ''
    return tag_tokens[0]


# ----------------------------------------------------------------
#           Algorithm Factory Functions
# ----------------------------------------------------------------

def get_title_algorithm_fn(title_match: str) -> Optional[Callable[[str, Optional[str]], str]]:
    """
    Return the appropriate function for the desired title match.

    Args:
        title_match: One of 'identical', 'similar', 'soundex', 'fuzzy'

    Returns:
        Matching function or None if invalid
    """
    algorithms = {
        'identical': identical_title_match,
        'similar': similar_title_match,
        'soundex': soundex_title_match,
        'fuzzy': fuzzy_title_match,
    }
    return algorithms.get(title_match)


def get_author_algorithm_fn(author_match: str) -> Optional[Callable[[str], Tuple[str, Optional[str]]]]:
    """
    Return the appropriate function for the desired author match.

    Args:
        author_match: One of 'identical', 'similar', 'soundex', 'fuzzy'

    Returns:
        Matching function or None if invalid
    """
    algorithms = {
        'identical': identical_authors_match,
        'similar': similar_authors_match,
        'soundex': soundex_authors_match,
        'fuzzy': fuzzy_authors_match,
    }
    return algorithms.get(author_match)


def get_variation_algorithm_fn(match_type: str, item_type: str) -> Callable:
    """
    Return the appropriate function for the desired variation match.

    Args:
        match_type: One of 'similar', 'soundex', 'fuzzy'
        item_type: One of 'authors', 'series', 'publisher', 'tags'

    Returns:
        Matching function
    """
    fn_name = f'{match_type}_{item_type}_match'
    return globals()[fn_name]


# ----------------------------------------------------------------
#                        Test Code
# ----------------------------------------------------------------

def do_assert_tests() -> None:
    """Run internal self-tests for all matching algorithms."""

    def _assert(test_name: str, match_type: str, item_type: str,
                value1: str, value2: str, equal: bool = True) -> None:
        fn = get_variation_algorithm_fn(match_type, item_type)
        hash1 = fn(value1)
        hash2 = fn(value2)
        if (equal and hash1 != hash2) or (not equal and hash1 == hash2):
            print(f'Failed: {test_name} {match_type} {item_type} (\'{value1}\', \'{value2}\')')
            print(f' hash1: {hash1}')
            print(f' hash2: {hash2}')

    def assert_match(match_type: str, item_type: str, value1: str, value2: str) -> None:
        _assert('is matching', match_type, item_type, value1, value2, equal=True)

    def assert_nomatch(match_type: str, item_type: str, value1: str, value2: str) -> None:
        _assert('not matching', match_type, item_type, value1, value2, equal=False)

    def _assert_author(test_name: str, match_type: str, item_type: str,
                       value1: str, value2: str, equal: bool = True) -> None:
        fn = get_variation_algorithm_fn(match_type, item_type)
        hash1, rev_hash1 = fn(value1)
        hash2, rev_hash2 = fn(value2)
        results_equal = hash1 in [hash2, rev_hash2] or \
            (rev_hash1 is not None and rev_hash1 in [hash2, rev_hash2])
        if (equal and not results_equal) or (not equal and results_equal):
            print(f'Failed: {test_name} {match_type} {item_type} (\'{value1}\', \'{value2}\')')
            print(f' hash1: {hash1}  rev_hash1: {rev_hash1}')
            print(f' hash2: {hash2}  rev_hash2: {rev_hash2}')

    def assert_author_match(match_type: str, item_type: str, value1: str, value2: str) -> None:
        _assert_author('is matching', match_type, item_type, value1, value2, equal=True)

    def assert_author_nomatch(match_type: str, item_type: str, value1: str, value2: str) -> None:
        _assert_author('not matching', match_type, item_type, value1, value2, equal=False)

    # Test identical title algorithms
    assert_match('identical', 'title', 'The Martian Way', 'The Martian Way')
    assert_match('identical', 'title', 'The Martian Way', 'the martian way')
    assert_nomatch('identical', 'title', 'The Martian Way', 'Martian Way')
    assert_nomatch('identical', 'title', 'China Miéville', 'China Mieville')

    # Test similar title algorithms
    assert_match('similar', 'title', 'The Martian Way', 'The Martian Way')
    assert_match('similar', 'title', 'The Martian Way', 'the martian way')
    assert_match('similar', 'title', 'The Martian Way', 'Martian Way')
    assert_match('similar', 'title', 'China Miéville', 'China Mieville')
    assert_nomatch('similar', 'title', 'The Martian Way', 'The Martain Way')

    # Test soundex title algorithms
    assert_match('soundex', 'title', 'The Martian Way', 'The Martian Way')
    assert_match('soundex', 'title', 'The Martian Way', 'The Martain Way')
    assert_match('soundex', 'title', 'Angel', 'Angle')
    assert_match('soundex', 'title', 'China Miéville', 'China Mieville')

    # Test fuzzy title algorithms
    assert_match('fuzzy', 'title', 'The Martian Way', 'The Martian Way')
    assert_match('fuzzy', 'title', 'The Martian Way', 'The Martian Way (Foo)')
    assert_match('fuzzy', 'title', 'The Martian Way', 'The Martian Way and other stories')
    assert_match('fuzzy', 'title', 'China Miéville', 'China Mieville')
    assert_nomatch('fuzzy', 'title', 'The Martian Way', 'The Martain Way')

    # Test identical author algorithms
    assert_author_match('identical', 'authors', 'Kevin J. Anderson', 'Kevin J. Anderson')
    assert_author_match('identical', 'authors', 'Kevin J. Anderson', 'Kevin j. Anderson')
    assert_author_nomatch('identical', 'authors', 'Kevin J. Anderson', 'Kevin J Anderson')

    # Test similar author algorithms
    assert_author_match('similar', 'authors', 'Kevin J. Anderson', 'Kevin J Anderson')
    assert_author_match('similar', 'authors', 'Kevin J. Anderson', 'Anderson, Kevin J.')
    assert_author_match('similar', 'authors', 'China Miéville', 'China Mieville')

    # Test soundex author algorithms
    assert_author_match('soundex', 'authors', 'Kevin J. Anderson', 'Keven J. Andersan')
    assert_author_match('soundex', 'authors', 'China Miéville', 'China Mieville')

    # Test fuzzy author algorithms
    assert_author_match('fuzzy', 'authors', 'Kevin J. Anderson', 'K. Anderson')
    assert_author_match('fuzzy', 'authors', 'China Miéville', 'China Mieville')
    assert_author_nomatch('fuzzy', 'authors', 'A. Brown', 'A. Bronte')

    # Test series algorithms
    assert_match('similar', 'series', 'China Miéville', 'China Mieville')
    assert_match('soundex', 'series', 'Angel', 'Angle')
    assert_match('fuzzy', 'series', 'China Miéville', 'China')

    # Test publisher algorithms
    assert_match('similar', 'publisher', 'Random House', 'Random House Inc')
    assert_match('soundex', 'publisher', 'Angel', 'Angle')
    assert_match('fuzzy', 'publisher', 'Random House Inc', 'Random')

    print('Tests completed')


# For testing, run from command line with:
# python -m cli.duplicates.matching
if __name__ == '__main__':
    do_assert_tests()
