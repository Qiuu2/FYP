# -*- coding: utf-8 -*-
r"""
test_patentsview_v2.py —— PatentsView 根因判定测试（一次跑完，直接给结论）

用法：
  Windows PowerShell（在 C:\FYP\data_repo\scripts 目录下）：
    $env:PATENTSVIEW_KEY = "你的真实key"
    python test_patentsview_v2.py

与 v1 的区别：v1 只发一条 GET，拿到结果还得人工判断；v2 一次发 5 条探针，
覆盖两个假设（key类型 / GET-vs-POST）并自动打印判定结论。
全程不打印 key 原文，只打印长度和指纹，输出可以直接贴回对话。
"""
import hashlib
import json
import os
import sys

import requests

URL = "https://search.patentsview.org/api/v1/patent/"
KEY = os.environ.get("PATENTSVIEW_KEY")
if not KEY:
    raise SystemExit("先设置 PATENTSVIEW_KEY 环境变量（PowerShell: $env:PATENTSVIEW_KEY=\"...\"），再运行。")

print("=" * 72)
print("PatentsView 根因判定测试 v2")
print(f"key 长度: {len(KEY)}   指纹(sha256前8): {hashlib.sha256(KEY.encode()).hexdigest()[:8]}")
print(f"requests {requests.__version__} / python {sys.version.split()[0]}")
print("=" * 72)

Q_SIMPLE = {"assignees.assignee_country": "HK"}
Q_YEAR = {"_and": [{"assignees.assignee_country": "HK"},
                   {"_gte": {"patent_date": "2020-01-01"}},
                   {"_lte": {"patent_date": "2020-12-31"}}]}
O_ONE = {"size": 1}
F_MIN = ["patent_id", "patent_date"]

results = {}


def probe(name, method, q, o=None, f=None, with_key=True):
    headers = {"X-Api-Key": KEY} if with_key else {}
    try:
        if method == "GET":
            params = {"q": json.dumps(q)}
            if o:
                params["o"] = json.dumps(o)
            if f:
                params["f"] = json.dumps(f)
            r = requests.get(URL, params=params, headers=headers, timeout=60)
        else:
            body = {"q": q}
            if o:
                body["o"] = o
            if f:
                body["f"] = f
            headers["Content-Type"] = "application/json"
            r = requests.post(URL, json=body, headers=headers, timeout=60)
    except Exception as e:
        print(f"\n--- [{name}] {method} ---")
        print(f"  请求异常: {type(e).__name__}: {e}")
        results[name] = {"status": None, "total_hits": None, "err": type(e).__name__}
        return

    hits = None
    parsed_keys = None
    try:
        j = r.json()
        if isinstance(j, dict):
            parsed_keys = sorted(j.keys())
            hits = j.get("total_hits")
    except Exception:
        pass

    print(f"\n--- [{name}] {method} ---")
    print(f"  status_code : {r.status_code}")
    print(f"  elapsed     : {r.elapsed.total_seconds():.2f}s")
    print(f"  content-type: {r.headers.get('Content-Type')}")
    print(f"  x-status-reason: {r.headers.get('X-Status-Reason')}")
    print(f"  json keys   : {parsed_keys}")
    print(f"  total_hits  : {hits!r}")
    print(f"  body (前1200字符):")
    print("  " + r.text[:1200].replace("\n", "\n  "))
    results[name] = {"status": r.status_code, "total_hits": hits, "keys": parsed_keys}


probe("A-GET-带key-简单q", "GET", Q_SIMPLE, O_ONE)
probe("B-GET-不带key", "GET", Q_SIMPLE, O_ONE, with_key=False)
probe("C-POST-带key-简单q", "POST", Q_SIMPLE, O_ONE)
probe("D-GET-带key-显式f", "GET", Q_SIMPLE, O_ONE, F_MIN)
probe("E-GET-带key-collect_all原查询(2020)", "GET", Q_YEAR, O_ONE)

print("\n" + "=" * 72)
print("汇总")
print("=" * 72)
for k, v in results.items():
    print(f"  {k:34s} status={str(v.get('status')):5s} total_hits={v.get('total_hits')!r}")

A, B, C, E = results.get("A-GET-带key-简单q", {}), results.get("B-GET-不带key", {}), \
    results.get("C-POST-带key-简单q", {}), results.get("E-GET-带key-collect_all原查询(2020)", {})

print("\n判定：")
if A.get("status") == 200 and isinstance(A.get("total_hits"), int):
    if isinstance(E.get("total_hits"), int) and E["total_hits"] > 0:
        print("  → key 有效、GET 有效、collect_all 的查询语法也有效。")
        print("  → 说明 v5.4 的 mod_patentsview() 现在能跑通；同学那份全空的 CSV 是旧版脚本产出的历史遗留，重跑即可。")
    elif E.get("total_hits") == 0:
        print("  → key 与接口都正常，但 collect_all 的 _and/_gte/_lte 逐年查询返回 0 → 问题在查询语法（日期过滤），需要改查询而不是改认证。")
    else:
        print("  → 简单查询正常但逐年查询异常，看 E 的 body 定位。")
elif A.get("status") in (401, 403):
    if B.get("status") in (401, 403) and A["status"] == B["status"]:
        print("  → 带 key 和不带 key 返回同样的拒绝码 → key 根本没被接受（假设①：key 类型/失效问题成立）。")
    else:
        print("  → 带 key 被拒、不带 key 表现不同 → key 被识别但无权限，仍属假设①。")
    print("  → 需要在 PatentsView / USPTO 账号页确认这把 key 的状态并重新申请。")
elif A.get("status") != 200 and C.get("status") == 200:
    print("  → GET 失败但 POST 成功 → 假设②成立，mod_patentsview() 改用 POST + JSON body。")
else:
    print("  → 不落在预设分支，把上面完整输出贴回对话由 Claude 判读。")
print("=" * 72)
