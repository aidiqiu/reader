import streamlit as st
import requests
import random
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from hashlib import md5

# ---------- 页面配置 ----------
st.set_page_config(page_title="汐涵阅读器", layout="wide")

# ---------- 响应式 CSS 样式 ----------
st.markdown("""
<style>
    /* 彻底解决标题裁剪：改用自定义容器，脱离原生限制 */
    .app-title {
        font-size: 1.6rem;
        font-weight: 800;
        text-align: center;
        margin-top: 0.5rem;
        margin-bottom: 1.5rem;
        color: #1E293B;
        line-height: 1.4;
    }
    
    /* 基础内边距优化 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    
    /* 中文正文排版优化 */
    .article-para {
        font-size: 1.18rem;
        line-height: 1.85;
        margin-bottom: 26px;
        text-align: justify;
        letter-spacing: 0.5px;
        color: #2F3542;
    }

    /* 原文/双语模式下的英文专属排版（字号稍小，颜色变浅区分） */
    .en-text {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 8px; /* 和下方的中文紧凑一点 */
        font-family: Georgia, serif;
    }

    /* 优化阅读模式选择器的外观（类似浮动胶囊） */
    div[data-testid="stRadio"] > div {
        display: flex;
        justify-content: center;
        background-color: #F1F5F9;
        padding: 5px 15px;
        border-radius: 25px;
        width: fit-content;
        margin: 0 auto 20px auto;
        gap: 15px;
    }

    /* 📱 移动端屏幕专属适配 */
    @media (max-width: 768px) {
        .app-title {
            font-size: 1.4rem;
        }
        .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        .article-para {
            font-size: 1.1rem;
            line-height: 1.75;
            margin-bottom: 20px;
        }
        .en-text {
            font-size: 0.95rem;
        }
        /* 翻页按钮铺满 */
        .stButton>button {
            padding: 0.4rem 0 !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# ---------- 百度翻译 API 配置 ----------
BAIDU_APPID = st.secrets.get("BAIDU_APPID", "")
BAIDU_APPKEY = st.secrets.get("BAIDU_APPKEY", "")

# ---------- 会话状态初始化 ----------
if "current_url" not in st.session_state:
    st.session_state.current_url = ""
if "next_url" not in st.session_state:
    st.session_state.next_url = ""
if "prev_url" not in st.session_state:
    st.session_state.prev_url = ""
if "url_history" not in st.session_state:
    st.session_state.url_history = []
# 核心改变：改用列表字典存储段落，按需翻译
# 格式: [{"en": "原文", "zh": "译文"或None}]
if "paragraphs_data" not in st.session_state:
    st.session_state.paragraphs_data = []

# 自定义标题（解决显示不全）
st.markdown("<div class='app-title'>📚 汐涵阅读器</div>", unsafe_allow_html=True)

url_input = st.text_input(
    "",
    placeholder="粘贴书籍章节网址，例如: https://bookreadfree.com/507607/12466798",
    key="url_input"
)

# ---------- 段落过滤函数 ----------
def is_valid_paragraph(text):
    if not text or len(text.strip()) < 2: return False
    text_lower = text.lower().strip()
    nav_words = ['next', 'prev', 'previous', 'next »', '« prev', '« previous', 'next page', 'previous page']
    for word in nav_words:
        if word == text_lower: return False
        if word in text_lower and len(text) < 40: return False
    exclude_keywords = ['©', 'copyright', 'all rights reserved', 'chapter', 'menu', 'home', 'page']
    for kw in exclude_keywords:
        if kw in text_lower and len(text) < 100: return False
    if text.replace('.', '').replace(',', '').replace(' ', '').isdigit(): return False
    return True

# ---------- 抓取网页内容 ----------
def fetch_content_and_links(target_url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(target_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        content_container = None
        possible_selectors = ['div[class*="content"]', 'div[id*="content"]', 'div[class*="chapter"]', 'article', 'div[class*="reader"]']
        for selector in possible_selectors:
            container = soup.select_one(selector)
            if container and len(container.get_text()) > 400:
                content_container = container
                break
        if not content_container: content_container = soup.body if soup.body else soup

        for br in content_container.find_all("br"): br.replace_with("\n")
        raw_text = content_container.get_text()
        lines = [line.strip() for line in raw_text.split('\n')]
        paragraphs = [p for p in lines if is_valid_paragraph(p)]

        # 链接提取
        prev_link = None
        prev_tag = soup.find('a', rel='prev') or soup.find('a', class_='p') or soup.find('a', string=lambda t: t and ('prev' in t.lower() or 'previous' in t.lower()))
        if prev_tag and prev_tag.get('href'): prev_link = urljoin(target_url, prev_tag['href'])

        next_link = None
        next_tag = soup.find('a', rel='next') or soup.find('a', class_='n') or soup.find('a', string=lambda t: t and 'next' in t.lower())
        if next_tag and next_tag.get('href'): next_link = urljoin(target_url, next_tag['href'])

        return paragraphs, prev_link, next_link
    except Exception as e:
        return f"抓取错误: {e}", None, None

# ---------- 单段落翻译 ----------
def translate_single_paragraph(text):
    if not text or len(text.strip()) == 0: return ""
    if not BAIDU_APPID or not BAIDU_APPKEY: return "[未配置百度翻译密钥]"
    
    endpoint = "https://fanyi-api.baidu.com/api/trans/vip/translate"
    for attempt in range(3):
        try:
            salt = str(random.randint(32768, 65536))
            sign = md5((BAIDU_APPID + text + salt + BAIDU_APPKEY).encode('utf-8')).hexdigest()
            params = {'q': text, 'from': 'en', 'to': 'zh', 'appid': BAIDU_APPID, 'salt': salt, 'sign': sign}
            response = requests.post(endpoint, data=params, timeout=10)
            res = response.json()
            if 'trans_result' in res:
                return " ".join([chunk['dst'] for chunk in res['trans_result']])
            else:
                if attempt < 2: time.sleep(0.5); continue
                return f"[翻译失败: {res.get('error_msg', '未知')}]"
        except Exception as e:
            if attempt < 2: time.sleep(0.5)
            else: return f"[翻译异常]"
    return "[翻译失败]"

# ---------- 页面初始化（仅抓取，不阻塞翻译） ----------
def init_new_page(url):
    with st.spinner("正在抓取网页..."):
        paragraphs, prev_link, next_link = fetch_content_and_links(url)
        st.session_state.current_url = url
        st.session_state.prev_url = prev_link or ""
        st.session_state.next_url = next_link or ""
        
        if isinstance(paragraphs, str):
            st.session_state.paragraphs_data = [{"en": paragraphs, "zh": paragraphs}]
        else:
            # 初始化状态：只有英文，中文为 None
            st.session_state.paragraphs_data = [{"en": p, "zh": None} for p in paragraphs]
            
        if not st.session_state.url_history or st.session_state.url_history[-1] != url:
            st.session_state.url_history.append(url)

# ---------- 强制滚动到顶部 ----------
def scroll_to_top():
    st.markdown("""
    <script>
        (function() { window.scrollTo(0, 0); var main = window.parent.document.querySelector('.main'); if(main) { main.scrollTo(0, 0); } })();
    </script>
    """, unsafe_allow_html=True)

# ---------- 按钮触发区 ----------
if st.button("开始阅读", type="primary", use_container_width=True):
    if url_input:
        st.session_state.url_history = []
        init_new_page(url_input)
        scroll_to_top()
        st.rerun()
    else:
        st.warning("请先输入一个网址！")

# ==========================================
# 📖 阅读渲染区（核心优化：边译边读）
# ==========================================
if st.session_state.paragraphs_data:
    st.markdown("---")
    
    # 浮动阅读模式选择（译文/原文/双语）
    display_mode = st.radio("阅读模式", ["译文", "原文", "双语"], horizontal=True, label_visibility="collapsed")
    
    # 极简翻页按钮 (上/下分布在两边)
    col_prev_t, col_space_t, col_next_t = st.columns([1, 6, 1])
    with col_prev_t:
        if st.session_state.prev_url:
            if st.button("◀", key="p_top", use_container_width=True):
                init_new_page(st.session_state.prev_url)
                scroll_to_top()
                st.rerun()
    with col_next_t:
        if st.session_state.next_url:
            if st.button("▶", key="n_top", use_container_width=True):
                init_new_page(st.session_state.next_url)
                scroll_to_top()
                st.rerun()

    # 动态进度提示框
    progress_box = st.empty()
    untranslated_count = sum(1 for p in st.session_state.paragraphs_data if p["zh"] is None)
    
    # 逐段渲染逻辑
    for i, item in enumerate(st.session_state.paragraphs_data):
        
        # 1. 动态按需翻译
        if display_mode in ["译文", "双语"] and item["zh"] is None:
            # 提示用户正在翻译的进度
            progress_box.caption(f"⏳ 正在边译边读... (剩余 {untranslated_count} 段)")
            # 发起翻译请求
            item["zh"] = translate_single_paragraph(item["en"])
            untranslated_count -= 1

        # 2. 页面内容展示
        if display_mode == "译文":
            if item["zh"]:
                st.markdown(f"<div class='article-para'>{item['zh']}</div>", unsafe_allow_html=True)
                
        elif display_mode == "原文":
            # 纯原文模式下，不会触发翻译，瞬间显示
            st.markdown(f"<div class='article-para en-text' style='color:#2F3542;'>{item['en']}</div>", unsafe_allow_html=True)
            
        elif display_mode == "双语":
            if item["en"] and item["zh"]:
                # 双语排版：上方原文（灰色较小），下方译文（黑色正文）
                st.markdown(f"<div class='article-para en-text'>{item['en']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='article-para' style='margin-top:-15px;'>{item['zh']}</div>", unsafe_allow_html=True)
                st.markdown("<hr style='margin:10px 0; border:0; border-top:1px dashed #E2E8F0;'>", unsafe_allow_html=True)

    # 翻译完成提示（3秒后清空）
    if untranslated_count == 0 and display_mode != "原文":
        progress_box.success("🎉 本章全部翻译完成！")
        time.sleep(3)
        progress_box.empty()

    # 底部极简翻页按钮
    st.markdown("---")
    col_prev_b, col_space_b, col_next_b = st.columns([1, 6, 1])
    with col_prev_b:
        if st.session_state.prev_url:
            if st.button("◀", key="p_bot", use_container_width=True):
                init_new_page(st.session_state.prev_url)
                scroll_to_top()
                st.rerun()
    with col_next_b:
        if st.session_state.next_url:
            if st.button("▶", key="n_bot", use_container_width=True):
                init_new_page(st.session_state.next_url)
                scroll_to_top()
                st.rerun()
