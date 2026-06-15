import asyncio
import aiohttp
import json
import os
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from typing import Optional


async def get_soup(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, proxy: Optional[str] = None, max_attempts: int = 3) -> BeautifulSoup:
    for attempt in range(1, max_attempts + 1):
        try:
            async with semaphore:
                async with session.get(url, proxy=proxy) as response:
                    response.raise_for_status()
                    text = await response.text(encoding='utf-8', errors='replace')
            return BeautifulSoup(text, 'html.parser')
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt == max_attempts:
                raise
            await asyncio.sleep(2 * attempt)
    raise Exception("请求失败")


async def get_novel_metadata(base_url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, proxy: Optional[str] = None, max_attempts: int = 3):
    print("正在分析小说信息...")
    current_url: str | None = base_url
    title, author, volumes = "未知书名", "未知作者", []
    current_vol_title, current_vol_chapters = None, []

    soup = await get_soup(current_url, session, semaphore, proxy, max_attempts)
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
        soup = await get_soup(current_url, session, semaphore, proxy, max_attempts)
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


def _dump_chapter(file_path: str, data: dict):
    try:
        tmp_path = file_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, file_path)
    except Exception:
        pass


async def fetch_single_chapter(chap_info: dict, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, proxy: Optional[str] = None, data_dir: Optional[str] = None, max_attempts: int = 3) -> dict:
    index = chap_info['index']
    title = chap_info.get('title', '')
    file_path = os.path.join(data_dir, f"chapter_{index:04d}.json") if data_dir else None
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    last_err = "未知错误"
    for attempt in range(1, max_attempts + 1):
        try:
            soup = await get_soup(chap_info['url'], session, semaphore, proxy, max_attempts)
            content = soup.find('div', class_='js-novel-text') or soup.find('div', class_='p-novel__text') or soup.find('div', id='novel_honbun')
            if not content:
                raise Exception("未找到正文内容")
            result = {
                'index': index,
                'title': title,
                'html': _clean_html(str(content)),
                'error': None
            }
            if file_path:
                _dump_chapter(file_path, result)
            return result
        except Exception as e:
            last_err = str(e)
            if attempt < max_attempts:
                await asyncio.sleep(2 * attempt)

    result = {
        'index': index,
        'title': title,
        'html': "",
        'error': last_err
    }
    if file_path:
        _dump_chapter(file_path, result)
    return result


def _clean_html(raw_html: str) -> str:
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


def sanitize_filename(title: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', title).strip() or 'novel'
