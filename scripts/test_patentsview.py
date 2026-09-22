# -*- coding: utf-8 -*-
"""
test_patentsview.py —— PatentsView 接口最小复现测试（排查 count 全空的问题）
用法：
  Windows PowerShell:
    $env:PATENTSVIEW_KEY = "你的key"
    python test_patentsview.py
  macOS / Linux / Git Bash:
    export PATENTSVIEW_KEY=你的key
    python3 test_patentsview.py

只发一条请求，把完整的原始响应（状态码 + body）打印出来，
不像 collect_all.py 里那样直接 .get("total_hits","") 悄悄吞掉异常情况。
"""
import json
import os

import requests

KEY = os.environ.get("PATENTSVIEW_KEY")
if not KEY:
    raise SystemExit("先设置 PATENTSVIEW_KEY 环境变量（见文件顶部用法），再运行。")

q = json.dumps({"assignees.assignee_country": "HK"})
o = json.dumps({"size": 1})

r = requests.get(
    "https://search.patentsview.org/api/v1/patent/",
    params={"q": q, "o": o},
    headers={"X-Api-Key": KEY},
    timeout=60,
)

print("status_code:", r.status_code)
print("response headers (部分):", {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "x-status-reason", "x-ratelimit-remaining")})
print("body (前1000字符):")
print(r.text[:1000])
