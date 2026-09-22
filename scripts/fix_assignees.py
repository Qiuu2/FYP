# -*- coding: utf-8 -*-
"""从 raw/patents_families_raw.csv 重算申请人家族数（按 city×family_id 去重），
覆盖 BigQuery 查询3 的输出。查询3 的 families 列是「产业×城市×家族」行次，
跨产业家族被重复计（v4 修了查询1，查询3 漏改）。"""
import csv, collections, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
src = ROOT / "raw" / "patents_families_raw.csv"
dst = ROOT / "raw" / "patents_assignees.csv"
rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
cnt, seen = collections.Counter(), set()
for r in rows:
    k = (r["city"], r["family_id"])
    if k in seen:
        continue
    seen.add(k)
    for nm in r["assignees"].split(" | "):
        nm = nm.strip()
        if nm:
            cnt[(r["city"], nm)] += 1
with open(dst, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["city", "assignee", "families"])
    for (c, n), v in sorted(cnt.items(), key=lambda x: (x[0][0], -x[1], x[0][1])):
        w.writerow([c, n, v])
hk = sum(v for k, v in cnt.items() if k[0] == "hk")
sg = sum(v for k, v in cnt.items() if k[0] == "sg")
print(f"✅ 写出 {dst.name}：{len(cnt)} 行；家族次合计 hk={hk} sg={sg}")
print(f"   去重家族数 hk={len({k[1] for k in seen if k[0]=='hk'})} "
      f"sg={len({k[1] for k in seen if k[0]=='sg'})}")
