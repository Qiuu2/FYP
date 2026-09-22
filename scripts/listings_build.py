# -*- coding: utf-8 -*-
"""指标 11 · 18A/18C 上市事件 → 季度序列

输入：raw/p3_hkex_listings.txt（每条带上市日期）
输出：clean/listings_by_quarter.csv

【产业归属】
    18A（生物科技章节）→ biomed
    18C（特专科技章节）→ ai
    金融科技无对应上市章节 —— 该产业的商业维只能靠指标 10

【geo_rule（提案附录 B）】
    「仅计在香港有实质运营或研发的实体；『上市地功能』单列为稳健性口径」
    ⚠️ 本脚本只产出【上市地功能口径】。实质运营口径需要逐家判定公司总部与研发地，
       属人工核查，不由脚本臆断（R1：零虚构）。
       判定结果应写入 config/listings_geo_review.csv，本脚本再据此出第二条曲线。
"""
import csv, re, json, pathlib, collections, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "raw" / "p3_hkex_listings.txt"
DST = ROOT / "clean" / "listings_by_quarter.csv"
GEO = ROOT / "config" / "listings_geo_review.csv"
QUARTERS = [f"{y}Q{q}" for y in range(2015, 2025) for q in range(1, 5)]

txt = SRC.read_text(encoding="utf-8")

def q_of(y, m):
    return f"{y}Q{(m - 1) // 3 + 1}"

events = []          # (industry, quarter, year, name, date_iso)

# ── 18C：名称,d/m/yyyy,募资,来源 ──────────────────────────
sec = txt.split("=== TABLE: listings_18c ===")[1].split("===")[0]
for line in sec.splitlines():
    m = re.match(r"^([^,]+),(\d{1,2})/(\d{1,2})/(\d{4}),", line.strip())
    if m:
        name, d, mo, y = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        events.append(("ai", q_of(y, mo), y, name.strip(), f"{y}-{mo:02d}-{d:02d}"))
n18c = len(events)

# ── 18A：名称,代码,yyyy-mm-dd，以 ｜ 分隔 ─────────────────
sec = txt.split("=== TABLE: listings_18a ===")[1].split("=== 争议")[0]
for chunk in sec.replace("\n", "｜").split("｜"):
    m = re.match(r"^\s*([^,]+),(\d{3,5}),(\d{4})-(\d{2})-(\d{2})", chunk.strip())
    if m:
        name, y, mo, d = m.group(1), int(m.group(3)), int(m.group(4)), int(m.group(5))
        events.append(("biomed", q_of(y, mo), y, name.strip(), f"{y}-{mo:02d}-{d:02d}"))
n18a = len(events) - n18c
print(f"解析：18C {n18c} 家 · 18A {n18a} 家 · 合计 {len(events)} 家")

# 窗口过滤
inwin = [e for e in events if e[1] in QUARTERS]
print(f"落在 2015Q1–2024Q4 窗口内：{len(inwin)} 家（窗口外 {len(events)-len(inwin)} 家已剔除）")

# 交叉验证：18A 逐年计数应与 clean/listings_18a_by_year.csv 一致
yr = collections.Counter(e[2] for e in events if e[0] == "biomed")
ok = True
for r in csv.DictReader(open(ROOT / "clean" / "listings_18a_by_year.csv", encoding="utf-8-sig")):
    y, c = int(r["year"]), int(r["count"])
    if yr[y] != c:
        print(f"  ⛔ 18A {y} 年：明细 {yr[y]} vs 年度表 {c}"); ok = False
print(f"  ↳ 18A 逐年交叉验证：{'✅ 全部一致' if ok else '⛔ 有不一致'}")

# ── geo_rule 第二口径（若已有人工判定表）────────────────
geo = {}
if GEO.exists():
    all_rows = list(csv.DictReader(open(GEO, encoding="utf-8-sig")))
    judged = {r["name"].strip(): (r.get("hk_substantive") or "").strip()
              for r in all_rows if (r.get("hk_substantive") or "").strip()}
    print(f"  ↳ 判定表 {len(all_rows)} 家，其中已填判定 {len(judged)} 家")
    # ⚠️ 只有【全部判完】才出实质运营口径。
    #    半填的表会让未判定的家算成 0，产出一条看起来像结论的假序列
    #    （「香港只有 0 家在港有实质研发」）——那不是结果，是空白。
    if len(judged) == len(all_rows) and all_rows:
        geo = judged
        print(f"  ↳ ✅ 判定已齐，本次同出【实质运营口径】")
    elif judged:
        print(f"  ↳ ⚠️ 判定未填完（{len(judged)}/{len(all_rows)}），"
              f"本次仍只出【上市地功能口径】；填满后重跑即自动多出一条")
    else:
        print(f"  ↳ ⚠️ 判定列全空，本次只出【上市地功能口径】")
else:
    print(f"  ⚠️ 未找到 {GEO.name} —— 只出【上市地功能口径】一条曲线；"
          f"实质运营口径待人工判定")

# ── 落盘 ─────────────────────────────────────────────
cnt = collections.Counter((e[0], e[1]) for e in inwin)
cnt_sub = collections.Counter((e[0], e[1]) for e in inwin if geo.get(e[3]) == "1")
rows, cum = [], collections.Counter()
for ind in ("ai", "biomed"):
    c = 0
    for q in QUARTERS:
        n = cnt[(ind, q)]; c += n
        rows.append([ind, "hk", q, n, c,
                     cnt_sub[(ind, q)] if geo else "",
                     "listing_venue"])
DST.parent.mkdir(exist_ok=True)
with open(DST, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["industry", "city", "quarter", "new_listings", "cumulative",
                "new_listings_hk_substantive", "geo_scope"])
    w.writerows(rows)
json.dump({
    "manifests": ["p3_hkex_listings.txt.manifest.json"],
    "script": "scripts/listings_build.py",
    "method": "指标11·IDI商业：18A→biomed、18C→ai，按上市日期切季度；同出当期新增与累计",
    "geo_rule_note": "本文件为【上市地功能口径】。提案附录 B 要求另出【实质运营口径】，"
                     "需逐家判定总部与研发地，属人工核查，未由脚本臆断",
    "coverage_note": "金融科技无对应上市章节；新加坡侧无对称源（提案 §4.5 已声明上市口径不对称）",
    "created_utc": "2026-09-12T00:00:00+00:00",
}, open(str(DST) + ".prov.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n✅ clean/{DST.name}  {len(rows)} 行")
for ind in ("ai", "biomed"):
    v = [r[3] for r in rows if r[0] == ind]
    nz = [(QUARTERS[i], v[i]) for i in range(len(v)) if v[i]]
    print(f"   {ind:7s} 窗口内 {sum(v):>3} 家，首个非零 {nz[0][0] if nz else '—'}，"
          f"末期累计 {rows[[r[0] for r in rows].index(ind) + 39][4]}")
