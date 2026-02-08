#!/usr/bin/env python3
"""Scrape Bunkr album links from bunkr-albums.io and download small videos."""
from __future__ import annotations

import argparse
import html
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse, urlencode
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".wmv", ".m4v"}


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


def fetch_html(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="ignore")


def extract_links(html_text: str, base_url: str) -> list[str]:
    parser = LinkExtractor()
    parser.feed(html_text)
    return [urljoin(base_url, link) for link in parser.links]


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def collect_search_pages(search_url: str) -> list[str]:
    queue = [search_url]
    seen = set()
    pages: list[str] = []
    while queue:
        url = queue.pop(0)
        url = normalize_url(url)
        if url in seen:
            continue
        seen.add(url)
        pages.append(url)
        try:
            html_text = fetch_html(url)
        except Exception as exc:
            print(f"[warn] failed to fetch search page {url}: {exc}")
            continue
        for link in extract_links(html_text, url):
            if "bunkr-albums.io" in link and "search=" in link and "page=" in link:
                if link not in seen:
                    queue.append(link)
    return pages


def collect_album_links(search_pages: Iterable[str]) -> list[str]:
    albums: set[str] = set()
    for page_url in search_pages:
        try:
            html_text = fetch_html(page_url)
        except Exception as exc:
            print(f"[warn] failed to fetch search page {page_url}: {exc}")
            continue
        for link in extract_links(html_text, page_url):
            if "/a/" in link and "bunkr" in link:
                albums.add(normalize_url(link))
    return sorted(albums)


def collect_album_pages(album_url: str) -> list[str]:
    queue = [album_url]
    seen = set()
    pages: list[str] = []
    while queue:
        url = queue.pop(0)
        url = normalize_url(url)
        if url in seen:
            continue
        seen.add(url)
        pages.append(url)
        try:
            html_text = fetch_html(url)
        except Exception as exc:
            print(f"[warn] failed to fetch album page {url}: {exc}")
            continue
        for link in extract_links(html_text, url):
            if "?page=" in link and urlparse(link).path == urlparse(url).path:
                if link not in seen:
                    queue.append(link)
    return pages


def collect_file_links(album_pages: Iterable[str]) -> list[str]:
    files: set[str] = set()
    for page_url in album_pages:
        try:
            html_text = fetch_html(page_url)
        except Exception as exc:
            print(f"[warn] failed to fetch album page {page_url}: {exc}")
            continue
        for link in extract_links(html_text, page_url):
            if "/f/" in link:
                files.add(normalize_url(link))
    return sorted(files)


@dataclass
class FileInfo:
    file_url: str
    download_url: Optional[str]
    filename: Optional[str]
    size_bytes: Optional[int]


def parse_size(text: str) -> Optional[int]:
    match = re.search(r"([0-9.]+)\s*(KB|MB|GB)", text, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    multiplier = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[unit]
    return int(value * multiplier)


def parse_file_page(file_url: str) -> FileInfo:
    try:
        html_text = fetch_html(file_url)
    except Exception as exc:
        print(f"[warn] failed to fetch file page {file_url}: {exc}")
        return FileInfo(file_url=file_url, download_url=None, filename=None, size_bytes=None)

    download_url = None
    for link in extract_links(html_text, file_url):
        if "get.bunkrr" in link or "download" in link:
            download_url = link
            break

    title_match = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    filename = None
    if title_match:
        title_text = html.unescape(title_match.group(1)).strip()
        filename = title_text.split("|")[0].strip()

    size_bytes = parse_size(html_text)

    return FileInfo(
        file_url=file_url,
        download_url=download_url,
        filename=filename,
        size_bytes=size_bytes,
    )


def head_content_length(url: str, timeout: int = 20) -> Optional[int]:
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
        with urlopen(req, timeout=timeout) as resp:
            length = resp.headers.get("Content-Length")
            if length:
                return int(length)
    except Exception as exc:
        print(f"[warn] HEAD failed for {url}: {exc}")
    return None


def is_video_file(filename: str | None, download_url: str | None) -> bool:
    candidates = []
    if filename:
        candidates.append(filename)
    if download_url:
        candidates.append(urlparse(download_url).path)
    for name in candidates:
        ext = Path(name).suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            return True
    return False


def sanitize_filename(name: str) -> str:
    name = name.strip().replace("/", "_")
    return re.sub(r"[^A-Za-z0-9._()\- ]+", "_", name)


def download_file(url: str, destination: Path) -> None:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(req) as resp, destination.open("wb") as handle:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def build_search_url(base_url: str, search_term: str) -> str:
    parsed = urlparse(base_url)
    query = urlencode({"search": search_term})
    return parsed._replace(query=query).geturl()


def create_zip_archive(source_dir: Path, zip_path: Path) -> None:
    import zipfile

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape bunkr-albums.io search results and download small videos.",
    )
    parser.add_argument("--search", help="Search term for bunkr-albums.io")
    parser.add_argument(
        "--search-url",
        help="Full bunkr-albums.io search URL (overrides --search)",
    )
    parser.add_argument(
        "--base-url",
        default="https://bunkr-albums.io/",
        help="Base URL for bunkr-albums.io",
    )
    parser.add_argument(
        "--output",
        default="downloads",
        help="Directory to store downloaded videos",
    )
    parser.add_argument(
        "--max-mb",
        type=float,
        default=50.0,
        help="Maximum file size in megabytes",
    )
    parser.add_argument(
        "--album-limit",
        type=int,
        default=0,
        help="Limit number of albums processed (0 = no limit)",
    )
    parser.add_argument(
        "--file-limit",
        type=int,
        default=0,
        help="Limit number of files per album (0 = no limit)",
    )
    parser.add_argument(
        "--zip-output",
        help="Optional zip file path to store downloaded files",
    )
    args = parser.parse_args()

    if not args.search and not args.search_url:
        parser.error("Provide --search or --search-url")

    search_url = args.search_url or build_search_url(args.base_url, args.search)

    print(f"[info] collecting search pages from {search_url}")
    search_pages = collect_search_pages(search_url)
    print(f"[info] found {len(search_pages)} search pages")

    albums = collect_album_links(search_pages)
    if args.album_limit:
        albums = albums[: args.album_limit]
    print(f"[info] found {len(albums)} album links")

    max_bytes = int(args.max_mb * 1024 * 1024)
    output_dir = Path(args.output)

    for index, album_url in enumerate(albums, start=1):
        print(f"[info] ({index}/{len(albums)}) processing album {album_url}")
        album_pages = collect_album_pages(album_url)
        file_links = collect_file_links(album_pages)
        if args.file_limit:
            file_links = file_links[: args.file_limit]
        print(f"[info] found {len(file_links)} files in album")

        for file_url in file_links:
            info = parse_file_page(file_url)
            if not info.download_url:
                print(f"[warn] no download url for {file_url}")
                continue
            if not is_video_file(info.filename, info.download_url):
                print(f"[skip] not a video {info.filename or info.download_url}")
                continue

            size_bytes = info.size_bytes
            if size_bytes is None:
                size_bytes = head_content_length(info.download_url)
            if size_bytes is None:
                print(f"[skip] unknown size for {info.download_url}")
                continue
            if size_bytes > max_bytes:
                print(
                    f"[skip] {info.download_url} size {size_bytes / 1024 / 1024:.2f}MB > limit",
                )
                continue

            filename = info.filename or Path(urlparse(info.download_url).path).name
            filename = sanitize_filename(filename)
            dest = output_dir / sanitize_filename(urlparse(album_url).path.strip("/") or "album")
            dest_file = dest / filename
            if dest_file.exists():
                print(f"[skip] already downloaded {dest_file}")
                continue
            print(f"[download] {info.download_url} -> {dest_file}")
            try:
                download_file(info.download_url, dest_file)
            except Exception as exc:
                print(f"[warn] failed download {info.download_url}: {exc}")
            time.sleep(0.5)

    if args.zip_output:
        zip_path = Path(args.zip_output)
        print(f"[info] creating zip archive at {zip_path}")
        create_zip_archive(output_dir, zip_path)

    print("[info] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
