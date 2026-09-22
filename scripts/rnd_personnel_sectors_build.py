# -*- coding: utf-8 -*-
r"""
rnd_personnel_sectors_build.py —— 从 P2 包裹抽出 R&D 人员的**按执行界别**序列

为什么需要（2026-09-14）：
    关二（外部校准）此前用 clean/rnd_personnel_business_by_year.csv 做分母，
    那是**商业界别**FTE。但指标 1 的分子（OpenAlex 研究者）绝大部分在大学与
    大学医院——分母里根本不含他们。生物医药比值算出 270% 就是分母错的直接证据。

    修法不需要采集：**高等教育界别（HE）序列早已在 raw/p2_censtatd_rnd_vacancies.txt
    里**（「按执行界别分解（同源）」段，2015–2024 全覆盖，与商业界别同表 710-86003）。
    本脚本只做本地抽取与自洽校验，零 API 调用。

自洽校验：Total 应等于 Business + HE + Govt（统计处四舍五入到整数，允许 |差| ≤ 2）。

输出：clean/rnd_personnel_by_sector_series.csv （宽表：sector × year）
     clean/rnd_personnel_by_sector_series.csv.prov.json
R1：不产生任何数据值，只从既有包裹逐行抄写并校验。
"""
import csv, json, pathlib, re
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "raw" / "p2_censtatd_rnd_vacancies.txt"
OUT = ROOT / "clean" / "rnd_personnel_by_sector_series.csv"

txt = SRC.read_text(encoding="utf-8")

# ── 商业界别（SERIES 段，逐行带 URL）──
biz = {}
sec = txt.split("=== SERIES: rnd_personnel_business_by_year ===")[1].split("===")[0]
for line in sec.splitlines():
    m = re.match(r"^(\d{4}),(\d+),FTE,(http\S+)", line.strip())
    if m:
        biz[int(m.group(1))] = int(m.group(2))

# ── 按执行界别分解段 ──
tot, he, gov = {}, {}, {}
sec2 = txt.split("按执行界别分解（同源）：")[1].split("族表")[0]
for line in sec2.splitlines():
    m = re.match(r"^(\d{4})\s+Total\s+(\d+)\s*/\s*HE\s+(\d+)\s*/\s*Govt\s+(\d+)", line.strip())
    if m:
        y = int(m.group(1))
        tot[y], he[y], gov[y] = int(m.group(2)), int(m.group(3)), int(m.group(4))

years = sorted(set(biz) & set(tot))
if not years:
    raise SystemExit("⛔ 没解析出任何年份——P2 包裹的格式变了，先看原文再改正则")
print(f"解析到 {len(years)} 年：{years[0]}–{years[-1]}")

# ── 自洽校验 ──
bad = []
for y in years:
    diff = tot[y] - (biz[y] + he[y] + gov[y])
    if abs(diff) > 2:
        bad.append((y, tot[y], biz[y], he[y], gov[y], diff))
    print(f"  {y}  Total {tot[y]:>6,}  = Biz {biz[y]:>6,} + HE {he[y]:>6,} + Govt {gov[y]:>5,}"
          f"   残差 {diff:+d}")
if bad:
    raise SystemExit(f"⛔ {len(bad)} 年不自洽（残差 >2），不是四舍五入能解释的：{bad}")
print("✅ 逐年自洽：Total = Business + HE + Govt（残差全部在 ±2 的四舍五入范围内）")

SECTORS = [("business", biz), ("higher_education", he), ("government", gov), ("total", tot)]
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["sector"] + [str(y) for y in years])
    for name, d in SECTORS:
        w.writerow([name] + [d[y] for y in years])
print(f"\n✅ clean/{OUT.name}（{len(SECTORS)} 行 × {len(years)} 年）")

# 关二会用到的比值提示（不落盘，只打印，避免把推论当数据入库）
print("\n参考：HE 界别 2015→2024 增长 "
      f"{he[years[0]]:,} → {he[years[-1]]:,}（×{he[years[-1]]/he[years[0]]:.2f}）；"
      f"商业界别 ×{biz[years[-1]]/biz[years[0]]:.2f}")
print("⚠️ 关二用哪个界别做分母，取决于指标 1 分子的机构构成，须在方法章声明，不由本脚本决定。")

json.dump({
    "manifests": ["p2_censtatd_rnd_vacancies.txt.manifest.json"],
    "script": "scripts/rnd_personnel_sectors_build.py",
    "method": "从 P2 包裹的『按执行界别分解（同源）』段与商业界别 SERIES 段逐行抄写；"
              "零 API 调用；逐年校验 Total = Business + HE + Govt（容差 ±2 四舍五入）",
    "source_table": "政府统计处表 710-86003（族表 710-86110 与之逐年相等，双表互证）",
    "why": "关二此前用商业界别做分母，而指标1的分子主要来自大学与大学医院；"
           "生物医药比值 270% 即分母错配的证据",
    "pending": "关二采用哪个界别作分母，须按指标1分子的机构构成决定并在方法章声明",
    "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}, open(str(OUT) + ".prov.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
