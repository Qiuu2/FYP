# -*- coding: utf-8 -*-
r"""
listings_geo_review_init.py —— 生成指标 11 的 geo_rule 人工判定表骨架

为什么需要：2026-09-12 拍板方案③后，指标 8 已按 geo_rule 剔除了「在港无实质研发」
的申请人主体。同一条规则必须适用于指标 11 的 18A/18C 上市企业，否则正文里
「香港商业化维」和「香港创新维」说的不是同一个「香港」。

本脚本只做一件事：把窗口内（2015Q1–2024Q4）的上市企业列成待判定表，
**判定列全部留空**——「某企业在香港是否有实质运营或研发」是事实判定，
需要查公司注册、年报、研发中心公开信息，R1 禁止 AI 臆断。

输出：config/listings_geo_review.csv
     列 name / industry / listing_chapter / listing_date / quarter
        hk_substantive（人工填 1=在港有实质运营或研发，0=无，空=未判定）
        hq_location / evidence_url / reviewer / review_date / notes
     notes 列很重要：查不到、双中心、拿不准这三种情形都要在这里留话，
     R4 复核时不一致的那几家全靠它说清当时看到了什么。

填好后直接重跑 scripts/listings_build.py，它会自动读取并多出一条
new_listings_hk_substantive 列（实质运营口径）。

用法：python scripts/listings_geo_review_init.py [--force]
     默认不覆盖已存在的判定表（防止把人填好的结果冲掉）。
"""
import argparse, csv, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "raw" / "p3_hkex_listings.txt"
OUT = ROOT / "config" / "listings_geo_review.csv"
QUARTERS = [f"{y}Q{q}" for y in range(2015, 2025) for q in range(1, 5)]

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="覆盖已存在的判定表（会丢掉人工填的内容）")
args = ap.parse_args()

if OUT.exists() and not args.force:
    filled = sum(1 for r in csv.DictReader(open(OUT, encoding="utf-8-sig"))
                 if (r.get("hk_substantive") or "").strip())
    sys.exit(f"⚠️ {OUT.relative_to(ROOT)} 已存在（已填 {filled} 行判定）。"
             f"\n   要重建骨架请加 --force —— 但那会丢掉人工填好的内容。")

txt = SRC.read_text(encoding="utf-8")
q_of = lambda y, m: f"{y}Q{(m - 1) // 3 + 1}"
rows = []

sec = txt.split("=== TABLE: listings_18c ===")[1].split("===")[0]
for line in sec.splitlines():
    m = re.match(r"^([^,]+),(\d{1,2})/(\d{1,2})/(\d{4}),", line.strip())
    if m:
        d, mo, y = int(m.group(2)), int(m.group(3)), int(m.group(4))
        rows.append([m.group(1).strip(), "ai", "18C", f"{y}-{mo:02d}-{d:02d}", q_of(y, mo)])

sec = txt.split("=== TABLE: listings_18a ===")[1].split("=== 争议")[0]
for chunk in sec.replace("\n", "｜").split("｜"):
    m = re.match(r"^\s*([^,]+),(\d{3,5}),(\d{4})-(\d{2})-(\d{2})", chunk.strip())
    if m:
        y, mo, d = int(m.group(3)), int(m.group(4)), int(m.group(5))
        rows.append([m.group(1).strip(), "biomed", "18A", f"{y}-{mo:02d}-{d:02d}", q_of(y, mo)])

inwin = [r for r in rows if r[4] in QUARTERS]
inwin.sort(key=lambda r: (r[3], r[0]))
print(f"解析 {len(rows)} 家 → 窗口内 {len(inwin)} 家"
      f"（18C {sum(1 for r in inwin if r[2]=='18C')} · 18A {sum(1 for r in inwin if r[2]=='18A')}）")

OUT.parent.mkdir(exist_ok=True)
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["name", "industry", "listing_chapter", "listing_date", "quarter",
                "hk_substantive", "hq_location", "evidence_url", "reviewer", "review_date",
                "notes"])
    for r in inwin:
        w.writerow(r + ["", "", "", "", "", ""])
print(f"✅ config/{OUT.name}（{len(inwin)} 行，判定列全空——等人填）")
print("\n判定标准（与指标 8 的 geo_rule 同一条）：")
print("  hk_substantive=1  在香港有实质运营或研发（研发中心／临床团队／主要经营地在港）")
print("  hk_substantive=0  仅以香港为上市地／注册地，研发与运营在其他法域")
print("  留空              未判定。listings_build.py 只会把 =1 的计入实质运营口径")
print("\n⚠️ 提示：18A 板块以内地生物科技企业为主体，这条规则一致执行后，")
print("   biomed/hk 的商业化维很可能大幅收缩——这是口径自洽的代价，不是错误。")
