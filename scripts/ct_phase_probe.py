# -*- coding: utf-8 -*-
r"""
ct_phase_probe.py —— 查清 ClinicalTrials.gov 的 phase 分项为什么加不满总数

背景（2026-09-18，賈贇 J4 第二步实测）：
    2024Q1 香港：总数 109，但分项 early_phase1 1 + phase1 1 + phase2 7 +
    phase3 12 + phase4 1 + NA 73 = 95，**差 14 个**。
    （順带：EARLY_PHASE1 是任务单漏列的取值，賈贇自己找出来的。）

    差额的两种可能，靠逐条 count 分不出来，必须把原始记录拉回来看：
      (a) phases 是**多值字段**（例如 ["PHASE1","PHASE2"]），
          而 AREA[Phase]PHASE1 只匹配单值 → 组合期别的试验两边都没被数到
      (b) 有些试验**根本没有 phases 字段**（既不是 NA，也不是任何 phase）

    本脚本一次把该季度全部记录拉回来，直接统计 phases 的真实取值组合。

用法（在你自己的机器上，仓库根目录）：
    python scripts\ct_phase_probe.py                      # 默认 hk / 2024Q1
    python scripts\ct_phase_probe.py --cc sg --q 2019Q3

调用量：1–2 次（一页 200 条，够装下一个季度）。
R1：只读、只打印，不写任何文件。
"""
import argparse, collections, json, sys
import requests

ap = argparse.ArgumentParser()
ap.add_argument("--cc", default="hk", choices=["hk", "sg"])
ap.add_argument("--q", default="2024Q1")
args = ap.parse_args()

TERM = {"hk": "Hong Kong", "sg": "Singapore"}[args.cc]
y, qn = int(args.q[:4]), int(args.q[-1])
d0 = f"{y}-{3*(qn-1)+1:02d}-01"
d1 = [f"{y}-03-31", f"{y}-06-30", f"{y}-09-30", f"{y}-12-31"][qn-1]
flt = f"AREA[StudyFirstPostDate]RANGE[{d0},{d1}]"

print(f"{args.cc}/{args.q}　filter = {flt}\n")

studies, token, pages = [], None, 0
while True:
    p = {"query.locn": TERM, "filter.advanced": flt, "pageSize": 200, "countTotal": "true"}
    if token:
        p["pageToken"] = token
    r = requests.get("https://clinicaltrials.gov/api/v2/studies", params=p, timeout=60)
    r.raise_for_status()
    j = r.json()
    if pages == 0:
        total = j.get("totalCount")
        print(f"totalCount = {total}")
    studies += j.get("studies", [])
    pages += 1
    token = j.get("nextPageToken")
    if not token or pages > 10:
        break
print(f"实际取回 {len(studies)} 条（{pages} 页）\n")

c = collections.Counter()
for s in studies:
    dm = (s.get("protocolSection") or {}).get("designModule") or {}
    ph = dm.get("phases")
    c[tuple(ph) if ph else ("<没有 phases 字段>",)] += 1

print("=== phases 字段的真实取值组合 ===")
for k, v in c.most_common():
    print(f"  {v:4d}  {' | '.join(k)}")

single = sum(v for k, v in c.items() if len(k) == 1 and not k[0].startswith("<"))
multi = sum(v for k, v in c.items() if len(k) > 1)
missing = sum(v for k, v in c.items() if k[0].startswith("<"))
print(f"\n单值 {single} · 多值组合 {multi} · 无字段 {missing} · 合计 {single+multi+missing}")

print("\n=== 判读 ===")
if multi:
    print(f"→ 有 {multi} 条是**多值组合**。AREA[Phase]PHASEn 若只匹配单值，"
          f"这些就是分项加不满总数的原因之一。")
if missing:
    print(f"→ 有 {missing} 条**根本没有 phases 字段**（不是 NA）。"
          f"这些用任何 AREA[Phase]xxx 都筛不到。")
if not multi and not missing:
    print("→ 全是单值且都有字段，那么差额另有原因，把上面整段发回来一起看。")
print("\n把以上整段输出原样粘回给组长。")
