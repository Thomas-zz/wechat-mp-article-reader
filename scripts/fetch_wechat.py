#!/usr/bin/env python3
"""读取微信公众号文章正文。

唯一入口：抓取 + 解析 + 浏览器兜底 + 多格式输出，纯标准库（playwright 可选）。

用法：
  python3 fetch_wechat.py "<mp.weixin.qq.com/s/... url>"
  python3 fetch_wechat.py --html saved.html --format json
  python3 fetch_wechat.py "<url>" --mode browser      # 强制 playwright
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import ssl


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.40 NetType/WIFI Language/zh_CN"
)

# 正文容器候选（按优先级）
CONTENT_SELECTORS = [
    "#js_content",
    "#js_article_content",
    "#img-content",
    ".rich_media_content",
    "article",
    ".rich_media_area_primary_inner",
]

# 从正文里删除的噪声子树
DROP_SELECTORS = [
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "form",
    "input",
    "button",
    ".original_area_primary",
    ".rich_media_tool",
    ".rich_media_meta_list",
    ".rich_media_area_extra",
    ".wx_profile_card_container",
    ".qr_code_pc_outer",
    ".reward_area",
    ".js_uneditable",
    "#js_tags",
    "#js_pc_qr_code",
    "#js_preview_reward_area",
    "#js_share_content",
    "#js_read_area3",
    "#js_toobar3",
    "mp-common-profile",
]

# 块级标签：每个的文本作为独立段落
BLOCK_TAGS = {
    "p", "li", "blockquote", "pre", "figcaption",
    "h1", "h2", "h3", "h4", "h5", "h6",
}

# 整行噪声（出现即丢弃该段）
NOISE_LINES = {
    "微信扫一扫",
    "继续滑动看下一个",
    "轻触阅读原文",
    "预览时标签不可点",
    "喜欢此内容的人还喜欢",
    "分享",
    "收藏",
    "点赞",
    "在看",
}

# 触发"页面被拦/壳页"判定的关键词
BLOCKED_MARKERS = (
    "当前环境异常",
    "请在微信客户端打开链接",
    "访问过于频繁",
    "网页包含敏感内容",
    "已快捷分享给你的好友",
)

# 内容过薄的阈值（去空白后的字符数）
MIN_TEXT_CHARS = 180

# 隐式闭合规则：遇到这些块级标签开始时，自动关闭未闭合的同级块级标签
IMPLICIT_CLOSE_ON = {
    "p": {"p", "li"},
    "li": {"p", "li"},
    "h1": {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"},
    "h2": {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"},
    "h3": {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"},
    "h4": {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"},
    "h5": {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"},
    "h6": {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"},
    "div": {"p", "li"},
    "section": {"p", "li"},
}

# void 元素（自闭合，无结束标签）
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


# ---------------------------------------------------------------------------
# 轻量 DOM（用 html.parser 事件构建，替代 lxml）
# ---------------------------------------------------------------------------

@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list[Any] = field(default_factory=list)
    parent: Any = None
    text: str = ""  # 直接文本（data 拼接），子节点文本见 itertext()

    @property
    def id(self) -> str:
        return self.attrs.get("id", "")

    @property
    def classes(self) -> set[str]:
        cls = self.attrs.get("class", "")
        return {c for c in cls.split() if c}

    def getparent(self) -> Any:
        return self.parent


class DOMBuilder(HTMLParser):
    """把 HTML 解析成 Node 树。带务实的隐式闭合启发式，容忍公众号页面的不规范标签。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="__root__", attrs={})
        self.stack: list[Node] = [self.root]
        self._collect_scripts = False
        self.scripts: list[str] = []

    def _current(self) -> Node:
        return self.stack[-1]

    def _implicit_close(self, new_tag: str) -> None:
        closes = IMPLICIT_CLOSE_ON.get(new_tag)
        if not closes:
            return
        # 从栈顶往下，关闭需要隐式闭合的块级标签
        while len(self.stack) > 1 and self._current().tag in closes:
            self.stack.pop()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            # 自闭合，不进栈
            node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self._current())
            self._current().children.append(node)
            return
        self._implicit_close(tag)
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self._current())
        self._current().children.append(node)
        self.stack.append(node)
        if tag == "script":
            self._collect_scripts = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self._current())
        self._current().children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        # 从栈顶找到匹配的标签，弹出它及以上
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                if tag == "script":
                    self._collect_scripts = False
                return
        # 没找到匹配：忽略多余结束标签

    def handle_data(self, data: str) -> None:
        if self._collect_scripts:
            self.scripts.append(data)
            return
        if data:
            self._current().text += data


def build_tree(document: str) -> tuple[Node, str]:
    builder = DOMBuilder()
    builder.feed(document)
    builder.close()
    return builder.root, "\n".join(builder.scripts)


# ---------------------------------------------------------------------------
# 选择器（CSS 子集：#id / .class / tag）
# ---------------------------------------------------------------------------

def _matches(node: Node, selector: str) -> bool:
    if selector.startswith("#"):
        return node.id == selector[1:]
    if selector.startswith("."):
        return selector[1:] in node.classes
    return node.tag == selector


def select_all(root: Node, selector: str) -> list[Node]:
    result: list[Node] = []
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.children:
            if isinstance(child, Node):
                if _matches(child, selector):
                    result.append(child)
                stack.append(child)
    return result


def select_first(root: Node, selector: str) -> Node | None:
    nodes = select_all(root, selector)
    return nodes[0] if nodes else None


def itertext(node: Node) -> str:
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node.children:
        if isinstance(child, Node):
            parts.append(itertext(child))
        elif isinstance(child, str):
            parts.append(child)
    return "".join(parts)


def iterdescendants(root: Node):
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.children:
            if isinstance(child, Node):
                yield child
                stack.append(child)


def getparent(node: Node) -> Node | None:
    return node.parent


# ---------------------------------------------------------------------------
# 解析逻辑（移植自 lxml 版，用上面的 DOM 等价实现）
# ---------------------------------------------------------------------------

JS_ESCAPE_RE = re.compile(r'\\x([0-9A-Fa-f]{2})|\\u([0-9A-Fa-f]{4})|\\\\|\\\'|\\"|\\n|\\r|\\t')


def decode_js_escapes(value: str) -> str:
    def repl(m: re.Match[str]) -> str:
        if m.group(1):
            return chr(int(m.group(1), 16))
        if m.group(2):
            return chr(int(m.group(2), 16))
        return {
            "\\\\": "\\",
            "\\'": "'",
            '\\"': '"',
            "\\n": "\n",
            "\\r": "\r",
            "\\t": "\t",
        }[m.group(0)]
    return JS_ESCAPE_RE.sub(repl, value)


def normalize_inline_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("​", "").replace("﻿", "")
    return re.sub(r"\s+", " ", text).strip()


def is_noise_line(text: str) -> bool:
    if text in NOISE_LINES:
        return True
    if len(text) <= 2:
        return False
    # 短行里含互动标记的当噪声
    return any(marker in text for marker in ("赞", "在看", "阅读原文")) and len(text) < 18


def find_content_root(tree: Node) -> Node | None:
    for selector in CONTENT_SELECTORS:
        node = select_first(tree, selector)
        if node is not None:
            return node
    return None


def cleanup_content_root(root: Node) -> None:
    # 删除 drop 子树 + display:none
    to_remove: list[Node] = []
    for selector in DROP_SELECTORS:
        for node in select_all(root, selector):
            to_remove.append(node)
    for node in iterdescendants(root):
        style = node.attrs.get("style", "")
        if re.search(r"display\s*:\s*none", style, re.I):
            to_remove.append(node)
    for node in to_remove:
        parent = node.parent
        if parent is not None and node in parent.children:
            parent.children.remove(node)


def has_block_ancestor(node: Node, root: Node) -> bool:
    parent = node.parent
    while parent is not None and parent is not root:
        if parent.tag in BLOCK_TAGS:
            return True
        parent = parent.parent
    return False


def extract_content_text(root: Node | None) -> str:
    if root is None:
        return ""
    blocks: list[str] = []
    for node in iterdescendants(root):
        if node.tag not in BLOCK_TAGS:
            continue
        if has_block_ancestor(node, root):
            continue
        text = normalize_inline_text(" ".join(p.strip() for p in itertext(node).split() if p.strip()))
        if not text or is_noise_line(text):
            continue
        blocks.append(text)

    if not blocks:
        fallback = itertext(root)
        for line in fallback.splitlines():
            cleaned = normalize_inline_text(line)
            if cleaned and not is_noise_line(cleaned):
                blocks.append(cleaned)

    blocks = dedupe_preserve_order(blocks)
    return "\n\n".join(blocks).strip()


def dedupe_preserve_order(blocks: list[str]) -> list[str]:
    out: list[str] = []
    for b in blocks:
        if out and out[-1] == b:
            continue
        out.append(b)
    return out


# ---------------------------------------------------------------------------
# 字段提取
# ---------------------------------------------------------------------------

def _meta(tree: Node, attr_name: str, attr_value: str) -> str | None:
    for node in iterdescendants(tree):
        if node.tag == "meta" and node.attrs.get(attr_name) == attr_value:
            v = normalize_inline_text(node.attrs.get("content", ""))
            return v or None
    return None


def _first_text(tree: Node, selector: str) -> str | None:
    node = select_first(tree, selector)
    if node is None:
        return None
    return normalize_inline_text(itertext(node)) or None


def _regex_group(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.S)
    if not m:
        return None
    return normalize_inline_text(m.group(1))


def extract_title(tree: Node, scripts: str) -> str:
    return _first_non_empty(
        _meta(tree, "property", "og:title"),
        _meta(tree, "name", "twitter:title"),
        _first_text(tree, "#activity-name"),
        _first_text(tree, "h1"),
        _first_text(tree, ".rich_media_title"),
        _regex_group(scripts, r"var\s+msg_title\s*=\s*['\"]([^'\"]+)"),
        "微信公众号文章",
    )


def extract_account(tree: Node, scripts: str, raw: str) -> str | None:
    return _first_non_empty(
        _first_text(tree, "#js_name"),
        _first_text(tree, ".profile_nickname"),
        _regex_group(scripts, r'var\s+nickname\s*=\s*htmlDecode\(["\'](.+?)["\']\)'),
        _regex_group(raw, r'"nickname"\s*:\s*"(.+?)"'),
        _regex_group(raw, r'nick_name\s*[:=]\s*["\'](.+?)["\']'),
    )


def extract_author(tree: Node) -> str | None:
    return _first_non_empty(
        _meta(tree, "name", "author"),
        _meta(tree, "property", "og:article:author"),
        _first_text(tree, "#js_author_name"),
        _first_text(tree, ".rich_media_meta_text"),
    )


def extract_publish_time(scripts: str, raw: str) -> str | None:
    patterns = [
        r'"publish_time"\s*:\s*"([^"]+)"',
        r"publish_time\s*[:=]\s*['\"]([^'\"]+)['\"]",
        r'createTime\s*[:=]\s*["\']?(\d{10})',
        r'"createTime"\s*:\s*(\d{10})',
        r"\bct\s*=\s*['\"]?(\d{10})",
    ]
    for pattern in patterns:
        m = re.search(pattern, scripts) or re.search(pattern, raw)
        if not m:
            continue
        parsed = _normalize_publish_time(m.group(1).strip())
        if parsed:
            return parsed
    return None


def _normalize_publish_time(value: str) -> str | None:
    if re.fullmatch(r"\d{10}", value):
        return datetime.fromtimestamp(int(value)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return value or None


def extract_biz(url: str | None, raw: str) -> str | None:
    if url:
        parsed = urlparse(url)
        value = parse_qs(parsed.query).get("__biz")
        if value:
            return value[0]
    return _regex_group(raw, r"__biz=([A-Za-z0-9%+/=_-]+)")


def extract_article_link(tree: Node, requested_url: str | None) -> str | None:
    return _first_non_empty(
        _meta(tree, "property", "og:url"),
        _meta(tree, "property", "twitter:url"),
        requested_url,
    )


def _first_non_empty(*values: str | None) -> str:
    for v in values:
        if v and v.strip():
            return v.strip()
    return ""


# ---------------------------------------------------------------------------
# content_noencode 兜底（结构化路径拿不到时的可靠正则路径）
# ---------------------------------------------------------------------------

def extract_body_via_noencode(raw: str) -> str:
    encoded = _first_non_empty(
        _regex_group(raw, r"content_noencode\s*[:=]\s*'((?:\\.|[^'])*)'"),
        _regex_group(raw, r'"content_noencode"\s*[:=]\s*"((?:\\.|[^"])*)"'),
    )
    if not encoded:
        return ""
    decoded = decode_js_escapes(encoded)
    tree, _ = build_tree(decoded)
    # content_noencode 通常是正文片段 HTML，不一定有 js_content 容器，
    # 拿不到容器时直接从整树提取块文本。
    root = find_content_root(tree) or tree
    return extract_content_text(root)


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    """构造一个带 CA 证书的 SSL 上下文。

    macOS 上 python.org 安装的 Python 自带 openssl 目录常缺 cert.pem，
    导致默认 HTTPS 验证失败。优先用 certifi；没有则回退系统默认；最后才放宽。
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    if ctx.get_ca_certs(binary_form=True):
        return ctx
    # 极端情况：系统没有可用 CA。放宽验证以便能用，但标记不安全（仅抓取公开页面可接受）。
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_simple_html(url: str, timeout: float) -> str:
    request = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        payload = response.read()
        encoding = response.headers.get_content_charset() or "utf-8"
    try:
        return payload.decode(encoding, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def fetch_browser_html(url: str, timeout: float) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright 未安装。浏览器兜底需要它：\n"
            "  pip install playwright && python3 -m playwright install chromium\n"
            "或改用 --html <手动另存的 HTML 路径>。"
        ) from exc
    timeout_ms = int(timeout * 1000)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="zh-CN",
                                viewport={"width": 1440, "height": 1600})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1200)
            for _ in range(6):
                page.mouse.wheel(0, 2200)
                page.wait_for_timeout(350)
            page.evaluate(
                """() => {
                  for (const img of document.querySelectorAll('img[data-src]')) {
                    if (!img.getAttribute('src') || img.getAttribute('src').startsWith('data:')) {
                      img.setAttribute('src', img.getAttribute('data-src'));
                    }
                  }
                }"""
            )
            page.wait_for_timeout(500)
            return page.content()
        finally:
            browser.close()


def is_too_thin(content: str) -> bool:
    compact = re.sub(r"\s+", "", content)
    return len(compact) < MIN_TEXT_CHARS or any(m in content for m in BLOCKED_MARKERS)


def fetch_with_mode(url: str, mode: str, timeout: float) -> tuple[str, str]:
    """返回 (html, method)。auto 模式自动从 simple 降级到 browser。"""
    if mode == "simple":
        return fetch_simple_html(url, timeout), "simple"

    if mode == "browser":
        return fetch_browser_html(url, timeout), "browser"

    # auto
    simple_html = fetch_simple_html(url, timeout)
    tree, scripts = build_tree(simple_html)
    root = find_content_root(tree)
    content = extract_content_text(root)
    if not is_too_thin(content):
        return simple_html, "simple"
    if not is_too_thin(extract_body_via_noencode(simple_html)):
        return simple_html, "simple"
    if _playwright_available():
        try:
            return fetch_browser_html(url, timeout), "browser"
        except RuntimeError:
            return simple_html, "simple"
    return simple_html, "simple"


def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Article 数据结构 + 渲染
# ---------------------------------------------------------------------------

@dataclass
class Article:
    url: str | None
    article_link: str | None
    title: str
    account: str | None
    author: str | None
    publish_time: str | None
    biz: str | None
    content: str
    method: str
    body_source: str
    fetched_at: str
    ok: bool = True
    reason: str = ""


def parse_html(raw: str, requested_url: str | None, method: str) -> Article:
    tree, scripts = build_tree(raw)
    content_root = find_content_root(tree)
    cleanup_content_root(content_root) if content_root else None
    content = extract_content_text(content_root)
    body_source = "structured" if content else ""

    if not content:
        # content_noencode 兜底
        noencode = extract_body_via_noencode(raw)
        if noencode:
            content = noencode
            body_source = "content_noencode"

    title = extract_title(tree, scripts)
    article_link = extract_article_link(tree, requested_url)
    account = extract_account(tree, scripts, raw)
    author = extract_author(tree)
    publish_time = extract_publish_time(scripts, raw)
    biz = extract_biz(article_link or requested_url, raw)

    return Article(
        url=requested_url,
        article_link=article_link,
        title=title,
        account=account,
        author=author,
        publish_time=publish_time,
        biz=biz,
        content=content,
        method=method,
        body_source=body_source,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        ok=bool(content),
        reason="" if content else "NO_CONTENT",
    )


def render_sentinel(article: Article) -> str:
    return "\n".join([
        "===TITLE===",
        article.title,
        "===ACCOUNT===",
        article.account or "",
        "===AUTHOR===",
        article.author or "",
        "===DATE===",
        article.publish_time or "",
        "===BODY===",
        article.content,
        "",
    ])


def render_json(article: Article, diag: bool = False) -> str:
    payload = {
        "ok": article.ok,
        "reason": article.reason,
        "title": article.title,
        "account": article.account,
        "author": article.author,
        "publish_time": article.publish_time,
        "biz": article.biz,
        "article_link": article.article_link,
        "content": article.content,
        "method": article.method,
        "body_source": article.body_source,
        "fetched_at": article.fetched_at,
    }
    if diag:
        payload["diag"] = {
            "body_chars": len(article.content),
            "body_source": article.body_source,
            "method": article.method,
        }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_markdown(article: Article) -> str:
    lines = [
        "---",
        f"title: {_yaml(article.title)}",
        f"source: {article.url or ''}",
        f"account: {_yaml(article.account)}",
        f"author: {_yaml(article.author)}",
        f"publish_time: {_yaml(article.publish_time)}",
        f"biz: {_yaml(article.biz)}",
        f"method: {article.method}",
        f"fetched_at: {article.fetched_at}",
        "---",
        "",
        f"# {article.title}",
        "",
    ]
    summary = " · ".join(p for p in [article.account, article.author, article.publish_time] if p)
    if summary:
        lines += [summary, ""]
    lines.append(article.content or "(未提取到正文)")
    return "\n".join(lines).rstrip() + "\n"


def _yaml(value: str | None) -> str:
    if value is None or value == "":
        return "null"
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="读取微信公众号文章正文（纯标准库，playwright 可选）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            '  python3 fetch_wechat.py "https://mp.weixin.qq.com/s/xxxx"\n'
            "  python3 fetch_wechat.py --html saved.html --format json\n"
            '  python3 fetch_wechat.py "<url>" --mode browser --format markdown'
        ),
    )
    p.add_argument("url", nargs="?", help="微信公众号文章链接")
    p.add_argument("--html", help="解析本地已存 HTML 文件，不重新下载")
    p.add_argument("--mode", choices=["auto", "simple", "browser"], default="auto",
                   help="抓取模式：auto(默认,simple→过薄则playwright)/simple/browser")
    p.add_argument("--format", choices=["text", "json", "markdown"], default="text",
                   help="输出格式：text(默认,sentinel区块)/json/markdown")
    p.add_argument("--output", "-o", help="写入文件而非 stdout")
    p.add_argument("--diag", action="store_true", help="json 格式下附带诊断字段")
    p.add_argument("--timeout", type=float, default=20.0, help="网络超时秒数（默认 20）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.url and not args.html:
        print("错误：必须提供文章链接或 --html 参数", file=sys.stderr)
        return 2

    try:
        if args.html:
            raw = Path(args.html).read_text(encoding="utf-8", errors="ignore")
            article = parse_html(raw, args.url, "html")
            if not article.ok:
                article.reason = article.reason or "NO_CONTENT"
        else:
            assert args.url is not None
            raw, method = fetch_with_mode(args.url, args.mode, args.timeout)
            article = parse_html(raw, args.url, method)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        out = render_json(article, diag=args.diag)
    elif args.format == "markdown":
        out = render_markdown(article)
    else:
        if not article.ok:
            # sentinel 模式下失败给清晰引导
            print("NO_CONTENT", file=sys.stderr)
            print(
                "未能提取正文。可尝试：\n"
                "  1) python3 fetch_wechat.py --html <手动另存的HTML路径>\n"
                "  2) pip install playwright && python3 -m playwright install chromium 后重试",
                file=sys.stderr,
            )
            return 1
        out = render_sentinel(article)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(args.output)
    else:
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
