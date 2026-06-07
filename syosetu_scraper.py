import requests
from bs4 import BeautifulSoup
from ebooklib import epub
import time
from urllib.parse import urljoin
import concurrent.futures
import sys
from tqdm import tqdm

# ---------------------------------------------------------
# 工具函数
# ---------------------------------------------------------
def get_soup(url: str) -> BeautifulSoup:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    cookies = {'over18': 'yes'} 
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, cookies=cookies, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return BeautifulSoup(response.text, 'html.parser')
        except requests.exceptions.RequestException as e:
            if attempt == 2: raise e
            time.sleep(2)
    raise Exception("请求失败") 

def get_novel_metadata(base_url: str):
    print(f"正在分析小说信息...")
    current_url: str | None = base_url
    title, author, volumes = "未知书名", "未知作者", []
    current_vol_title, current_vol_chapters = None, []
    
    soup = get_soup(current_url)
    title_tag = soup.find('h1', class_='p-novel__title') or soup.find('p', class_='novel_title')
    title = title_tag.text.strip() if title_tag else str(soup.title.string).split('-')[0].strip()
    author_tag = soup.find('div', class_='p-novel__author') or soup.find('div', class_='novel_writername')
    author = author_tag.text.strip().replace('作者：', '').replace('作者:', '') if author_tag else "未知"

    if not soup.find('div', class_='p-eplist'): 
        volumes.append((None, [{'title': title, 'url': base_url, 'index': 0}]))
        return title, author, volumes

    global_chap_index = 0
    while current_url:
        soup = get_soup(current_url)
        elements = soup.find_all(['div', 'dl'], class_=['p-eplist__chapter-title', 'chapter_title', 'p-eplist__sublist', 'novel_sublist2'])
        for el in elements:
            if 'p-eplist__chapter-title' in el.get('class', []) or 'chapter_title' in el.get('class', []):
                if current_vol_chapters or current_vol_title is not None: volumes.append((current_vol_title, current_vol_chapters))
                current_vol_title, current_vol_chapters = el.text.strip(), []
            else:
                a_tag = el.find('a')
                if a_tag:
                    current_vol_chapters.append({'title': a_tag.text.strip(), 'url': urljoin(current_url, str(a_tag.get('href'))), 'index': global_chap_index})
                    global_chap_index += 1
        
        next_tag = soup.find('a', class_='c-pager__item--next') or next((a for a in soup.find_all('a') if '次へ' in a.text or '>>' in a.text), None)
        if next_tag and next_tag.get('href'):
            next_url = urljoin(current_url, str(next_tag.get('href')))
            if next_url == current_url: break
            current_url = next_url
        else: break
            
    if current_vol_chapters or current_vol_title is not None: volumes.append((current_vol_title, current_vol_chapters))
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

def fetch_single_chapter(chap_info: dict) -> dict:
    try:
        soup = get_soup(chap_info['url'])
        content = soup.find('div', class_='js-novel-text') or soup.find('div', class_='p-novel__text') or soup.find('div', id='novel_honbun')
        if not content: raise Exception("未找到正文内容")
        return {'index': chap_info['index'], 'title': chap_info['title'], 'html': clean_and_compress_html(str(content)), 'error': None}
    except Exception as e:
        return {'index': chap_info['index'], 'title': chap_info['title'], 'html': "", 'error': str(e)}

def create_epub(ncode_url: str, identifier: str):
    start_time = time.time()
    title, author, volumes = get_novel_metadata(ncode_url)
    all_chapters = [ch for _, chaps in volumes for ch in chaps]
    
    print(f"\n🚀 开始抓取，共 {len(all_chapters)} 章")
    fetched_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_single_chapter, ch): ch for ch in all_chapters}
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(all_chapters), desc="正在抓取正文"):
            res = future.result()
            fetched_results[res['index']] = res

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
            # 使用 Link 对象代替 Section，并将其 href 指向卷内第一章
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

if __name__ == '__main__':
    if len(sys.argv) > 1:
        code = sys.argv[1]
    else:
        code = input("请输入 N-code ID: ").strip()
    
    ncode_id = code.split('/')[-1]
    create_epub(f"https://ncode.syosetu.com/{ncode_id}/", ncode_id)
