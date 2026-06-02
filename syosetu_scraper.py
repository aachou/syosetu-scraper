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
    """深度清洗正文 HTML：无视原作者的所有空行，只提取有字的纯净段落（类型安全版）"""
    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # 1. 建立一个全新的基础容器
    new_soup = BeautifulSoup("<div></div>", 'html.parser')
    new_container = new_soup.find('div')
    assert new_container is not None, "基础容器创建失败"
    
    p_tags = soup.find_all('p')
    
    for p in p_tags:
        # 提取文字，将内嵌的 <br/> 转换为换行符 \n
        raw_text_block = p.get_text(separator="\n").strip()
        lines = raw_text_block.split('\n')
        
        for line in lines:
            clean_line = line.strip()
            
            # 【铁律】：只有这一行真的有文字，才把它做成 <p> 标签放进新容器中
            if clean_line:
                new_p = new_soup.new_tag('p')
                new_p.string = clean_line
                new_p.attrs['class'] = 'epub-text-line'
                new_container.append(new_p)
                
            # 如果是原作者敲的空行（clean_line 为空），直接在这里被无情抛弃，绝不污染新容器

    # 此时容器内全是紧密排列、无空行的纯文字段落
    return str(new_container.decode_contents())

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
    """【物理拦截核心·紧凑精致版】：解压 epub，转换为无数字编号的 div 架构，缩紧间距并精准微调样式"""
    print("🛠️ 正在进行物理层面目录重构（紧凑精致 + 卷可点击 + 去除加粗 + 消除数字）...")
    temp_dir = epub_path + "_temp_extract"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    # 1. 解压文件
    with zipfile.ZipFile(epub_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
        
    # 2. 搜寻并彻底清洗导航和目录页面
    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(('.xhtml', '.html')):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if 'epub:type="toc"' in content or '<ol' in content or '<li' in content:
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # 遍历所有的列表项，洗脑转换为带有独立类名的 div
                    for li in soup.find_all('li'):
                        li.name = 'div'
                        # 判断它是否包含子列表（说明它是大卷/大分类的主题）
                        if li.find('ol') or li.find('ul'):
                            li.attrs['class'] = 'toc-volume-block'
                        else:
                            li.attrs['class'] = 'toc-chapter-item'
                    
                    # 把所有的 ol/ul 容器转换成普通的普通块
                    for ol in soup.find_all(['ol', 'ul']):
                        ol.name = 'div'
                        ol.attrs['class'] = 'toc-level-wrapper'
                    
                    # 强力注入全新的、不依赖列表标签的【紧凑型】层级样式表
                    if soup.head:
                        style_tag = soup.new_tag('style')
                        style_tag.string = """
                            /* 彻底根除所有潜在的数字和符号 */
                            div, nav, a { 
                                list-style: none !important; 
                                list-style-type: none !important; 
                                text-decoration: none !important;
                            }
                            
                            /* 目录大框架 */
                            .toc-level-wrapper { 
                                padding: 0; 
                                margin: 0; 
                            }
                            
                            /* 分卷/大分类：收紧上下间距，保持普通粗细 */
                            .toc-volume-block > a, .toc-volume-block > span {
                                font-weight: normal !important;
                                font-size: 1.05em;
                                color: #111;
                                display: block;
                                margin-top: 0.8em;
                                margin-bottom: 0.2em;
                            }
                            
                            /* 普通章节：缩进微调为 1.0em，大幅收紧垂直间距和行高 */
                            .toc-chapter-item {
                                padding-left: 1.0em !important;
                                margin: 0.25em 0 !important;
                                display: block;
                                line-height: 1.3 !important;
                            }
                            
                            .toc-chapter-item a {
                                color: #444;
                                display: block;
                                padding: 2px 0;
                            }
                        """
                        soup.head.append(style_tag)
                        
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(str(soup))
                        
    # 3. 重新打包回 EPUB 格式
    os.remove(epub_path)
    with zipfile.ZipFile(epub_path, 'w', zipfile.ZIP_DEFLATED) as zip_out:
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
    print("🎯 紧凑精致版目录物理重构完毕。")

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
                    
                    /* 终极强制排版：所有段落尾部强制腾出 1.7em（刚好一行字）的空间 */
                    p.epub-text-line, p {{ 
                        margin-top: 0 !important;
                        margin-left: 0 !important;
                        margin-right: 0 !important;
                        margin-bottom: 1.7em !important; 
                        padding: 0 !important; 
                        line-height: 1.7 !important;
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
            # 卷目录可点击跳转到第一话
            first_chap_file = vol_epub_chapters[0].file_name if vol_epub_chapters else ""
            vol_section = epub.Section(vol_title, href=first_chap_file)
            toc_structure.append( (vol_section, vol_epub_chapters) )
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
    
    # 触发后处理：物理拦截并清洗总目录
    try:
        force_remove_ol_from_epub(output_filename)
    except Exception as patch_err:
        print(f"⚠️ 后处理拦截时出现小意外（但不影响基础文件生成）: {patch_err}")
    
    end_time = time.time()
    print(f"✨ 生成成功: {output_filename}")
    print(f"⏱️ 总耗时: {end_time - start_time:.2f} 秒")

if __name__ == '__main__':
    print("=========================================")
    print("  Syosetu 电子书 (EPUB) 下载器 - 多线程  ")
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
