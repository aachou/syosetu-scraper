import os
import sys
import argparse
import asyncio

if sys.stdout.encoding and sys.stdout.encoding.upper() != 'UTF-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from core import __version__
from core.book import create_epub, list_chapters


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="syosetu-scraper",
        description="抓取 syosetu 网站上的小说并生成 EPUB 电子书。"
    )
    parser.add_argument('ncode', help="N-code ID 或完整 syosetu URL")
    parser.add_argument('--proxy', help="代理地址，如 http://127.0.0.1:7897")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('-o', '--output-dir', default='.', help="EPUB 输出目录（默认当前目录）")
    parser.add_argument('-c', '--concurrency', type=int, default=4, help="并发请求数（默认 4）")
    parser.add_argument('--delay', type=float, default=0, help="每章抓取后的间隔秒数")
    parser.add_argument('--keep-temp', action='store_true', help="保留临时文件，不自动清理")
    parser.add_argument('--retry', '--max-retries', dest='max_retries', type=int, default=3, help="最大重试次数（默认 3）")
    parser.add_argument('--timeout', type=int, default=15, help="请求超时秒数（默认 15）")
    parser.add_argument('--list', action='store_true', help="仅列出章节，不下载")
    return parser.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])
    proxy = args.proxy or os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY') or os.environ.get('https_proxy') or os.environ.get('http_proxy')
    ncode_id = args.ncode.split('/')[-1]
    if proxy:
        print(f"使用代理: {proxy}")

    try:
        if args.list:
            asyncio.run(list_chapters(
                f"https://ncode.syosetu.com/{ncode_id}/",
                ncode_id,
                proxy=proxy,
                concurrency=args.concurrency,
                max_attempts=args.max_retries,
            ))
        else:
            success = asyncio.run(create_epub(
                f"https://ncode.syosetu.com/{ncode_id}/",
                ncode_id,
                proxy=proxy,
                concurrency=args.concurrency,
                delay=args.delay,
                output_dir=args.output_dir,
                keep_temp=args.keep_temp,
                max_attempts=args.max_retries,
                timeout_sec=args.timeout,
            ))
            if not success:
                sys.exit(1)
    except KeyboardInterrupt:
        print("\n用户中断，退出。")
        sys.exit(130)
    except Exception as e:
        print(f"\n错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
