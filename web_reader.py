import streamlit as st
import requests
import random
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from hashlib import md5

st.set_page_config(page_title="汐涵阅读器", layout="wide")
st.markdown("""
<style>
    /* 强力修复标题裁剪问题，移除不必要的限制 */
    .main .block-container h1 {
        font-size: 2.2rem !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
        padding-top: 0.5rem !important;
        padding-bottom: 0.5rem !important;
    }
    /* 页面整体内边距减小，让阅读区更大 */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
    }
    /* 优化中文段落排版：首行缩进，增加行高和段落间距 */
    .article-para {
        font-size: 1.15rem !important;
        line-height: 1.8 !important;
        margin-bottom: 24px !important;
        text-align: justify;
        letter-spacing: 0.5px;
    }
</style>
""", unsafe_allow_html=True)

BAIDU_APPID = st.secrets.get("BAIDU_APPID", "")
BAIDU_APPKEY = st.secrets.get("BAIDU_APPKEY", "")

# ---------- 会话状态初始化 ----------
if "current_url" not in st.session_state:
    st.session_state.current_url = ""
if "next_url" not in st.session_state:
    st.session_state.next_url = ""
if "prev_url" not in st.session_state:
    st.session_state.prev_url = ""
if "translated_paragraphs" not in st.session_state:
    st.session_state.translated_paragraphs = []
if "url_history" not in st.session_state:
    st.session_state.url_history = []

# 使用 Markdown 渲染大标题，稳定性更好
st.markdown("# 📚 汐涵阅读器")
st.markdown("输入英文书籍章节的网址，沉浸式体验中文翻译。")

url_input = st.text_input(
    "",
    placeholder="在这里粘贴书籍章节的网址，例如: https://bookreadfree.com/507607/12466798",
    key="url_input"
)

# ---------- 段落过滤函数 ----------
def is_valid_paragraph(text):
    """过滤掉导航、版权、空内容等非正文段落"""
    if not text or len(text.strip()) < 3:
        return False

    text_lower = text.lower().strip()

    if text_lower in ['next', 'prev', 'previous', 'next »', '« prev', '« previous']:
        return False
    if text_lower.startswith('next') and len(text) < 80:
        return False
    if text_lower.startswith('prev') and len(text) < 80:
        return False

    exclude_keywords = ['©', 'copyright', 'all rights reserved', 'chapter', 'menu', 'home', 'page']
    for kw in exclude_keywords:
        if kw in text_lower:
            if len(text) < 120:
                return False

    if text.replace('.', '').replace(',', '').replace(' ', '').isdigit():
        return False

    return True

# ---------- 抓取网页内容 ----------
def fetch_content_and_links(target_url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(target_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        raw_paragraphs = []
        # 核心优化：保留原网页段落的独立性
        for p in soup.find_all('p'):
            text = p.get_text().strip()
            if text:
                raw_paragraphs.append(text)

        paragraphs = [p for p in raw_paragraphs if is_valid_paragraph(p)]

        if len(paragraphs) < 3:
            paragraphs = [p for p in raw_paragraphs if len(p.strip()) > 10]

        if not paragraphs:
            full_text = soup.get_text().strip()
            paragraphs = [p.strip() for p in full_text.split('\n') if len(p.strip()) > 10]

        # 提取上一页链接
        prev_link = None
        prev_tag = soup.find('a', rel='prev')
        if not prev_tag:
            prev_tag = soup.find('a', class_='p')
        if not prev_tag:
            prev_tag = soup.find('a', string=lambda t: t and ('prev' in t.lower() or 'previous' in t.lower()))
        if prev_tag and prev_tag.get('href'):
            prev_link = urljoin(target_url, prev_tag['href'])

        # 提取下一页链接
        next_link = None
        next_tag = soup.find('a', rel='next')
        if not next_tag:
            next_tag = soup.find('a', class_='n')
        if not next_tag:
            next_tag = soup.find('a', string=lambda t: t and 'next' in t.lower())
        if next_tag and next_tag.get('href'):
            next_link = urljoin(target_url, next_tag['href'])

        return paragraphs, prev_link, next_link
    except Exception as e:
        return f"错误：抓取网页时出错。 {e}", None, None

# ---------- 单段落翻译（重大修复：支持多行翻译拼接）----------
def translate_single_paragraph(text):
    if not text or len(text.strip()) == 0:
        return ""

    endpoint = "https://fanyi-api.baidu.com/api/trans/vip/translate"
    max_retries = 3

    for attempt in range(max_retries):
        try:
            salt = str(random.randint(32768, 65536))
            sign_str = BAIDU_APPID + text + salt + BAIDU_APPKEY
            sign = md5(sign_str.encode('utf-8')).hexdigest()

            params = {
                'q': text,
                'from': 'en',
                'to': 'zh',
                'appid': BAIDU_APPID,
                'salt': salt,
                'sign': sign
            }
            response = requests.post(endpoint, data=params, timeout=15)
            result = response.json()

            if 'trans_result' in result:
                # 【修复核心】遍历所有翻译结果切片，用换行符拼接，确保长段落不丢失、不合并
                translated_chunks = [sub_res['dst'] for sub_res in result['trans_result']]
                return "\n".join(translated_chunks)
            else:
                error_msg = result.get('error_msg', '未知错误')
                if attempt < max_retries - 1:
                    time.sleep(1.0)
                    continue
                else:
                    return f"[翻译失败: {error_msg}]"
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1.0)
            else:
                return f"[翻译失败: {str(e)[:50]}...]"
    return "[翻译失败]"

# ---------- 批量翻译段落 ----------
def translate_paragraphs(english_paragraphs):
    translated = []
    total = len(english_paragraphs)

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, para in enumerate(english_paragraphs):
        status_text.text(f"正在翻译第 {i+1}/{total} 段...")
        translated_para = translate_single_paragraph(para)
        translated.append(translated_para)
        progress_bar.progress((i + 1) / total)

    status_text.text("翻译完成！")
    time.sleep(0.3)
    status_text.empty()
    progress_bar.empty()

    return translated

# ---------- 强制滚动到顶部 ----------
def scroll_to_top():
    st.markdown("""
    <script>
        (function() {
            window.scrollTo(0, 0);
            var mainContent = window.parent.document.querySelector('.main');
            if (mainContent) { mainContent.scrollTo(0, 0); }
        })();
    </script>
    """, unsafe_allow_html=True)

# ---------- 加载并翻译指定网址 ----------
def load_and_translate(url, add_to_history=True):
    with st.spinner("正在抓取网页内容..."):
        result = fetch_content_and_links(url)

    if isinstance(result[0], str) and result[0].startswith("错误："):
        st.session_state.translated_paragraphs = [result[0]]
        st.session_state.prev_url = ""
        st.session_state.next_url = ""
    else:
        paragraphs, prev_link, next_link = result
        st.session_state.prev_url = prev_link if prev_link else ""
        st.session_state.next_url = next_link if next_link else ""

        with st.spinner(f"正在翻译 {len(paragraphs)} 个段落..."):
            st.session_state.translated_paragraphs = translate_paragraphs(paragraphs)

    st.session_state.current_url = url

    if add_to_history:
        if not st.session_state.url_history or st.session_state.url_history[-1] != url:
            st.session_state.url_history.append(url)

# ---------- “开始阅读”按钮 ----------
if st.button("开始阅读", type="primary", use_container_width=True):
    if url_input:
        st.session_state.url_history = []
        load_and_translate(url_input, add_to_history=True)
        scroll_to_top()
        st.rerun()
    else:
        st.warning("请先输入一个网址！")

# ---------- 显示翻译结果 ----------
if st.session_state.translated_paragraphs:
    st.success("翻译完成，请尽情阅读！")

    # 顶部导航栏
    col1, col2 = st.columns(2)
    with col1:
        if st.session_state.prev_url:
            if st.button("◀ 上一页", type="secondary", use_container_width=True):
                load_and_translate(st.session_state.prev_url, add_to_history=True)
                scroll_to_top()
                st.rerun()
        else:
            st.button("◀ 上一页", type="secondary", use_container_width=True, disabled=True)
    with col2:
        if st.session_state.next_url:
            if st.button("下一页 ▶", type="secondary", use_container_width=True):
                load_and_translate(st.session_state.next_url, add_to_history=True)
                scroll_to_top()
                st.rerun()
        else:
            st.button("下一页 ▶", type="secondary", use_container_width=True, disabled=True)

    st.markdown("---")

    # 阅读进度
    para_count = len(st.session_state.translated_paragraphs)
    if st.session_state.url_history:
        st.caption(f"📄 第 {len(st.session_state.url_history)} 页 · 共 {para_count} 段")

    st.markdown("### 📖 中文阅读区")

    # 【重要优化】优雅渲染中文正文，支持段落内部的换行符
    for para in st.session_state.translated_paragraphs:
        if para and para.strip():
            formatted_para = para.replace("\n", "<br>")
            st.markdown(f"<div class='article-para'>{formatted_para}</div>", unsafe_allow_html=True)

    st.markdown("---")
    col1_bottom, col2_bottom = st.columns(2)
    with col1_bottom:
        if st.session_state.prev_url:
            if st.button("◀ 上一页", key="prev_bottom", type="secondary", use_container_width=True):
                load_and_translate(st.session_state.prev_url, add_to_history=True)
                scroll_to_top()
                st.rerun()
    with col2_bottom:
        if st.session_state.next_url:
            if st.button("下一页 ▶", key="next_bottom", type="secondary", use_container_width=True):
                load_and_translate(st.session_state.next_url, add_to_history=True)
                scroll_to_top()
                st.rerun()

    scroll_to_top()
