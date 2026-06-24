# 浏览器兜底信号与渲染态提取

## 什么时候需要浏览器

- urllib（simple 模式）拿到的正文明显过薄，或命中拦截标记（"当前环境异常" / "访问过于频繁" / "网页包含敏感内容" 等）。
- 页面是安全页、挑战页、或非文章壳页面。
- 内容靠懒加载，curl 拿不到。
- 用户需要基于真实渲染页面做核验。

脚本 `--mode auto` 会自动在 simple 拿不到足够正文时切到 playwright（若已安装）。`--mode browser` 可强制走浏览器。

## 浏览器中的快速校验信号

- 可见的文章 H1 加上多段正文，比浏览器标签页标题更能说明页面已正确加载。标签页标题仍可能只是 `微信公众平台`。
- 顶部附近出现作者、日期、地点或 `原创` 等标记时，通常说明正文已加载。
- 底部出现 `赞`、`分享`、`在看`、`留言`、`上一篇`、`下一篇` 这类控件时，可视为文章结束标记。

## 推荐的浏览器提取顺序

1. 先拿整页 DOM 快照 / `page.content()`。
2. 再用作用域限定在疑似正文容器内的 `page.evaluate()` 提取。
3. 如果内容像是被截断了，先滚动，再重新抓一份。
4. 截图只用于验证页面实际渲染了什么，或说明不确定性。

## 常见正文容器候选

- `#js_content`
- `#js_article_content`
- `#img-content`
- `.rich_media_content`
- `article`
- `main`
- 最后才退回到 `body`

## 紧凑提取模板

```js
const article = await page.evaluate(() => {
  const pick = (selector) =>
    document.querySelector(selector)?.innerText?.trim() || "";

  const root =
    document.querySelector("#js_content") ||
    document.querySelector("#img-content") ||
    document.querySelector(".rich_media_content") ||
    document.querySelector("article") ||
    document.querySelector("main") ||
    document.body;

  const title =
    pick("h1") ||
    pick(".rich_media_title") ||
    pick("#activity-name");

  const meta =
    pick(".rich_media_meta_list") ||
    pick("#meta_content") ||
    pick("[class*='meta']");

  return {
    title,
    meta,
    body: root.innerText.trim(),
  };
});
```

## 清洗建议

- 优先保留 `上一篇`、`下一篇`、`赞`、`分享`、`在看`、`留言` 这些底部标记之前的文本。
- 如果文章以图片为主、文字很少，就总结可见文字，并注明图片没有做 OCR。
- 如果快照已经足够干净完整，就不要再用更宽泛的 `body.innerText` 覆盖它。

## 手动另存 HTML 的兜底

当 playwright 不可用、或自动抓取失败时，最可靠的兜底是让用户在浏览器里打开原文，手动另存为 `.html`，然后：

```bash
python3 scripts/fetch_wechat.py --html saved.html --format json
```

这种方式不依赖任何抓取环境，能处理绝大多数可见页面。
