# Bunkr Scraper

This repository provides a small Python utility to scrape album links from `bunkr-albums.io`, walk each album, and download **videos under a size limit** (default: 50 MB).

## Requirements

* Python 3.10+
* Network access

The script only uses the Python standard library.

## Usage

```bash
python bunkr_scraper.py --search "JAV" --max-mb 50 --output downloads
```

### Useful flags

* `--search-url`: Use a full search URL (overrides `--search`).
* `--album-limit`: Limit number of albums processed.
* `--file-limit`: Limit number of files per album.
* `--zip-output`: Optional path to zip up the downloaded files at the end.

Example with a full URL:

```bash
python bunkr_scraper.py --search-url "https://bunkr-albums.io/?search=JAV" --max-mb 50
```

## Notes

* The scraper checks file size from the file page and falls back to a `HEAD` request.
* Files with unknown size or over the limit are skipped.
* Only common video extensions are downloaded (mp4, mkv, webm, mov, avi, wmv, m4v).
