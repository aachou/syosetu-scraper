# syosetu-scraper — AGENTS.md

## Repo structure

Single-file Python project. All logic in `syosetu_scraper.py` (~300 lines). No tests, no CI, no linter/formatter config.

## Setup

```bash
uv sync           # install deps from uv.lock
```

- Requires **Python 3.14+** (`.python-version`, `pyproject.toml`), `__version__ = "0.2.0"`
- Dependencies: `aiohttp`, `beautifulsoup4`, `ebooklib`, `tqdm`

## Run

```bash
uv run python syosetu_scraper.py n3170ed
uv run python syosetu_scraper.py n3170ed --proxy http://127.0.0.1:7897
uv run python syosetu_scraper.py n3170ed -c 2 --delay 1
```

See `--help` for all options. No test/lint/typecheck scripts exist.

## Architecture notes

- **async concurrency**: asyncio + aiohttp, semaphore capped at configurable N (default 4)
- **Retry**: `get_soup` and `fetch_single_chapter` retry up to 3× with linear backoff (`2s × attempt`)
- **Checkpoint/resume**: per-chapter JSON saved to `data/<ncode>/chapter_XXXX.json`; existing files loaded and skipped on re-run
- **Temp cleanup**: `data/<ncode>/` deleted after successful EPUB generation unless `--keep-temp`
- **EPUB generation**: uses `ebooklib`; styles injected as a single CSS string (`STYLE_CONTENT`)
- **Hardcoded cookies**: `{'over18': 'yes'}` always sent
- **SSL verification**: disabled when proxy is active (`TCPConnector(ssl=False)`)
- **Proxy resolution order**: CLI arg > `HTTPS_PROXY` > `HTTP_PROXY` > `https_proxy` > `http_proxy`
- **Metadata parsing**: scrapes title, author, chapter list (supports multi-page ToC with "次へ" pagination)
- **Filename sanitization**: `re.sub(r'[<>:"/\\|?*]', '_', title)` — preserves all valid filename characters
- **CLI**: uses `argparse`, all config via flags (`-o`, `-c`, `--delay`, `--keep-temp`, `--version`)
- **`--delay`**: float seconds slep after each successful chapter fetch
