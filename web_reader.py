import streamlit as st
import requests
import random
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from hashlib import md5

st.set_page_config(page_title="汐涵阅读器", layout="wide")

# ---------- 响应式 CSS 样式（全面适配移动端与大屏）----------
st.markdown("""
<style>
    /* 强力修复标题裁剪问题 */
    .main .block-container h1 {
        font-size: 2.2rem !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
        padding-top: 0.5rem !important;
        padding-bottom: 0.5rem !important;
    }
    
    /* 基础内边距优化 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
    }
    
    /* 中文正文排版优化 */
    .article-para {
        font-size: 1.18rem !important;
        line-height: 1.85 !important;
        margin-bottom: 26px !important;
        text-align: justify;
        letter-spacing: 0.5px;
        color: #2F3542;
    }

    /* 📱 移动端屏幕专属适配 (当屏幕宽度小于 768px 时生效) */
    @media (max-width: 768px) {
        .main .block-container h1 {
            font-size: 1.6rem !important; /* 手机端标题稍微调小，防止换行过多 */
        }
        .block-container {
            padding-left: 0.8rem !important;   /* 缩减手机两边留白 */
            padding-right: 0.8rem !important;
            padding-top: 0.5rem !important;
        }
        .article-para {
            font-size: 1.1rem !important;  /* 手机端更适合的字号 */
            line-height: 1.75 !important;
            margin-bottom: 20px !important; /* 稍微紧凑一点的段落间距 */
        }
        /* 强制让移动端的按钮在大框架下有更好的触控体验 */
        .stButton>button {
            padding: 0.5rem 0.2rem !important;
            font-size: 0.95rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# ---------- 安全读取百度翻译 API 配置 ----------
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
if "show_success" not in st.session_state:
    st.session_state.show_success = False

st.markdown("# 📚 汐涵阅读器")
st.markdown("输入英文书籍章节的网址，沉浸式体验中文翻译。")

url_input = st.text_input(
    "",
    placeholder="在这里粘贴书籍章节的网址，例如: https://bookreadfree.com/507607/12466798",
    key="url_input"
)

# ---------- 段落过滤函数（拒绝将原页面的“上一页/下一页”文本送去翻译）----------
def is_valid_paragraph(text):
    """精确清洗非正文元素，防止“上一页”等导航文本混入阅读区"""
    if not text or len(text.strip()) < 2:
        return False

    text_lower = text.lower().strip()

    # 1. 拦截完全匹配或包含常见翻页词和符号的短文本
    nav_words = [
        'next', 'prev', 'previous', 'next »', '« prev', '« previous', 
        'next page', 'previous page', 'index', 'contents', 'table of contents',
        '‹', '›', '»', '«', 'rightarrow', 'leftarrow'
    ]
    for word in nav_words:
        if word == text_lower:
            return False
        if word in text_lower and len(text) < 40:
            return False

    # 2. 过滤小说网站常用的其他干扰项
    exclude_keywords = ['©', 'copyright', 'all rights reserved', 'chapter', 'menu', 'home', 'page']
    for kw in exclude_keywords:
        if kw in text_lower and len(text) < 100:
            return False

    # 3. 过滤纯数字
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

        # 尝试寻找正文核心容器
        content_container = None
        possible_selectors = [
            'div[class*="content"]', 'div[id*="content"]', 
            'div[class*="chapter"]', 'div[id*="chapter"]', 
            'article', 'div[class*="reader"]', 'div[class*="book"]'
        ]
        for selector in possible_selectors:
            container = soup.select_one(selector)
            if container and len(container.get_text()) > 400:
                content_container = container
                break
        
        if not content_container:
            content_container = soup.body if soup.body else soup

        # 处理换行符
        for br in content_container.find_all("br"):
            br.replace_with("\n")
        
        raw_text = content_container.get_text()
        lines = [line.strip() for line in raw_text.split('\n')]
        
        # 核心清洗：不符合正文标准的（包括原站点的翻页文字）直接干掉
        paragraphs = [p for p in lines if is_valid_paragraph(p)]

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

# ---------- 单段落翻译 ----------
def translate_single_paragraph(text):
    if not text or len(text.strip()) == 0:
        return ""

    if not BAIDU_APPID or not BAIDU_APPKEY:
        return "[错误: 未在 Secrets 中配置百度翻译密钥]"

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
                translated_chunks = [sub_res['dst'] for sub_res in result['trans_result']]
                return " ".join(translated_chunks)
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
            # 标记需要展示“成功提示”
            st.session_state.show_success = True

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
    
    # 【新功能】翻译完成提示信息 3 秒后自动消失
    if st.session_state.show_success:
        msg_placeholder = st.empty()
        msg_placeholder.success("🎉 翻译完成，请尽情阅读！")
        time.sleep(3.0)
        msg_placeholder.empty() # 3秒时间到，清空该组件，不占屏幕空间
        st.session_state.show_success = False # 重置状态

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

    # 逐段优雅渲染
    for para in st.session_state.translated_paragraphs:
        if para and para.strip():
            st.markdown(f"<div class='article-para'>{para}</div>", unsafe_allow_html=True)

    # 底部导航栏
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

    # 再次确保滚动置顶
    scroll_to_top()
