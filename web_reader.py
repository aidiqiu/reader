import streamlit as st
import requests
import random
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from hashlib import md5

# ---------- 页面配置 ----------
st.set_page_config(page_title="汐涵阅读器", layout="wide", initial_sidebar_state="collapsed")

# ---------- 核心 CSS & JS 注入 ----------
st.markdown("""
<style>
    /* 1. 暴力解决标题显示问题，接管系统自带标题样式 */
    h1 {
        font-size: 2.2rem !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
        padding-top: 0 !important;
        margin-top: 0 !important;
        color: #1E293B !important;
        text-align: center;
    }
    
    /* 基础内边距 */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
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

    /* 原文/双语模式下的英文专属排版 */
    .en-text {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 8px; 
        font-family: Georgia, serif;
    }

    /* 2. 左侧浮动智能菜单样式 (译文/原文/双语) */
    div[data-testid="stRadio"] {
        position: fixed;
        left: 15px;
        top: 50%;
        transform: translateY(-50%);
        z-index: 9999;
        background: rgba(255, 255, 255, 0.95);
        padding: 15px 10px;
        border-radius: 12px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.12);
        border: 1px solid #E2E8F0;
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1); /* 丝滑过渡 */
    }
    /* 让单选框垂直排列更美观 */
    div[data-testid="stRadio"] > div {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    /* 3. 红底白字高亮按钮（针对翻页和开始阅读） */
    button[kind="primary"] {
        background-color: #FF4B4B !important; /* Streamlit 经典红 */
        color: white !important;
        font-weight: bold !important;
        border-radius: 8px !important;
        border: none !important;
        transition: transform 0.1s;
    }
    button[kind="primary"]:active {
        transform: scale(0.95);
    }
    /* 专门放大箭头的字号，保持按钮长度为箭头的 2-3 倍 */
    .nav-btn-container button p {
        font-size: 1.4rem !important; 
    }

    /* 📱 移动端屏幕专属适配 */
    @media (max-width: 768px) {
        h1 { font-size: 1.6rem !important; }
        .block-container { padding-left: 0.8rem !important; padding-right: 0.8rem !important; }
        .article-para { font-size: 1.1rem; line-height: 1.75; margin-bottom: 20px; }
        .en-text { font-size: 0.95rem; }
        /* 手机端悬浮菜单靠边一点，稍微缩小 */
        div[data-testid="stRadio"] {
            left: 5px;
            padding: 10px 5px;
            transform: translateY(-50%) scale(0.9);
        }
    }
</style>

<script>
    // 注入智能滚动监听：上滑显示，下滑隐藏悬浮菜单
    (function() {
        const doc = window.parent.document;
        const mainScrollArea = doc.querySelector('.main');
        if (!mainScrollArea) return;

        // 防止重复绑定
        if (mainScrollArea.dataset.scrollBound === 'true') return;
        mainScrollArea.dataset.scrollBound = 'true';

        let lastScrollTop = 0;
        mainScrollArea.addEventListener('scroll', function() {
            const currentScroll = mainScrollArea.scrollTop;
            const switcher = doc.querySelector('div[data-testid="stRadio"]');
            
            if (switcher) {
                // 如果下滑超过 50px，菜单向左隐藏 
                if (currentScroll > lastScrollTop && currentScroll > 50) {
                    switcher.style.opacity = '0';
                    switcher.style.pointerEvents = 'none';
                    switcher.style.transform = 'translateY(-50%) translateX(-150%)';
                } 
                // 如果上滑，菜单弹回
                else if (currentScroll < lastScrollTop) {
                    switcher.style.opacity = '1';
                    switcher.style.pointerEvents = 'auto';
                    switcher.style.transform = 'translateY(-50%) translateX(0)';
                }
            }
            lastScrollTop = currentScroll <= 0 ? 0 : currentScroll;
        }, { passive: true });
    })();
</script>
""", unsafe_allow_html=True)

# ---------- 百度翻译 API 配置 ----------
BAIDU_APPID = st.secrets.get("BAIDU_APPID", "")
BAIDU_APPKEY = st.secrets.get("BAIDU_APPKEY", "")

# ---------- 会话状态初始化 ----------
if "current_url" not in st.session_state: st.session_state.current_url = ""
if "next_url" not in st.session_state: st.session_state.next_url = ""
if "prev_url" not in st.session_state: st.session_state.prev_url = ""
if "url_history" not in st.session_state: st.session_state.url_history = []
if "paragraphs_data" not in st.session_state: st.session_state.paragraphs_data = []

# 稳定版大标题
st.markdown("# 📚 汐涵阅读器")

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
                return f"[翻译失败]"
        except Exception as e:
            if attempt < 2: time.sleep(0.5)
            else: return f"[翻译异常]"
    return "[翻译失败]"

# ---------- 页面初始化 ----------
def init_new_page(url):
    with st.spinner("正在抓取网页..."):
        paragraphs, prev_link, next_link = fetch_content_and_links(url)
        st.session_state.current_url = url
        st.session_state.prev_url = prev_link or ""
        st.session_state.next_url = next_link or ""
        
        if isinstance(paragraphs, str):
            st.session_state.paragraphs_data = [{"en": paragraphs, "zh": paragraphs}]
        else:
            st.session_state.paragraphs_data = [{"en": p, "zh": None} for p in paragraphs]
            
        if not st.session_state.url_history or st.session_state.url_history[-1] != url:
            st.session_state.url_history.append(url)

def scroll_to_top():
    st.markdown("""<script>(function() { window.scrollTo(0, 0); var main = window.parent.document.querySelector('.main'); if(main) { main.scrollTo(0, 0); } })();</script>""", unsafe_allow_html=True)

# ---------- 开始阅读按钮 ----------
if st.button("开始阅读", type="primary", use_container_width=True):
    if url_input:
        st.session_state.url_history = []
        init_new_page(url_input)
        scroll_to_top()
        st.rerun()
    else:
        st.warning("请先输入一个网址！")

# ==========================================
# 📖 阅读渲染区
# ==========================================
if st.session_state.paragraphs_data:
    st.markdown("---")
    
    # 悬浮阅读模式选择器（UI被CSS接管）
    display_mode = st.radio("阅读模式", ["译文", "原文", "双语"], label_visibility="collapsed")
    
    # 顶部翻页导航栏 (列宽比 1.5 : 7 : 1.5 确保按钮长度是箭头的完美比例)
    st.markdown("<div class='nav-btn-container'>", unsafe_allow_html=True)
    col_p_t, col_s_t, col_n_t = st.columns([1.5, 7, 1.5])
    with col_p_t:
        if st.session_state.prev_url:
            if st.button("◀", key="p_top", type="primary", use_container_width=True):
                init_new_page(st.session_state.prev_url)
                scroll_to_top()
                st.rerun()
    with col_n_t:
        if st.session_state.next_url:
            if st.button("▶", key="n_top", type="primary", use_container_width=True):
                init_new_page(st.session_state.next_url)
                scroll_to_top()
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    # 逐段渲染逻辑（静默后台边看边译，不显示剩余段落）
    for i, item in enumerate(st.session_state.paragraphs_data):
        
        # 1. 后台静默翻译
        if display_mode in ["译文", "双语"] and item["zh"] is None:
            item["zh"] = translate_single_paragraph(item["en"])

        # 2. 页面内容展示
        if display_mode == "译文":
            if item["zh"]:
                st.markdown(f"<div class='article-para'>{item['zh']}</div>", unsafe_allow_html=True)
                
        elif display_mode == "原文":
            st.markdown(f"<div class='article-para en-text' style='color:#2F3542;'>{item['en']}</div>", unsafe_allow_html=True)
            
        elif display_mode == "双语":
            if item["en"] and item["zh"]:
                st.markdown(f"<div class='article-para en-text'>{item['en']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='article-para' style='margin-top:-15px;'>{item['zh']}</div>", unsafe_allow_html=True)
                st.markdown("<hr style='margin:10px 0; border:0; border-top:1px dashed #E2E8F0;'>", unsafe_allow_html=True)

    # 底部翻页导航栏
    st.markdown("---")
    st.markdown("<div class='nav-btn-container'>", unsafe_allow_html=True)
    col_p_b, col_s_b, col_n_b = st.columns([1.5, 7, 1.5])
    with col_p_b:
        if st.session_state.prev_url:
            if st.button("◀", key="p_bot", type="primary", use_container_width=True):
                init_new_page(st.session_state.prev_url)
                scroll_to_top()
                st.rerun()
    with col_n_b:
        if st.session_state.next_url:
            if st.button("▶", key="n_bot", type="primary", use_container_width=True):
                init_new_page(st.session_state.next_url)
                scroll_to_top()
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
