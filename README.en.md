# WeChat MP Article Reader (Claude Code Skill)

A Claude Code skill for reading WeChat official account (公众号) articles. Pure Python standard library — **install and run, zero third-party dependencies**, with optional browser fallback.

Give it an `mp.weixin.qq.com` link and it returns the title, account name, author, publish date, and body — whereas WebFetch / naive scrapers almost always get only a skeleton page.

---

## What problem it solves

WeChat article pages are notoriously hard to scrape:

- **Lazy-loaded / anti-scraping shell**: a plain `curl` or WebFetch often returns only the page skeleton, no body.
- **Non-standard HTML**: lots of inline styles, nested `section`s, implicitly closed tags — regex parsing is brittle.
- **UI noise mixed in**: bottom controls like "Like / Wow / Share / Swipe for next / Scan with WeChat".

This skill uses structured parsing (`html.parser` builds a DOM → locate the content container → drop noise subtrees → segment by block tags → filter noise lines) to handle all of the above, with a `content_noencode` regex-decode fallback when the structured path fails.

---

## Installation

This skill is a directory. Drop it into Claude Code's skills directory and it's recognized. The skill's `name` is `wechat-mp-article-reader`; **the directory name must match**: `~/.claude/skills/wechat-mp-article-reader/`.

### Option A: let an agent install it (recommended)

Send the GitHub repo link to Claude Code (or any skill-aware agent) and say:

> Install this skill: <repo link>

The agent will clone it into the skills directory. Equivalent command:

```bash
git clone <repo-url> ~/.claude/skills/wechat-mp-article-reader
```

### Option B: download zip and import manually

1. Download the zip from the Releases page and unzip.
2. Rename the unzipped directory to `wechat-mp-article-reader`.
3. Move it to `~/.claude/skills/wechat-mp-article-reader/`.

Expected layout:

```
~/.claude/skills/wechat-mp-article-reader/
├── SKILL.md
├── scripts/fetch_wechat.py
├── references/fallbacks.md
└── ...
```

### Option C: git clone

```bash
git clone <repo-url> ~/.claude/skills/wechat-mp-article-reader
```

### Browser fallback (optional)

Most public articles can be fetched with `urllib` (standard library) — **no install needed**. A few blocked / heavily-lazy pages benefit from playwright:

```bash
pip install playwright && python3 -m playwright install chromium
```

If you skip it, the script still runs via `urllib` and, on failure, guides you to manually save the HTML and feed it via `--html`.

> This skill will later be published to various skill platforms / marketplaces for one-click install.

---

## Usage

### As a Claude Code skill

Once installed, just tell Claude:

- "Read this WeChat article: `https://mp.weixin.qq.com/s/xxxx`"
- "Summarize this article: <link>"

Claude will trigger the skill automatically.

### As a CLI

```bash
# Default: sentinel blocks (title/account/author/date/body)
python3 scripts/fetch_wechat.py "https://mp.weixin.qq.com/s/xxxx"

# Structured JSON (with method/body_source for traceability)
python3 scripts/fetch_wechat.py "<url>" --format json

# Save as markdown
python3 scripts/fetch_wechat.py "<url>" --format markdown -o article.md

# Parse a locally saved HTML (no re-download)
python3 scripts/fetch_wechat.py --html saved.html --format json

# Force browser rendering
python3 scripts/fetch_wechat.py "<url>" --mode browser
```

#### Options

| Option | Description |
|---|---|
| `url` | WeChat article URL |
| `--html <path>` | Parse a locally saved HTML file instead of downloading |
| `--mode {auto,simple,browser}` | Fetch mode, default `auto` (simple→playwright if too thin) |
| `--format {text,json,markdown}` | Output format, default `text` (sentinel blocks) |
| `--output, -o <path>` | Write to file instead of stdout |
| `--diag` | Include diagnostic fields in JSON output |
| `--timeout <sec>` | Network timeout, default 20 |

---

## What it does NOT do

- ❌ Login-required content, paywalled content, private-message articles
- ❌ Anti-scraping bypass, cookie capture, token endpoints
- ❌ Image OCR (image-heavy articles only summarize visible text, noted explicitly)
- ❌ Fetching multiple articles at once (to avoid anti-scraping triggers — one at a time)

In these cases the script tells you honestly that it can't fetch, and asks you to **paste the body / save HTML from a browser / export a PDF**.

---

## Project layout

```
wechat-mp-article-reader/
├── SKILL.md                  # skill definition (Claude Code entry)
├── scripts/fetch_wechat.py   # single entry: fetch+parse+browser fallback+multi-format output
├── references/fallbacks.md   # browser fallback signals & DOM extraction templates
├── tests/                    # offline unit tests (stdlib only, no network/deps)
├── README.md                 # Chinese (default)
├── README.en.md              # English (this file, optional translation)
└── pyproject.toml            # metadata; core zero-dep, playwright as optional extra
```

---

## Tests

Offline unit tests — no third-party libraries, no network:

```bash
python3 tests/test_fetch.py
```
