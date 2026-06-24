# 微信公众号文章读取器（Claude Code Skill）

读取微信公众号文章正文的 Claude Code skill。纯 Python 标准库，**安装即用、零第三方依赖**，浏览器兜底可选。

把一个 `mp.weixin.qq.com` 链接丢给它，就能拿到标题、账号、作者、发布时间和正文——而 WebFetch / 普通爬虫抓公众号页面几乎必然只拿到一个壳。

---

## 它解决什么问题

公众号文章页面有几个让人头疼的特性：

- **正文懒加载 / 反爬壳**：直接 `curl` 或 WebFetch 经常只拿到页面骨架，没有正文。
- **HTML 不规范**：大量内联样式、嵌套 `section`、隐式闭合标签，regex 解析很脆。
- **混入大量 UI 噪声**：底部"赞 / 在看 / 分享 / 继续滑动看下一个 / 微信扫一扫"等。

本 skill 用一套结构化解析（`html.parser` 构建 DOM → 定位正文容器 → 删噪声子树 → 按块级标签切段落 → 过滤噪声行）解决上述问题，并在结构化路径失效时回退到 `content_noencode` 正则解码。

---

## 安装

本 skill 是一个目录，把它放到 Claude Code 的 skills 目录即可被识别。skill 的 `name` 为 `wechat-mp-article-reader`，**目录名需与之一致**：`~/.claude/skills/wechat-mp-article-reader/`。

### 方式 A：让 Agent 自动安装（推荐）

把本仓库的 GitHub 链接发给 Claude Code（或其它支持 skill 的 agent），直接说：

> 帮我安装这个 skill：<仓库链接>

Agent 会 clone 到 skills 目录。等价命令：

```bash
git clone <仓库地址> ~/.claude/skills/wechat-mp-article-reader
```

### 方式 B：下载 zip 手动导入

1. 在仓库 Releases 页下载 zip 并解压。
2. 把解压出来的目录重命名为 `wechat-mp-article-reader`。
3. 移动到 `~/.claude/skills/wechat-mp-article-reader/`。

最终目录结构应为：

```
~/.claude/skills/wechat-mp-article-reader/
├── SKILL.md
├── scripts/fetch_wechat.py
├── references/fallbacks.md
└── ...
```

### 方式 C：git clone

```bash
git clone <仓库地址> ~/.claude/skills/wechat-mp-article-reader
```

### 浏览器兜底（可选）

绝大多数公开文章用 `urllib`（标准库）就能抓到正文，**无需安装任何东西**。少数被拦 / 懒加载严重的页面会用到 playwright：

```bash
pip install playwright && python3 -m playwright install chromium
```

没装也没关系——脚本会自动用 `urllib` 跑，失败时引导你手动另存 HTML 再喂给 `--html`。

### 其它工具

Cursor / Codex / Windsurf 等也可手动适配（把 `SKILL.md` 的约束部分迁移到各自的规则文件），后续会提供更顺滑的安装方式。

> 后续本 skill 会发布到各 skill 平台 / 市场，届时可直接按平台指引一键安装。

---

## 用法

### 作为 Claude Code skill

装好后，直接对 Claude 说：

- "给我读这篇公众号文章：`https://mp.weixin.qq.com/s/xxxx`"
- "总结一下这篇文章：<链接>"

Claude 会自动触发本 skill。

### 作为命令行工具

```bash
# 默认输出 sentinel 区块（标题/账号/作者/日期/正文）
python3 scripts/fetch_wechat.py "https://mp.weixin.qq.com/s/xxxx"

# 结构化 JSON（含 method/body_source，便于溯源）
python3 scripts/fetch_wechat.py "<url>" --format json

# 存成 markdown
python3 scripts/fetch_wechat.py "<url>" --format markdown -o article.md

# 解析本地已存 HTML（不重新下载）
python3 scripts/fetch_wechat.py --html saved.html --format json

# 强制浏览器渲染
python3 scripts/fetch_wechat.py "<url>" --mode browser
```

#### 参数

| 参数 | 说明 |
|---|---|
| `url` | 微信公众号文章链接 |
| `--html <path>` | 解析本地已存 HTML，不重新下载 |
| `--mode {auto,simple,browser}` | 抓取模式，默认 `auto`（simple→过薄则 playwright） |
| `--format {text,json,markdown}` | 输出格式，默认 `text`（sentinel 区块） |
| `--output, -o <path>` | 写入文件而非 stdout |
| `--diag` | JSON 格式下附带诊断字段 |
| `--timeout <秒>` | 网络超时，默认 20 |

---

## 能力边界（不做什么）

- ❌ 登录后才能看的内容、付费墙内容、私信文章
- ❌ 绕过反爬、cookie 抓包、token 接口
- ❌ 图片 OCR（图片为主的文章只总结可见文字并注明）
- ❌ 一次抓多篇文章（避免高频触发反爬，请一篇一篇来）

遇到这些场景，脚本会如实告诉你抓不到，并请你**手动粘贴正文 / 浏览器另存 HTML / 导出 PDF**。

---

## 项目结构

```
wechat-mp-article-reader/
├── SKILL.md                  # skill 定义（Claude Code 读取的入口）
├── scripts/fetch_wechat.py   # 唯一入口：抓取+解析+浏览器兜底+多格式输出
├── references/fallbacks.md   # 浏览器兜底信号与 DOM 提取模板
├── tests/                    # 离线单元测试（纯标准库，无需网络/依赖）
├── README.md                 # 中文（本文件）
├── README.en.md              # 英文（可选翻译）
└── pyproject.toml            # 元数据，核心零依赖，playwright 为可选 extra
```

---

## 测试

离线单元测试，无需任何第三方库、无需网络：

```bash
python3 tests/test_fetch.py
```
