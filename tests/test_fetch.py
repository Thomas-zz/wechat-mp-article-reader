#!/usr/bin/env python3
"""fetch_wechat.py 的离线单元测试（纯标准库，无需 lxml/bs4/network）。

运行：
  python3 tests/test_fetch.py
  python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_wechat  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sample.html"
SCRIPT = ROOT / "scripts" / "fetch_wechat.py"


class ParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = FIXTURE.read_text(encoding="utf-8")
        cls.article = fetch_wechat.parse_html(cls.raw, requested_url=None, method="html")

    def test_title(self):
        self.assertEqual(self.article.title, "样例公众号文章标题")

    def test_account(self):
        self.assertEqual(self.article.account, "样例公众号")

    def test_author(self):
        self.assertEqual(self.article.author, "样例作者")

    def test_publish_time(self):
        # 1717430400 = 2024-06-04 00:00:00 UTC，本地时区日期应为 2024-06-04（东八区 08:00）
        self.assertRegex(self.article.publish_time, r"^2024-06-04 ")

    def test_biz(self):
        self.assertEqual(self.article.biz, "Mzg5MDAwMDAwMA==")

    def test_content_has_body(self):
        self.assertIn("这是第一段正文。", self.article.content)
        self.assertIn("这是第二段正文，包含更完整的内容。", self.article.content)
        self.assertIn("这是一段引用。", self.article.content)

    def test_content_filters_noise(self):
        self.assertNotIn("继续滑动看下一个", self.article.content)
        self.assertNotIn("微信扫一扫", self.article.content)

    def test_ok_flag(self):
        self.assertTrue(self.article.ok)


class NoencodeFallbackTest(unittest.TestCase):
    def test_noencode_extraction(self):
        # 结构化容器缺失时，应走 content_noencode 兜底
        encoded = "\\u8fd9\\u662f\\u901a\\u8fc7 noencode \\u63d0\\u53d6\\u7684\\u6b63\\u6587"
        raw = f"<html><script>var content_noencode = '{encoded}';</script></html>"
        body = fetch_wechat.extract_body_via_noencode(raw)
        self.assertIn("noencode", body)


class CLITest(unittest.TestCase):
    def _run(self, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "scripts"))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, env=env, timeout=30,
        )
        return result

    def test_json_output_is_valid(self):
        r = self._run("--html", str(FIXTURE), "--format", "json")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["title"], "样例公众号文章标题")
        self.assertEqual(data["account"], "样例公众号")
        self.assertEqual(data["method"], "html")
        self.assertTrue(data["ok"])

    def test_sentinel_output(self):
        r = self._run("--html", str(FIXTURE))
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("===TITLE===", r.stdout)
        self.assertIn("===BODY===", r.stdout)
        self.assertIn("这是第一段正文。", r.stdout)

    def test_markdown_output(self):
        r = self._run("--html", str(FIXTURE), "--format", "markdown")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertTrue(r.stdout.startswith("---"))
        self.assertIn("# 样例公众号文章标题", r.stdout)

    def test_missing_arg(self):
        r = self._run()
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
