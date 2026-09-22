# -*- coding: utf-8 -*-
"""指标 1 · 从 (作者,季度) 底稿算三年滚动窗口的唯一作者数

附录 A：近三年在港机构署名发文的【唯一作者数】（滚动窗口）

滚动窗口定义（须与方法章一致）：
    W(t) = 以季度 t 为右端点、向前回溯 12 个季度（含 t）的闭窗
    指标(t) = 在 W(t) 内至少发表过一次的唯一作者数

    ⚠️ 前 11 个季度（2015Q1–2015Q4 … 2017Q3）窗口不完整——
       它们只能回溯到 2015Q1，实际窗口长度 < 12 期，值会系统性偏低。
       本脚本照实输出并标记 window_full=False，【不做任何填补】。
       方法章须声明：先行检验只使用 window_full=True 的 2017Q4 起 29 期。

输入：raw/openalex_author_quarters.csv
输出：clean/researchers_stock_by_quarter.csv
      industry,city,quarter,unique_authors,new_authors,window_full
"""
import csv, collections, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "raw" / "openalex_author_quarters.csv"
DST = ROOT / "clean" / "researchers_stock_by_quarter.csv"
PROV = ROOT / "clean" / "researchers_stock_by_quarter.csv.prov.json"

QUARTERS = [f"{y}Q{q}" for y in range(2015, 2025) for q in range(1, 5)]   # 40 期
WINDOW = 12          # 三年 = 12 个季度

if not SRC.exists():
    sys.exit(f"⛔ 找不到 {SRC}\n   先跑 python scripts/collect_authors.py --all")

# (industry, city, quarter) -> set(author_id)
# by_loc = 主口径（作者本人挂本地机构）；by_all = 全作者口径（含国际合著者，稳健性用）
by = collections.defaultdict(set)          # 主口径
by_all = collections.defaultdict(set)      # 稳健性口径
n_rows = 0
HAS_LOCAL = None
for r in csv.DictReader(open(SRC, encoding="utf-8-sig")):
    if HAS_LOCAL is None:
        HAS_LOCAL = "is_local" in r
        if not HAS_LOCAL:
            print("⛔ 底稿没有 is_local 列——这是 2026-09-07 之前的旧版底稿，")
            print("   它把整篇论文的全部作者（含国际合著者）都算成了本地研究者。")
            print("   请先跑 scripts/collect_openalex_master.py --all 重采，再跑本脚本。")
            sys.exit(1)
    k = (r["industry"], r["city"], r["quarter"])
    by_all[k].add(r["author_id"])
    if r["is_local"] == "1":
        by[k].add(r["author_id"])
    n_rows += 1
print(f"读入 {n_rows:,} 行；本地署名 {sum(len(v) for v in by.values()):,} / "
      f"全部 {sum(len(v) for v in by_all.values()):,}")

units = sorted({(k[0], k[1]) for k in by})
print(f"单元 {len(units)} 个：{units}")

bad_q = {k[2] for k in by} - set(QUARTERS)
if bad_q:
    sys.exit(f"⛔ 出现窗口外季度：{sorted(bad_q)}")

rows = []
for ind, city in units:
    seen_ever = set()                      # 用于算 new_authors
    for i, q in enumerate(QUARTERS):
        lo = max(0, i - WINDOW + 1)
        win = QUARTERS[lo:i + 1]
        authors, authors_all = set(), set()
        for wq in win:
            authors |= by.get((ind, city, wq), set())
            authors_all |= by_all.get((ind, city, wq), set())
        cur = by.get((ind, city, q), set())
        new = len(cur - seen_ever)
        seen_ever |= cur
        # new_authors 左截断：2015Q1 之前的历史完全没有，故 2015 年前后的
        # new_authors 把"老作者首次出现在样本里"误记为新人。只在 2018Q1 起可用。
        new_ok = (i >= 12)
        rows.append([ind, city, q, len(authors), len(authors_all),
                     new, new_ok, len(win) == WINDOW])

DST.parent.mkdir(parents=True, exist_ok=True)
with open(DST, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["industry", "city", "quarter", "unique_authors",
                "unique_authors_allauthors", "new_authors", "new_authors_usable",
                "window_full"])
    w.writerows(rows)

# ── 自检 ──
exp = len(units) * len(QUARTERS)
assert len(rows) == exp, f"行数 {len(rows)} ≠ 期望 {exp}"
full = [r for r in rows if r[7]]
print(f"\n✅ {DST.relative_to(ROOT).as_posix()}  {len(rows)} 行 = {len(units)} 单元 × {len(QUARTERS)} 期")
print(f"   window_full=True 的期数：{len(full)//len(units)}（2017Q4 起），"
      f"先行检验只能用这一段")

# 单调性提示：滚动存量不应剧烈跳变
print(f"\n各单元 window_full 段的存量区间：")
for ind, city in units:
    v = [r[3] for r in rows if r[0] == ind and r[1] == city and r[7]]
    va = [r[4] for r in rows if r[0] == ind and r[1] == city and r[7]]
    if v:
        print(f"   {ind:11s} {city}   {min(v):>6,} – {max(v):>6,}   末期 {v[-1]:>6,}"
              f"   ｜全作者口径末期 {va[-1]:>7,}（膨胀 {va[-1]/max(v[-1],1):.1f}×）")

json.dump({
    "manifests": ["openalex_author_quarters.csv.manifest.json"],
    "script": "scripts/authors_build.py",
    "source": "raw/openalex_author_quarters.csv",
    "method": f"三年滚动窗口（{WINDOW} 季度闭窗）内唯一作者数；new_authors 为该季度首次出现的作者数",
    "author_scope": "主口径 unique_authors 只计【作者本人挂本地机构】的署名；"
                    "unique_authors_allauthors 为该论文全部作者（含国际合著者）的旧口径，仅作稳健性对照",
    "window_caveat": "前 11 期窗口不完整，window_full=False；先行检验只用 2017Q4 起 29 期",
    "new_authors_caveat": "2015Q1 之前无历史，new_authors 存在左截断偏误；"
                          "new_authors_usable=True（2018Q1 起）之后才可用",
    "units": [f"{a}/{b}" for a, b in units],
    "created_utc": "2026-09-07T00:00:00+00:00",
}, open(PROV, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\nprov → {PROV.name}")
