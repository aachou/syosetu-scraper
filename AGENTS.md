# syosetu-scraper — AGENTS.md

## Repo structure

Multi-file project. Entry point is `syosetu_scraper.py` (~70 lines). Core logic in `core/` package (`fetch.py` + `book.py`). Tests in `tests/`. CI in `.github/workflows/ci.yml`.

## Setup

```bash
uv sync           # install deps from uv.lock
```

- Requires **Python 3.14+** (`.python-version`, `pyproject.toml`), `__version__ = "0.2.0"`
- Dependencies: `aiohttp`, `beautifulsoup4`, `ebooklib`, `tqdm`
- Dev dependencies: `pytest`, `pytest-asyncio`

## Run

```bash
uv run python syosetu_scraper.py n3170ed
uv run python syosetu_scraper.py n3170ed --proxy http://127.0.0.1:7897
uv run python syosetu_scraper.py n3170ed -c 2 --delay 1
```

See `--help` for all options.

## Test

```bash
uv run pytest
uv run pytest -v           # verbose
uv run pytest tests/test_utils.py  # single file
```

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
- **CLI**: uses `argparse`, all config via flags (`-o`, `-c`, `--delay`, `--keep-temp`, `--retry`, `--timeout`, `--list`, `--version`)
- **`--delay`**: float seconds slep after each successful chapter fetch

## Release

```bash
gh release create v<version> --title "v<version> — <summary>" --notes "<body>"
```

- Title 格式: `v<version> — <中文概括>`
- Body 分三部分: `## 新功能` `## BUG 修复` `## 新测试`
- 不要对 Markdown 内任何符号加反斜杠转义（包括反引号包围的代码）— shell 中直接写纯文本，不嵌套引号
