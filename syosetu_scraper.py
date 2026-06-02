import requests
from bs4 import BeautifulSoup
from ebooklib import epub
import time
from urllib.parse import urljoin
import concurrent.futures
import zipfile
import os
import shutil

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
            if attempt == 2:
                raise e
            time.sleep(2)
    raise Exception("请求失败：超过最大重试次数") 

def get_novel_metadata(base_url: str):
    """获取小说信息"""
    print(f"正在分析小说信息...")
    current_url: str | None = base_url
    title = "未知书名"
    author = "未知作者"
    volumes = []            
    current_vol_title = None
    current_vol_chapters = []
    
    soup = get_soup(current_url)
    
    title_tag = soup.find('h1', class_='p-novel__title') or soup.find('p', class_='novel_title')
    if title_tag:
        title = title_tag.text.strip()
    elif soup.title and soup.title.string:
        title = str(soup.title.string).split('-')[0].strip()
        
    author_tag = soup.find('div', class_='p-novel__author') or soup.find('div', class_='novel_writername')
    if author_tag:
        author = author_tag.text.strip().replace('作者：', '').replace('作者:', '')

    content_div = soup.find('div', class_='js-novel-text') or \
                  soup.find('div', class_='p-novel__text') or \
                  soup.find('div', id='novel_honbun')
                  
    if content_div and not soup.find('div', class_='p-eplist'): 
        print("💡 检测到该小说为【短篇小说】，无分级目录。")
        volumes.append((None, [{'title': title, 'url': base_url, 'index': 0}]))
        return title, author, volumes

    page_count = 1
    global_chap_index = 0
    
    while current_url:
        print(f"正在解析连载目录页 (第 {page_count} 页)...")
        if page_count > 1:
            soup = get_soup(current_url)
            
        elements = soup.find_all(['div', 'dl'], class_=['p-eplist__chapter-title', 'chapter_title', 'p-eplist__sublist', 'novel_sublist2'])
        
        for el in elements:
            raw_classes = el.get('class')
            classes = raw_classes if isinstance(raw_classes, list) else ([raw_classes] if raw_classes else [])
            
            if 'p-eplist__chapter-title' in classes or 'chapter_title' in classes:
                vol_name = el.text.strip()
                if vol_name != current_vol_title:
                    if current_vol_chapters or current_vol_title is not None:
                        volumes.append((current_vol_title, current_vol_chapters))
                    current_vol_title = vol_name
                    current_vol_chapters = []
            else:
                a_tag = el.find('a')
                if a_tag:
                    chap_title = a_tag.text.strip()
                    href_val = a_tag.get('href')
                    if href_val:
                        chap_url = urljoin(current_url, str(href_val))
                        current_vol_chapters.append({'title': chap_title, 'url': chap_url, 'index': global_chap_index})
                        global_chap_index += 1
                    
        next_tag = soup.find('a', class_='c-pager__item--next')
        if not next_tag:
            for a_tag in soup.find_all('a'):
                href_val = a_tag.get('href')
                if href_val and ('次へ' in a_tag.text or '>>' in a_tag.text):
                    next_tag = a_tag
                    break
                    
        if next_tag:
            next_href = next_tag.get('href')
            if next_href:
                next_url = urljoin(current_url, str(next_href))
                if next_url == current_url: break
                current_url = next_url
                page_count += 1
                time.sleep(0.5) 
                continue 
                
        break
            
    if current_vol_chapters or current_vol_title is not None:
        volumes.append((current_vol_title, current_vol_chapters))
        
    total_chapters = sum(len(chaps) for _, chaps in volumes)
    print(f"\n成功获取: 《{title}》 by {author}")
    print(f"共扫描到 {total_chapters} 章，分为 {len(volumes)} 个卷/部。\n")
    return title, author, volumes

def clean_and_compress_html(raw_html: str) -> str:
    """深度清洗正文 HTML，压缩连续空行，打上样式标记"""
    soup = BeautifulSoup(raw_html, 'html.parser')
    p_tags = soup.find_all('p')
    consecutive_empty = 0
    
    for p in p_tags:
        p_text = p.get_text().strip()
        is_empty = (not p_text) or p_text == ""
        
        if is_empty:
            consecutive_empty += 1
            if consecutive_empty > 1:
                p.decompose()
            else:
                p.attrs['class'] = 'epub-blank-line'
                p.clear()
        else:
            consecutive_empty = 0
            p.attrs['class'] = 'epub-text-line'
            
    return str(soup)

def fetch_single_chapter(chap_info: dict) -> dict:
    import random
    time.sleep(random.uniform(0.1, 0.4))
    try:
        soup = get_soup(chap_info['url'])
        content_div = soup.find('div', class_='js-novel-text') or \
                      soup.find('div', class_='p-novel__text') or \
                      soup.find('div', id='novel_honbun')
        if not content_div:
            raise Exception("未找到正文")
            
        cleaned_html = clean_and_compress_html(str(content_div))
        print(f"✅ 抓取并清洗成功: {chap_info['title']}")
        return {'index': chap_info['index'], 'title': chap_info['title'], 'html': cleaned_html, 'error': None}
    except Exception as e:
        print(f"❌ 抓取失败: {chap_info['title']} - {e}")
        return {'index': chap_info['index'], 'title': chap_info['title'], 'html': "", 'error': str(e)}

def force_remove_ol_from_epub(epub_path: str):
    """【物理拦截核心】：强行解压生成的 epub，暴力用 div 替换里面的所有 ol/li 标签，消除数字编号"""
    print("🛠️ 正在进行物理层面目录重构（强力消除数字编号）...")
    temp_dir = epub_path + "_temp_extract"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    # 1. 解压文件
    with zipfile.ZipFile(epub_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
        
    # 2. 搜寻并彻底清洗导航和目录页面 (通常是 nav.xhtml)
    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(('.xhtml', '.html')):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 如果文件中包含导航目录标记，或者包含 ol 列表，直接对其降维打击
                if 'epub:type="toc"' in content or '<ol' in content or '<li' in content:
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # 强行把所有 <ol> 换成 <div>，把所有 <li> 换成 <div> 并赋予无边距样式
                    for ol in soup.find_all('ol'):
                        ol.name = 'div'
                        ol.attrs['style'] = 'list-style:none !important; list-style-type:none !important; padding:0; margin:0;'
                    for ul in soup.find_all('ul'):
                        ul.name = 'div'
                        ul.attrs['style'] = 'list-style:none !important; list-style-type:none !important; padding:0; margin:0;'
                    for li in soup.find_all('li'):
                        li.name = 'div'
                        li.attrs['style'] = 'list-style:none !important; list-style-type:none !important; padding:0; margin:0; display:block;'
                    
                    # 往 head 区域注入最强硬的“灭杀数字编号”全局样式
                    if soup.head:
                        style_tag = soup.new_tag('style')
                        style_tag.string = """
                            nav, ol, ul, li, div { 
                                list-style: none !important; 
                                list-style-type: none !important; 
                            }
                            li::before, ol::before { content: none !important; }
                        """
                        soup.head.append(style_tag)
                        
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(str(soup))
                        
    # 3. 重新打包回 EPUB 格式
    os.remove(epub_path)
    with zipfile.ZipFile(epub_path, 'w', zipfile.ZIP_DEFLATED) as zip_out:
        # EPUB 标准规范：mimetype 文件必须作为第一个文件且不能压缩
        mimetype_path = os.path.join(temp_dir, 'mimetype')
        if os.path.exists(mimetype_path):
            zip_out.write(mimetype_path, 'mimetype', compress_type=zipfile.ZIP_STORED)
            
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, temp_dir)
                if rel_path == 'mimetype':
                    continue
                zip_out.write(full_path, rel_path)
                
    # 4. 清理临时解压目录
    shutil.rmtree(temp_dir)
    print("🎯 物理重构完毕，数字编号已彻底根除。")

def create_epub(ncode_url: str, identifier: str):
    start_time = time.time()
    title, author, volumes = get_novel_metadata(ncode_url)
    
    total_chapters = sum(len(chaps) for _, chaps in volumes)
    if total_chapters == 0:
        print("未获取到任何章节，程序退出。")
        return

    all_chapters_to_fetch = []
    for _, chaps in volumes:
        all_chapters_to_fetch.extend(chaps)

    print(f"\n🚀 开始多线程极速抓取正文 (共 {total_chapters} 章)...")
    fetched_results = {}
    MAX_WORKERS = 4 
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_single_chapter, chap): chap for chap in all_chapters_to_fetch}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            fetched_results[res['index']] = res

    print("\n📦 正在按正确顺序组装 EPUB...")
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language('ja') 
    book.add_author(author)
    
    epub_chapters = []     
    toc_structure = []     
    
    for vol_title, chaps in volumes:
        vol_epub_chapters = []
        for chap in chaps:
            idx = chap['index']
            result_data = fetched_results.get(idx)
            
            if not result_data or result_data['error']:
                content_html = f"<p>该章节抓取失败: {result_data['error'] if result_data else '未知错误'}</p>"
            else:
                content_html = result_data['html']
                
            file_name = f"chapter_{idx:04d}.xhtml"
            c = epub.EpubHtml(title=chap['title'], file_name=file_name, lang='ja')
            
            c.content = f"""
            <html>
            <head>
                <title>{chap['title']}</title>
                <style>
                    body {{ font-family: "MS Mincho", "Hiragino Mincho Pro", serif; line-height: 1.7; padding: 3%; }}
                    p.epub-text-line, p {{ 
                        margin: 0 0 0.3em 0 !important; 
                        padding: 0 !important; 
                        line-height: 1.7 !important;
                    }}
                    p.epub-blank-line {{
                        margin: 0 !important;
                        padding: 0 !important;
                        height: 1.2em !important;
                        line-height: 1.2em !important;
                    }}
                    h2 {{ text-align: center; margin-bottom: 1.5em; border-bottom: 1px solid #ccc; padding-bottom: 10px; }}
                </style>
            </head>
            <body>
                <h2>{chap['title']}</h2>
                {content_html}
            </body>
            </html>
            """
            
            book.add_item(c)
            epub_chapters.append(c)
            vol_epub_chapters.append(c)
            
        if vol_title:
            toc_structure.append( (epub.Section(vol_title), vol_epub_chapters) )
        else:
            toc_structure.extend(vol_epub_chapters)
            
    book.toc = toc_structure
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + epub_chapters
    
    safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c in [' ', '-', '_']]).strip()
    output_filename = f"{safe_title if safe_title else identifier}.epub"
    
    print(f"\n正文组装完成，正在进行初步打包...")
    epub.write_epub(output_filename, book, {})
    
    # 【降维打击触发】：不跟旧库在内存里纠缠，直接去硬盘里修改已经生成的 epub 文件！
    try:
        force_remove_ol_from_epub(output_filename)
    except Exception as patch_err:
        print(f"⚠️ 后处理拦截时出现小意外（但不影响基础文件生成）: {patch_err}")
    
    end_time = time.time()
    print(f"✨ 生成成功: {output_filename}")
    print(f"⏱️ 总耗时: {end_time - start_time:.2f} 秒")

if __name__ == '__main__':
    print("=========================================")
    print("  Syosetu 电子书 (EPUB) 下载器 - 拦截版  ")
    print("=========================================")
    
    user_input = input("请输入小说的 N-code ID (如 n3170ed) 或 完整网址: ").strip()
    
    if not user_input:
        print("输入为空，程序已退出。")
    else:
        if user_input.startswith("http"):
            parts = [p for p in user_input.split('/') if p]
            identifier = parts[-1] if parts else "unknown"
        else:
            identifier = user_input
            
        identifier = identifier.split('?')[0].lower()
        target_url = f"https://ncode.syosetu.com/{identifier}/"
        print(f"🔗 解析目标地址为: {target_url}\n")
        
        create_epub(target_url, identifier)