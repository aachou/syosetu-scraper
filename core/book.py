import asyncio
import aiohttp
import json
import os
import shutil
import time
from ebooklib import epub
from tqdm import tqdm
from typing import Optional, Any

from . import HEADERS, COOKIES
from .fetch import get_novel_metadata, fetch_single_chapter, sanitize_filename

STYLE_CONTENT = """
@namespace epub "http://www.idpf.org/2007/ops";
.paragraph {
    margin: 0 !important;
    margin-bottom: 1em !important;
    line-height: 1.7 !important;
    text-indent: 2em !important;
    padding-left: 0 !important;
    text-align: justify !important;
}
h2 {
    text-align: center !important;
    font-size: 1.2em !important;
    margin-bottom: 1em !important;
    padding-bottom: 0 !important;
    border-bottom: none !important;
}
"""


async def list_chapters(ncode_url: str, identifier: str, proxy: Optional[str] = None, concurrency: int = 4, max_attempts: int = 3):
    semaphore = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(ssl=False) if proxy else None

    async with aiohttp.ClientSession(headers=HEADERS, cookies=COOKIES, timeout=aiohttp.ClientTimeout(total=15, sock_connect=5, sock_read=15), connector=connector) as session:
        title, author, volumes = await get_novel_metadata(ncode_url, session, semaphore, proxy, max_attempts)

    print(f"📖 标题: {title}")
    print(f"✍️ 作者: {author}")
    total = sum(len(chaps) for _, chaps in volumes)
    print(f"📑 章节: {total}")
    print()
    for vol_title, chaps in volumes:
        if vol_title:
            print(f"  [{vol_title}]")
        for ch in chaps:
            print(f"    {ch['index']:4d}. {ch['title']}")


async def create_epub(ncode_url: str, identifier: str, proxy: Optional[str] = None, concurrency: int = 4, delay: float = 0, output_dir: str = '.', keep_temp: bool = False, max_attempts: int = 3, timeout_sec: int = 15) -> bool:
    start_time = time.time()
    timeout = aiohttp.ClientTimeout(total=timeout_sec, sock_connect=5, sock_read=timeout_sec)
    semaphore = asyncio.Semaphore(concurrency)
    data_dir: str | None = None

    connector = aiohttp.TCPConnector(ssl=False) if proxy else None
    if proxy:
        print("⚠️ 警告：已禁用 SSL 证书验证以兼容代理。")

    try:
        async with aiohttp.ClientSession(headers=HEADERS, cookies=COOKIES, timeout=timeout, connector=connector) as session:
            title, author, volumes = await get_novel_metadata(ncode_url, session, semaphore, proxy, max_attempts)
            all_chapters = [ch for _, chaps in volumes for ch in chaps]

            print(f"📖 标题: {title}")
            print(f"✍️ 作者: {author}")
            print(f"📑 章节: {len(all_chapters)} 章")
            print(f"\n⬇️  开始抓取...")

            data_dir = os.path.join('data', identifier)
            os.makedirs(data_dir, exist_ok=True)

            fetched_results: dict[int, Any] = {}
            existing_count = 0
            for ch in all_chapters:
                fp = os.path.join(data_dir, f"chapter_{ch['index']:04d}.json")
                if os.path.exists(fp):
                    try:
                        with open(fp, 'r', encoding='utf-8') as f:
                            fetched_results[ch['index']] = json.load(f)
                            existing_count += 1
                    except Exception:
                        pass

            tasks = [asyncio.create_task(fetch_single_chapter(ch, session, semaphore, proxy, data_dir, max_attempts)) for ch in all_chapters if ch['index'] not in fetched_results]

            failed_count = 0
            with tqdm(total=len(all_chapters), desc="⬇️  正在抓取正文") as pbar:
                if existing_count:
                    pbar.set_postfix_str(f"已缓存 {existing_count}")
                    pbar.update(existing_count)
                for future in asyncio.as_completed(tasks):
                    res = await future
                    fetched_results[res['index']] = res
                    if res['error']:
                        failed_count += 1
                    pbar.set_postfix_str(f"失败 {failed_count}" if failed_count else "")
                    pbar.update()
                    if delay:
                        await asyncio.sleep(delay)

        if failed_count:
            print(f"❌ {failed_count} 章抓取失败")
        print("📦 正在组装 EPUB...")
        book = epub.EpubBook()
        book.set_identifier(identifier)
        book.set_title(title)
        book.set_language('ja')
        book.add_author(author)

        nav_css = epub.EpubItem(uid="style_main", file_name="style/stylesheet.css", media_type="text/css", content=STYLE_CONTENT)
        book.add_item(nav_css)

        all_epub_chapters = []
        toc_structure = []

        for vol_title, chaps in volumes:
            vol_epub_chapters = []
            for chap in chaps:
                res = fetched_results.get(chap['index'])
                if not res:
                    continue
                content_html = res['html'] if not res['error'] else f"<p>{res['error']}</p>"

                c = epub.EpubHtml(title=chap['title'], file_name=f"chapter_{chap['index']:04d}.xhtml", lang='ja')
                c.add_link(href='style/stylesheet.css', rel='stylesheet', type='text/css')
                c.content = f"<h2>{chap['title']}</h2>{content_html}"

                book.add_item(c)
                vol_epub_chapters.append(c)
                all_epub_chapters.append(c)

            if vol_title:
                vol_link = epub.Link(vol_epub_chapters[0].file_name, vol_title, f"uid_{chaps[0]['index']}")
                toc_structure.append((vol_link, tuple(vol_epub_chapters)))
            else:
                toc_structure.extend(vol_epub_chapters)

        book.toc = toc_structure
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ['nav'] + all_epub_chapters

        os.makedirs(output_dir, exist_ok=True)
        output_filename = os.path.join(output_dir, f"{sanitize_filename(title)}.epub")
        epub.write_epub(output_filename, book, {})
        elapsed = time.time() - start_time
        print(f"\n✓ 生成成功: {output_filename}")
        print(f"  耗时: {elapsed:.1f} 秒 | 章节: {len(all_epub_chapters)}/{len(all_chapters)}")

        return True
    finally:
        if not keep_temp and data_dir and os.path.exists(data_dir):
            shutil.rmtree(data_dir)
            print(f"  🗑️ 已清理临时文件")
