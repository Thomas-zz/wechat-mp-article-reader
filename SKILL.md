---
name: wechat-mp-article-reader
description: "读取微信公众号文章正文。**当用户提供 mp.weixin.qq.com / weixin.qq.com 文章链接时立即使用**，不要先试 WebFetch（公众号对 WebFetch 几乎必失败）。支持提取标题、账号、作者、发布日期、正文，并可输出 Markdown/JSON。也用于：通用抓取只拿到壳页面 / 安全验证页 / 懒加载内容不全 / 用户主动要求把公众号文章保存为 markdown 时。**不要**用于：登录后内容、付费内容、私信、要求绕过反爬的场景。"
---

# 微信公众号文章读取器

## 何时触发

- 用户给出 `https://mp.weixin.qq.com/s/...` 或 `https://weixin.qq.com/...` 链接
- 用户说"这篇公众号文章 / 微信文章 / 推文 / 文章链接"
- WebFetch 返回的公众号页面只有标题、缺正文、出现安全验证提示
- 用户要把公众号文章保存为 markdown

## 快速流程

```bash
python3 scripts/fetch_wechat.py "<url>"
```

默认输出这些 sentinel 区块（直接基于 `===BODY===` 总结，**不要重新抓取**）：

- `===TITLE===`
- `===ACCOUNT===`
- `===AUTHOR===`
- `===DATE===`
- `===BODY===`

其它格式：

```bash
python3 scripts/fetch_wechat.py "<url>" --format json        # 结构化，含 method/body_source 便于溯源
python3 scripts/fetch_wechat.py "<url>" --format markdown -o article.md   # 存盘
```

## 失败处理

脚本 `--mode auto`（默认）会自动决定：urllib 抓取 → 若正文过薄或命中拦截标记 → 自动切 playwright（如已安装）。仍失败时输出 `NO_CONTENT` 并提示。此时：

1. **手动另存 HTML 再喂给脚本**：在浏览器打开原文，另存为 `.html`，然后：
   ```bash
   python3 scripts/fetch_wechat.py --html saved.html --format json
   ```
2. **安装 playwright 后重试**：
   ```bash
   pip install playwright && python3 -m playwright install chromium
   ```

若两种都不行（如付费墙、登录后、私信文章），如实告诉用户当前页面无法自动读取，请他提供粘贴正文 / 导出 HTML / PDF。

## 浏览器兜底（高级）

当需要基于真实渲染页面核验时，可强制浏览器模式：

```bash
python3 scripts/fetch_wechat.py "<url>" --mode browser
```

浏览器中可用的核验信号与精确提取选择器见 [references/fallbacks.md](references/fallbacks.md)。

## 强约束（必须遵守）

- **不要用 WebFetch / Read 直接抓原始公众号 HTML** — 经常是单行 + 反爬壳，浪费 token 必失败
- **不要重复抓同一个 URL** — 复用已有 HTML（`--html`）或上一次的输出
- **不要在搜索引擎、镜像站、转载页试** — 用户给的是原始链接就用原始链接
- **不要调用 cookie 抓包、token 接口、Fiddler 类流程** — 不在 skill 范围内
- **不要尝试登录后内容、付费墙、私信文章** — 如实告诉用户无法自动读取
- **一次只读一篇文章** — 避免高频触发反爬

## 输出要求

- 总结时带**标题、账号、作者、发布日期**（脚本已给，复制即可）
- 区分"原文事实"和"基于上下文的推断"
- 可靠性敏感场景下，**注明来源是快路径（simple）还是浏览器兜底（browser）**——`json` 输出的 `method` 字段会告诉你
- 只看到部分内容时**明确说明**，不要装作看完整篇
- 用户问"怎么拿到的"时，如实说明路径（urllib / playwright / 手动另存 HTML）

## 安装（给安装者看）

本 skill 安装到 Claude Code 的 skills 目录后即可被识别。skill 的 `name` 字段为 `wechat-mp-article-reader`，需放置在 `~/.claude/skills/wechat-mp-article-reader/`（目录名与 `name` 一致）。详见 README.md 的"安装"一节。
