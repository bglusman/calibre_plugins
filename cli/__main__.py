#!/usr/bin/env python3
"""
Calibre Plugin CLI - Headless duplicate detection and library analysis.

This is a command-line interface for running Calibre plugin algorithms
without the Calibre GUI. Designed for use with calibre-web-automated or
other headless Calibre setups.

Usage:
    calibre-cli duplicates /path/to/library [options]
    calibre-cli duplicates /path/to/library --title-match similar --author-match fuzzy
    calibre-cli duplicates /path/to/library --format json > duplicates.json

License: GPL v3
"""

from __future__ import unicode_literals, division, absolute_import, print_function

import argparse
import sys
import json
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional

from .core.database import CalibreDB
from .core.progress import ProgressReporter, NullProgress
from .core.output import OutputFormatter
from .duplicates.finder import DuplicateFinder, DuplicateGroup


__version__ = '0.1.0'


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog='calibre-cli',
        description='Headless Calibre library analysis tools',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Find duplicates with default settings:
    calibre-cli duplicates /path/to/library

  Find duplicates with fuzzy matching:
    calibre-cli duplicates /path/to/library --title-match fuzzy --author-match fuzzy

  Find books with duplicate ISBNs:
    calibre-cli duplicates /path/to/library --search-type identifier --identifier isbn

  Find binary duplicate files:
    calibre-cli duplicates /path/to/library --search-type binary

  Output as JSON:
    calibre-cli duplicates /path/to/library --format json > duplicates.json

  Output as CSV for spreadsheet import:
    calibre-cli duplicates /path/to/library --format csv > duplicates.csv

Match Types:
  identical  - Exact match (case-insensitive)
  similar    - Normalized match (removes articles, punctuation, accents)
  soundex    - Phonetic match (catches typos/spelling variations)
  fuzzy      - Very aggressive (ignores subtitles, 'and', 'or')
"""
    )

    parser.add_argument(
        '--version', '-V',
        action='version',
        version=f'%(prog)s {__version__}'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Duplicates command
    dup_parser = subparsers.add_parser(
        'duplicates', aliases=['dups', 'dup'],
        help='Find duplicate books in the library'
    )
    dup_parser.add_argument(
        'library_path',
        help='Path to Calibre library folder (containing metadata.db)'
    )
    dup_parser.add_argument(
        '--search-type', '-s',
        choices=['title_author', 'identifier', 'binary', 'author_only'],
        default='title_author',
        help='Type of duplicate search (default: title_author)'
    )
    dup_parser.add_argument(
        '--title-match', '-t',
        choices=['identical', 'similar', 'soundex', 'fuzzy', 'ignore'],
        default='similar',
        help='Title matching algorithm (default: similar)'
    )
    dup_parser.add_argument(
        '--author-match', '-a',
        choices=['identical', 'similar', 'soundex', 'fuzzy', 'ignore'],
        default='similar',
        help='Author matching algorithm (default: similar)'
    )
    dup_parser.add_argument(
        '--identifier', '-i',
        default='isbn',
        help='Identifier type for identifier search (default: isbn)'
    )
    dup_parser.add_argument(
        '--include-languages', '-l',
        action='store_true',
        help='Consider language when matching (different languages = not duplicates)'
    )
    dup_parser.add_argument(
        '--format', '-f',
        choices=['text', 'json', 'csv'],
        default='text',
        help='Output format (default: text)'
    )
    dup_parser.add_argument(
        '--sort-by-size',
        action='store_true',
        help='Sort groups by size (largest first) instead of title'
    )
    dup_parser.add_argument(
        '--summary', '-S',
        action='store_true',
        help='Only show summary statistics, not individual groups'
    )
    dup_parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress progress output'
    )
    dup_parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug output'
    )
    dup_parser.add_argument(
        '--output', '-o',
        type=str,
        help='Output file path (default: stdout)'
    )

    # Info command (library info)
    info_parser = subparsers.add_parser(
        'info',
        help='Show library information'
    )
    info_parser.add_argument(
        'library_path',
        help='Path to Calibre library folder'
    )
    info_parser.add_argument(
        '--format', '-f',
        choices=['text', 'json'],
        default='text',
        help='Output format (default: text)'
    )

    return parser


def cmd_duplicates(args) -> int:
    """Execute the duplicates command."""
    library_path = Path(args.library_path)

    if not library_path.exists():
        print(f"Error: Library path does not exist: {library_path}", file=sys.stderr)
        return 1

    db_path = library_path / 'metadata.db'
    if not db_path.exists():
        print(f"Error: No metadata.db found at {library_path}", file=sys.stderr)
        print("Make sure this is a valid Calibre library folder.", file=sys.stderr)
        return 1

    # Setup progress callback
    def progress_callback(message: str, current: int, total: int):
        if not args.quiet:
            if total > 0:
                percent = int(100 * current / total)
                print(f"\r{message}: {percent}%", end='', file=sys.stderr, flush=True)
            else:
                print(f"\r{message}", end='', file=sys.stderr, flush=True)

    try:
        with CalibreDB(str(library_path)) as db:
            finder = DuplicateFinder(
                db,
                progress_callback=None if args.quiet else progress_callback,
                debug=args.debug
            )

            # Run duplicate search
            groups = finder.find_duplicates(
                search_type=args.search_type,
                title_match=args.title_match,
                author_match=args.author_match,
                identifier_type=args.identifier,
                include_languages=args.include_languages,
                sort_by_title=not args.sort_by_size
            )

            # Clear progress line
            if not args.quiet:
                print("", file=sys.stderr)

            # Get output file
            if args.output:
                output_file = open(args.output, 'w', encoding='utf-8')
            else:
                output_file = sys.stdout

            try:
                if args.summary:
                    # Summary only
                    summary = finder.get_summary(groups)
                    output_summary(summary, args.format, output_file)
                else:
                    # Full results
                    output_duplicates(groups, db, args.format, output_file)
            finally:
                if args.output:
                    output_file.close()

            return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


def output_summary(summary: Dict[str, Any], format: str, file) -> None:
    """Output summary statistics."""
    if format == 'json':
        json.dump(summary, file, indent=2)
        file.write('\n')
    else:
        print("Duplicate Search Summary", file=file)
        print("=" * 40, file=file)
        print(f"Total duplicate groups: {summary['total_groups']}", file=file)
        print(f"Total books in groups:  {summary['total_books']}", file=file)
        print(f"Duplicates to remove:   {summary['duplicates_to_remove']}", file=file)
        print(f"Largest group size:     {summary['largest_group']}", file=file)
        print(f"Average group size:     {summary['avg_group_size']:.1f}", file=file)


def output_duplicates(groups: List[DuplicateGroup], db: CalibreDB,
                      format: str, file) -> None:
    """Output duplicate groups."""
    if format == 'json':
        output = {
            'summary': {
                'total_groups': len(groups),
                'total_books': sum(len(g) for g in groups),
            },
            'groups': []
        }

        for group in groups:
            group_data = {
                'group_id': group.group_id,
                'book_count': len(group),
                'books': []
            }

            for book_id in group.book_ids:
                book_info = db.get_book_info(book_id)
                group_data['books'].append(book_info)

            output['groups'].append(group_data)

        json.dump(output, file, indent=2, ensure_ascii=False)
        file.write('\n')

    elif format == 'csv':
        writer = csv.writer(file)
        writer.writerow(['group_id', 'book_id', 'title', 'authors', 'series',
                        'isbn', 'formats', 'path'])

        for group in groups:
            for book_id in group.book_ids:
                info = db.get_book_info(book_id)
                writer.writerow([
                    group.group_id,
                    book_id,
                    info.get('title', ''),
                    info.get('authors', ''),
                    info.get('series', ''),
                    info.get('isbn', ''),
                    info.get('formats', ''),
                    info.get('path', ''),
                ])
    else:
        # Text format
        print(f"Found {len(groups)} duplicate groups", file=file)
        print(f"Total books: {sum(len(g) for g in groups)}", file=file)
        print("=" * 70, file=file)

        for group in groups:
            print(f"\nGroup {group.group_id} ({len(group)} books):", file=file)
            print("-" * 50, file=file)

            for book_id in group.book_ids:
                info = db.get_book_info(book_id)
                title = info.get('title', 'Unknown')
                authors = info.get('authors', 'Unknown')
                formats = info.get('formats', 'None')

                print(f"  [{book_id}] {title}", file=file)
                print(f"          by {authors}", file=file)
                print(f"          formats: {formats}", file=file)


def cmd_info(args) -> int:
    """Execute the info command."""
    library_path = Path(args.library_path)

    if not library_path.exists():
        print(f"Error: Library path does not exist: {library_path}", file=sys.stderr)
        return 1

    try:
        with CalibreDB(str(library_path)) as db:
            info = {
                'library_path': str(library_path.absolute()),
                'book_count': db.book_count(),
            }

            if args.format == 'json':
                json.dump(info, sys.stdout, indent=2)
                print()
            else:
                print("Calibre Library Info", file=sys.stdout)
                print("=" * 40, file=sys.stdout)
                print(f"Path:       {info['library_path']}", file=sys.stdout)
                print(f"Book count: {info['book_count']}", file=sys.stdout)

            return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ('duplicates', 'dups', 'dup'):
        return cmd_duplicates(args)
    elif args.command == 'info':
        return cmd_info(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
