# syosetu-scraper

抓取「小説家になろう」小说并生成 EPUB 电子书。

## 快速开始

```bash
uv sync
uv run python syosetu_scraper.py n3170ed
```

## 全部选项

| 参数 | 说明 |
|------|------|
| `ncode` | N-code ID 或完整 URL（必填） |
| `--proxy` | 代理地址，如 `http://127.0.0.1:7897` |
| `-o,--output-dir` | 输出目录（默认当前目录） |
| `-c,--concurrency` | 并发数（默认 4） |
| `--delay` | 每章抓取后的间隔秒数 |
| `--keep-temp` | 保留临时文件 |
| `--retry,--max-retries` | 重试次数（默认 3） |
| `--timeout` | 请求超时秒数（默认 15） |
| `--list` | 仅列出章节，不下载 |
| `--version` | 版本号 |
| `--help` | 帮助信息 |

## 功能

- 异步并发下载，断点续传，自动重试
- 排版优化的 EPUB（首行缩进、段落间距、标题居中）
- 支持代理（`--proxy` 或环境变量 `HTTPS_PROXY` 等）
- 可调节并发数和请求间隔，降低服务器压力

## 测试

```bash
uv run pytest
```

## 免责声明

本工具仅供个人学习研究使用。请遵守目标网站的 `robots.txt` 及服务条款，不要高频请求服务器。生成的 EPUB 仅限个人收藏，请勿用于商业用途或公开传播。
