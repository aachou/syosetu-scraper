import asyncio
import aiohttp
from bs4 import BeautifulSoup
from ebooklib import epub
import time
import os
import json
import shutil
from urllib.parse import urljoin
import sys
from tqdm import tqdm
from typing import Optional

# ---------------------------------------------------------
# 工具函数
# ---------------------------------------------------------
async def get_soup(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, proxy: Optional[str] = None) -> BeautifulSoup:
    for attempt in range(3):
        try:
            async with semaphore:
                async with session.get(url, proxy=proxy) as response:
                    response.raise_for_status()
                    text = await response.text(encoding='utf-8', errors='replace')
            return BeautifulSoup(text, 'html.parser')
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt == 2:
                raise
            await asyncio.sleep(2)
    raise Exception("请求失败") 

async def get_novel_metadata(base_url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, proxy: Optional[str] = None):
    print(f"正在分析小说信息...")
    current_url: str | None = base_url
    title, author, volumes = "未知书名", "未知作者", []
    current_vol_title, current_vol_chapters = None, []

    soup = await get_soup(current_url, session, semaphore, proxy)
    title_tag = soup.find('h1', class_='p-novel__title') or soup.find('p', class_='novel_title')
    if title_tag:
        title = title_tag.text.strip()
    else:
        page_title = soup.title.string if soup.title and soup.title.string else ""
        title = page_title.split('-', 1)[0].strip() or "未知书名"
    author_tag = soup.find('div', class_='p-novel__author') or soup.find('div', class_='novel_writername')
    author = author_tag.text.strip().replace('作者：', '').replace('作者:', '') if author_tag else "未知"

    if not soup.find('div', class_='p-eplist'):
        volumes.append((None, [{'title': title, 'url': base_url, 'index': 0}]))
        return title, author, volumes

    global_chap_index = 0
    while current_url:
        soup = await get_soup(current_url, session, semaphore, proxy)
        elements = soup.find_all(['div', 'dl'], class_=['p-eplist__chapter-title', 'chapter_title', 'p-eplist__sublist', 'novel_sublist2'])
        for el in elements:
            classes = el.get('class') or []
            if 'p-eplist__chapter-title' in classes or 'chapter_title' in classes:
                if current_vol_chapters or current_vol_title is not None:
                    volumes.append((current_vol_title, current_vol_chapters))
                current_vol_title, current_vol_chapters = el.text.strip(), []
            else:
                a_tag = el.find('a')
                if a_tag:
                    current_vol_chapters.append({
                        'title': a_tag.text.strip(),
                        'url': urljoin(current_url, str(a_tag.get('href'))),
                        'index': global_chap_index
                    })
                    global_chap_index += 1

        next_tag = soup.find('a', class_='c-pager__item--next') or next((a for a in soup.find_all('a') if '次へ' in a.text or '>>' in a.text), None)
        if next_tag and next_tag.get('href'):
            next_url = urljoin(current_url, str(next_tag.get('href')))
            if next_url == current_url:
                break
            current_url = next_url
        else:
            break

    if current_vol_chapters or current_vol_title is not None:
        volumes.append((current_vol_title, current_vol_chapters))
    return title, author, volumes


def clean_and_compress_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, 'html.parser')
    new_soup = BeautifulSoup("<div></div>", 'html.parser')
    new_container = new_soup.find('div')
    assert new_container is not None
    for p in soup.find_all('p'):
        for line in p.get_text(separator="\n").strip().split('\n'):
            if line.strip():
                new_p = new_soup.new_tag('p')
                new_p.string = line.strip()
                new_p.attrs['class'] = 'paragraph'
                new_container.append(new_p)
    return str(new_container.decode_contents())

async def fetch_single_chapter(chap_info: dict, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, proxy: Optional[str] = None, data_dir: Optional[str] = None, max_attempts: int = 3) -> dict:
    index = chap_info['index']
    title = chap_info.get('title', '')
    file_path = None
    if data_dir:
        file_path = os.path.join(data_dir, f"chapter_{index:04d}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass

    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            soup = await get_soup(chap_info['url'], session, semaphore, proxy)
            content = soup.find('div', class_='js-novel-text') or soup.find('div', class_='p-novel__text') or soup.find('div', id='novel_honbun')
            if not content:
                raise Exception("未找到正文内容")
            result = {
                'index': index,
                'title': title,
                'html': clean_and_compress_html(str(content)),
                'error': None
            }
            if file_path:
                tmp_path = file_path + '.tmp'
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False)
                os.replace(tmp_path, file_path)
            return result
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                await asyncio.sleep(2 * attempt)
            else:
                result = {
                    'index': index,
                    'title': title,
                    'html': "",
                    'error': str(e)
                }
                if file_path:
                    try:
                        tmp_path = file_path + '.tmp'
                        with open(tmp_path, 'w', encoding='utf-8') as f:
                            json.dump(result, f, ensure_ascii=False)
                        os.replace(tmp_path, file_path)
                    except Exception:
                        pass
                return result

    # 兜底：确保所有代码路径都有返回值（用于类型检查）
    return {
        'index': index,
        'title': title,
        'html': "",
        'error': str(last_err) if last_err is not None else 'unknown error'
    }

async def create_epub(ncode_url: str, identifier: str, proxy: Optional[str] = None):
    start_time = time.time()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    cookies = {'over18': 'yes'}
    timeout = aiohttp.ClientTimeout(total=15, sock_connect=5, sock_read=15)
    semaphore = asyncio.Semaphore(4)

    connector = aiohttp.TCPConnector(ssl=False) if proxy else aiohttp.TCPConnector()
    if proxy:
        print("警告：已禁用 SSL 证书验证以兼容代理。")

    async with aiohttp.ClientSession(headers=headers, cookies=cookies, timeout=timeout, connector=connector) as session:
        title, author, volumes = await get_novel_metadata(ncode_url, session, semaphore, proxy)
        all_chapters = [ch for _, chaps in volumes for ch in chaps]
        print(f"\n🚀 开始抓取，共 {len(all_chapters)} 章")

        # 临时数据目录，用于断点续传
        data_dir = os.path.join('data', identifier)
        os.makedirs(data_dir, exist_ok=True)

        fetched_results = {}
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

        # 只为尚未持久化的章节创建任务
        tasks = [asyncio.create_task(fetch_single_chapter(ch, session, semaphore, proxy, data_dir)) for ch in all_chapters if ch['index'] not in fetched_results]

        with tqdm(total=len(all_chapters), desc="正在抓取正文") as pbar:
            if existing_count:
                pbar.update(existing_count)
            for future in asyncio.as_completed(tasks):
                res = await future
                fetched_results[res['index']] = res
                pbar.update()

    print("\n📦 正在组装 EPUB...")
    book = epub.EpubBook()
    book.set_identifier(identifier); book.set_title(title); book.set_language('ja'); book.add_author(author)

    style_content = """
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
    nav_css = epub.EpubItem(uid="style_main", file_name="style/stylesheet.css", media_type="text/css", content=style_content)
    book.add_item(nav_css)

    all_epub_chapters = []
    toc_structure = []

    # 核心：使用 epub.Link 实现目录卷名可点击跳转
    for vol_title, chaps in volumes:
        vol_epub_chapters = []
        for chap in chaps:
            res = fetched_results[chap['index']]
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

    output_filename = f"{''.join([c for c in title if c.isalnum() or c in ' -_'])}.epub"
    epub.write_epub(output_filename, book, {})
    print(f"\n✨ 生成成功: {output_filename} (耗时: {time.time() - start_time:.2f} 秒)")

    # 清理临时数据目录
    try:
        if 'data_dir' in locals() and os.path.exists(data_dir):
            shutil.rmtree(data_dir)
            print(f"已清理临时目录: {data_dir}")
    except Exception:
        pass

async def main():
    if len(sys.argv) > 1:
        code = sys.argv[1]
    else:
        code = input("请输入 N-code ID: ").strip()

    proxy_arg = sys.argv[2] if len(sys.argv) > 2 else None
    proxy = proxy_arg or os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY') or os.environ.get('https_proxy') or os.environ.get('http_proxy')

    ncode_id = code.split('/')[-1]
    if proxy:
        print(f"使用代理: {proxy}")
    await create_epub(f"https://ncode.syosetu.com/{ncode_id}/", ncode_id, proxy)

if __name__ == '__main__':
    asyncio.run(main())
