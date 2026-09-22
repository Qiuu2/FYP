# -*- coding: utf-8 -*-
"""把金融科技牌照事件流转成【累计存量】季度序列。

附录 A 指标 9 口径：
    「金融科技：虚拟银行、储值支付、虚拟资产平台等牌照（累计存量口径，防稀疏脉冲）」

为什么必须是累计存量：事件流在 2015/2017/2018/2021/2023 全空，
2016 一年 13 件、2019 一年 10 件——这种稀疏脉冲序列做同比增长率会炸
（除零、无穷大），也无法进 4.5 步骤③的交叉相关。累计存量是单调的，
增长率有定义，且「持牌机构数」本身才是 IDI·创新想测的存量概念。

输入：clean/fintech_license_events.csv   date,entity,event_type,date_type,source_url
输出：clean/fintech_licenses_by_quarter.csv
      industry,city,quarter,licenses_cumulative,new_this_quarter

口径决定（都写进 prov）：
  · 窗口 2015Q1–2024Q4（40 期），与 papers/clinicaltrials 对齐
  · 窗口外事件的处理：2015 年之前无事件；2025 起的 6 件【剔除】，
    因为它们落在研究窗口之外，计入会让 2024Q4 的存量虚高
  · city 固定 hk：4.5 步骤②明确「新加坡侧仅使用双城对称的数据源
    （OpenAlex、GitHub、专利）」，牌照是港侧单边指标
  · industry 固定 fintech：附录 A 该指标只覆盖金融科技与生物医药，
    生物医药那半是临床试验（已在 clinicaltrials_by_quarter.csv）
"""
import csv, collections, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC  = ROOT / "clean" / "fintech_license_events.csv"
DST  = ROOT / "clean" / "fintech_licenses_by_quarter.csv"
PROV = ROOT / "clean" / "fintech_licenses_by_quarter.csv.prov.json"
QUARTERS = [f"{y}Q{q}" for y in range(2015, 2025) for q in range(1, 5)]   # 40 期

def to_q(d):
    y, m = int(d[:4]), int(d[5:7])
    return f"{y}Q{(m - 1) // 3 + 1}"

if not SRC.exists():
    sys.exit(f"⛔ 找不到 {SRC}")
rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
print(f"读入 {len(rows)} 条牌照事件")

inwin, before, after = [], [], []
for r in rows:
    q = to_q(r["date"])
    (inwin if q in QUARTERS else (before if r["date"] < "2015" else after)).append(r)
print(f"  窗口内 {len(inwin)}；窗口前 {len(before)}（计入期初存量）；窗口后 {len(after)}（剔除）")
if after:
    print("  剔除的窗口外事件：")
    for r in sorted(after, key=lambda x: x["date"]):
        print(f"     {r['date']}  {r['event_type']:12s} {r['entity'][:46]}")

new = collections.Counter(to_q(r["date"]) for r in inwin)
base = len(before)
out, cum = [], base
for q in QUARTERS:
    cum += new[q]
    out.append(["fintech", "hk", q, cum, new[q]])

DST.parent.mkdir(parents=True, exist_ok=True)
with open(DST, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["industry", "city", "quarter", "licenses_cumulative", "new_this_quarter"])
    w.writerows(out)

# 自检
assert len(out) == 40, f"应为 40 期，实为 {len(out)}"
cums = [r[3] for r in out]
assert cums == sorted(cums), "累计存量必须单调不减"
assert cums[-1] == base + len(inwin), f"期末存量 {cums[-1]} ≠ 期初 {base} + 窗口内 {len(inwin)}"
byt = collections.Counter(r["event_type"] for r in inwin)

print(f"\n✅ {DST.relative_to(ROOT).as_posix()}：40 行")
print(f"   期初存量 {base} → 期末存量 {cums[-1]}（窗口内新增 {len(inwin)}）")
print(f"   按类型：{dict(byt)}")
print(f"   单调不减 ✅　｜　空季度 {sum(1 for r in out if r[4] == 0)} 个（存量口径下不是缺失）")

json.dump({
    "manifests": ["p4_fintech_licenses.txt.manifest.json"],
    "script": "scripts/licenses_build.py",
    "source": "clean/fintech_license_events.csv",
    "method": "事件流→累计存量季度序列（附录A指标9「累计存量口径，防稀疏脉冲」）",
    "window": "2015Q1-2024Q4（40期）",
    "excluded_out_of_window": [{"date": r["date"], "entity": r["entity"],
                                "event_type": r["event_type"]} for r in sorted(after, key=lambda x: x["date"])],
    "scope_notes": "city=hk 单边（4.5步骤②：新加坡侧仅用双城对称源）；industry=fintech（指标9的生物医药半边为临床试验）",
    "created_utc": "2026-08-31T00:00:00+00:00",
}, open(PROV, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"   prov → {PROV.name}")
