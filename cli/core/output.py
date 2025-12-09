"""
Output formatting for CLI operations.
"""

from __future__ import unicode_literals, division, absolute_import, print_function

import json
import csv
import sys
from typing import List, Dict, Any, Optional, TextIO
from io import StringIO


class OutputFormatter:
    """
    Format output for CLI operations in various formats.
    """

    def __init__(self, format: str = 'text', file: TextIO = None):
        """
        Initialize output formatter.

        Args:
            format: Output format ('text', 'json', 'csv')
            file: Output file (default: sys.stdout)
        """
        self.format = format.lower()
        self.file = file or sys.stdout

    def output_duplicates(self, duplicate_groups: Dict[int, List[int]],
                          book_info_fn=None) -> str:
        """
        Format duplicate detection results.

        Args:
            duplicate_groups: Dict mapping group_id to list of book_ids
            book_info_fn: Optional function to get book info (id -> dict)

        Returns:
            Formatted output string
        """
        if self.format == 'json':
            return self._duplicates_json(duplicate_groups, book_info_fn)
        elif self.format == 'csv':
            return self._duplicates_csv(duplicate_groups, book_info_fn)
        else:
            return self._duplicates_text(duplicate_groups, book_info_fn)

    def _duplicates_text(self, groups: Dict[int, List[int]],
                         book_info_fn=None) -> str:
        """Format duplicates as human-readable text."""
        lines = []
        lines.append(f"Found {len(groups)} duplicate groups\n")
        lines.append("=" * 60)

        for group_id, book_ids in groups.items():
            lines.append(f"\nGroup {group_id} ({len(book_ids)} books):")
            lines.append("-" * 40)

            for book_id in book_ids:
                if book_info_fn:
                    info = book_info_fn(book_id)
                    title = info.get('title', 'Unknown')
                    authors = info.get('authors', 'Unknown')
                    lines.append(f"  [{book_id}] {title}")
                    lines.append(f"          by {authors}")
                else:
                    lines.append(f"  Book ID: {book_id}")

        return '\n'.join(lines)

    def _duplicates_json(self, groups: Dict[int, List[int]],
                         book_info_fn=None) -> str:
        """Format duplicates as JSON."""
        output = {
            'summary': {
                'total_groups': len(groups),
                'total_duplicates': sum(len(books) for books in groups.values())
            },
            'groups': []
        }

        for group_id, book_ids in groups.items():
            group_data = {
                'group_id': group_id,
                'book_count': len(book_ids),
                'books': []
            }

            for book_id in book_ids:
                if book_info_fn:
                    info = book_info_fn(book_id)
                    group_data['books'].append(info)
                else:
                    group_data['books'].append({'id': book_id})

            output['groups'].append(group_data)

        return json.dumps(output, indent=2, ensure_ascii=False)

    def _duplicates_csv(self, groups: Dict[int, List[int]],
                        book_info_fn=None) -> str:
        """Format duplicates as CSV."""
        output = StringIO()

        if book_info_fn:
            fieldnames = ['group_id', 'book_id', 'title', 'authors',
                          'series', 'isbn', 'formats']
        else:
            fieldnames = ['group_id', 'book_id']

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for group_id, book_ids in groups.items():
            for book_id in book_ids:
                row = {'group_id': group_id, 'book_id': book_id}

                if book_info_fn:
                    info = book_info_fn(book_id)
                    row['title'] = info.get('title', '')
                    row['authors'] = info.get('authors', '')
                    row['series'] = info.get('series', '')
                    row['isbn'] = info.get('isbn', '')
                    row['formats'] = info.get('formats', '')

                writer.writerow(row)

        return output.getvalue()

    def output_variations(self, variations: Dict[int, set],
                          item_map: Dict[int, str],
                          count_map: Dict[int, int]) -> str:
        """
        Format metadata variation results.

        Args:
            variations: Dict mapping item_id to set of similar item_ids
            item_map: Dict mapping item_id to item name
            count_map: Dict mapping item_id to usage count
        """
        if self.format == 'json':
            return self._variations_json(variations, item_map, count_map)
        elif self.format == 'csv':
            return self._variations_csv(variations, item_map, count_map)
        else:
            return self._variations_text(variations, item_map, count_map)

    def _variations_text(self, variations: Dict[int, set],
                         item_map: Dict[int, str],
                         count_map: Dict[int, int]) -> str:
        """Format variations as human-readable text."""
        lines = []
        lines.append(f"Found {len(variations)} variation groups\n")
        lines.append("=" * 60)

        for item_id, similar_ids in variations.items():
            item_name = item_map.get(item_id, str(item_id))
            count = count_map.get(item_id, 0)

            similar_names = []
            for sid in similar_ids:
                sname = item_map.get(sid, str(sid))
                scount = count_map.get(sid, 0)
                similar_names.append(f"{sname} ({scount} books)")

            lines.append(f"\n{item_name} ({count} books) => ")
            lines.append(f"  Similar: {', '.join(similar_names)}")

        return '\n'.join(lines)

    def _variations_json(self, variations: Dict[int, set],
                         item_map: Dict[int, str],
                         count_map: Dict[int, int]) -> str:
        """Format variations as JSON."""
        output = {
            'summary': {'total_groups': len(variations)},
            'variations': []
        }

        for item_id, similar_ids in variations.items():
            group = {
                'id': item_id,
                'name': item_map.get(item_id, str(item_id)),
                'count': count_map.get(item_id, 0),
                'similar': [
                    {
                        'id': sid,
                        'name': item_map.get(sid, str(sid)),
                        'count': count_map.get(sid, 0)
                    }
                    for sid in similar_ids
                ]
            }
            output['variations'].append(group)

        return json.dumps(output, indent=2, ensure_ascii=False)

    def _variations_csv(self, variations: Dict[int, set],
                        item_map: Dict[int, str],
                        count_map: Dict[int, int]) -> str:
        """Format variations as CSV."""
        output = StringIO()
        fieldnames = ['item_id', 'item_name', 'item_count',
                      'similar_id', 'similar_name', 'similar_count']

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for item_id, similar_ids in variations.items():
            for sid in similar_ids:
                writer.writerow({
                    'item_id': item_id,
                    'item_name': item_map.get(item_id, ''),
                    'item_count': count_map.get(item_id, 0),
                    'similar_id': sid,
                    'similar_name': item_map.get(sid, ''),
                    'similar_count': count_map.get(sid, 0)
                })

        return output.getvalue()

    def write(self, content: str):
        """Write content to output file."""
        print(content, file=self.file)
