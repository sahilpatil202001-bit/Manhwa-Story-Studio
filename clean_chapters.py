#!/usr/bin/env python
"""
Command-line shortcut for the Chapter Cleaner & Unpacker.
Usage:
    python clean_chapters.py ch2
    python clean_chapters.py ch2 ch3 ch4
    python clean_chapters.py --path "assets/inbox/The Greatest Estate Developer"
    python clean_chapters.py              (scans assets/inbox by default)
"""

import sys
from pathlib import Path

# Add src/ to python path so manhwa_studio can be imported directly
project_root = Path(__file__).resolve().parent
src_dir = project_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import argparse
from manhwa_studio.ingestion.chapter_cleaner import clean_and_unpack_inbox


def main():
    parser = argparse.ArgumentParser(
        description="Extract clean chapter images, skip ads/duplicates, and remove zip archives.",
    )
    parser.add_argument(
        "folders",
        nargs="*",
        help="Specific chapter folder(s) to process (e.g. ch2, ch3 or 2 3). If omitted, scans all subfolders.",
    )
    parser.add_argument(
        "--path",
        "-p",
        type=str,
        default="assets/inbox",
        help="Root directory where chapter folders/zips are located (default: assets/inbox)",
    )
    parser.add_argument(
        "--keep-zip",
        action="store_true",
        help="Keep the zip archive after extraction (default: deletes zip)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without extracting or deleting anything",
    )
    args = parser.parse_args()

    target_dir = Path(args.path).resolve()
    print(f"📦 Scanning for chapter zips in: {target_dir}")
    if args.folders:
        print(f"🎯 Target folders/chapters: {args.folders}")

    cleaned = clean_and_unpack_inbox(
        root_dir=target_dir,
        folders=args.folders if args.folders else None,
        delete_zip=not args.keep_zip,
        dry_run=args.dry_run,
    )
    print(f"🏁 Finished! Successfully processed {cleaned} chapter(s).")


if __name__ == "__main__":
    main()
