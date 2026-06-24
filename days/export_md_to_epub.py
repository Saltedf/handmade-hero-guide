#!/usr/bin/env python3
"""
md2epub - Merge Markdown files in a directory into one EPUB.

Sorting rules:
    1. README.md always comes first
    2. Files with numeric prefix (00-xxx, 01-xxx) sorted by number ascending
    3. Files without numeric prefix sorted by file creation time (oldest first)

Skipped by default: AGENTS.md, teaching-method.md

Usage:
    md2epub                                       # current directory
    md2epub path/to/dir --title 'My Book'         # specified directory
    md2epub --recursive --dry-run                  # recursive + preview only
"""
from __future__ import annotations

import argparse
import atexit
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKIP_NAMES = {"AGENTS.md", "teaching-method.md"}

# Temp files created for directory heading markers; cleaned up on exit
_temp_files: list[Path] = []


def _cleanup_temp_files() -> None:
    for f in _temp_files:
        try:
            f.unlink()
        except OSError:
            pass


atexit.register(_cleanup_temp_files)


def _make_heading_file(dirname: str) -> Path:
    """Create a temp .md file containing just a # heading for the directory name."""
    fd, path = tempfile.mkstemp(suffix=".md", prefix=f"heading-{dirname}-")
    p = Path(path)
    p.write_text(f"# {dirname}\n", encoding="utf-8")
    _temp_files.append(p)
    return p


def _file_birth_time(path: Path) -> float:
    """Return file birth time (creation time). Fall back to mtime if unavailable."""
    try:
        stat = path.stat()
        btime = getattr(stat, "st_birthtime", None)
        if btime is not None:
            return btime
        return stat.st_mtime
    except OSError:
        return float("inf")


def _entry_sort_key(entry: Path) -> tuple:
    """Sort key for a file or directory within the same level."""
    name = entry.name
    lower = name.lower()

    if entry.is_file() and lower == "readme.md":
        return (0, -1, 0.0, "")

    stem = Path(name).stem if entry.is_file() else name
    match = re.search(r"^(\d+)|(\d+)$", stem)

    # print(stem ,match)

    if match:
        number = int(match.group(1) or match.group(2))
        rest = re.sub(r"\d+[-_\s]*", "", stem).lower()
        print(rest)
        return (1, number, 0.0, rest)

    # No numeric prefix -- sort by creation time
    btime = _file_birth_time(entry)
    return (2, 0, btime, stem.lower())


def collect_markdown_files(root: Path, recursive: bool, extra_skip: set[str] | None = None) -> list[Path]:
    skip = SKIP_NAMES | (extra_skip or set())

    def _collect(directory: Path) -> list[Path]:
        entries: list[Path] = []
        for child in directory.iterdir():
            if child.name.startswith("."):
                continue
            if child.name in skip:
                continue
            if child.is_file() and child.suffix == ".md":
                entries.append(child)
            elif child.is_dir() and recursive:
                entries.append(child)

        entries.sort(key=_entry_sort_key)

        result: list[Path] = []
        for entry in entries:
            if entry.is_file():
                result.append(entry)
            else:
                # Insert a heading marker for the subdirectory, then recurse
                sub_files = _collect(entry)
                if sub_files:
                    result.append(_make_heading_file(entry.name))
                    result.extend(sub_files)
        return result

    return _collect(root)


def build_pandoc_command(files: list[Path], output: Path, title: str) -> list[str]:
    return [
        "pandoc",
        *[str(path) for path in files],
        "--toc",
        "--split-level=1",
        "--metadata",
        f"title={title}",
        "-o",
        str(output),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge Markdown files in a directory into one EPUB."
    )
    parser.add_argument("directory", nargs="?", default=".", help="Markdown directory (default: current directory)")
    parser.add_argument(
        "-o",
        "--output",
        help="Output EPUB path; defaults to <dirname>.epub inside the directory",
    )
    parser.add_argument(
        "--title",
        help="EPUB title; defaults to directory name",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recursively collect Markdown files from subdirectories",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="*",
        default=[],
        help="Additional filenames to skip (e.g. --exclude CHANGELOG.md TODO.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print merge order and pandoc command, do not generate EPUB",
    )
    return parser.parse_args()


def shutil_which(name: str) -> str | None:
    from shutil import which
    return which(name)


def main() -> int:
    args = parse_args()
    root = Path(args.directory).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1

    if not shutil_which("pandoc"):
        print("pandoc not found. Please install pandoc first.", file=sys.stderr)
        return 1

    files = collect_markdown_files(root, recursive=args.recursive, extra_skip={Path(e).name for e in args.exclude})
    if not files:
        print(f"No Markdown files found in: {root}", file=sys.stderr)
        return 1

    title = args.title or root.name
    output = Path(args.output).expanduser().resolve() if args.output else root / f"{root.name}.epub"
    output.parent.mkdir(parents=True, exist_ok=True)

    print("Merge order:")
    temp_set = set(_temp_files)
    for index, path in enumerate(files, start=1):
        if path in temp_set:
            # Extract directory name from the heading file content
            heading = path.read_text(encoding="utf-8").strip().lstrip("# ")
            print(f"  {index:02d}. [{heading}]")
        else:
            print(f"  {index:02d}. {path.relative_to(root)}")

    cmd = build_pandoc_command(files, output, title)
    if args.dry_run:
        print("\npandoc command:")
        print(" ".join(cmd))
        return 0

    subprocess.run(cmd, check=True)
    print(f"\nGenerated: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
