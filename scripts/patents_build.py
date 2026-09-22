# -*- coding: utf-8 -*-
r"""
patents_build.py —— 把 BigQuery 导出的「家族级」专利文件加工成入库用的季度序列

为什么是本地做（2026-08-26）：
    BigQuery 的查询只跑一次，输出到"家族"这一级（约 1 万行，带申请人）。
    之后所有口径决策都在这里做——三分归类、企业口径、跨产业唯一分配、补零——
    改规则不用再回 BigQuery，也不再消耗免费额度。

输入：
    raw/patents_families_raw.csv
        industry,city,quarter,family_id,first_filing_in_window,assignees
    config/patents_assignee_sector.csv （可选，人工归类后才有）
        assignee,sector      sector ∈ university / company / public_rd

输出：
    raw/patents_families_by_quarter.csv   216 行（3产业×2城市×36季度，已补零）
    raw/patents_assignees.csv             申请人清单（附 families 数），供人工归类
    并打印：年度/季度自洽核对、跨产业重叠量、归类覆盖率

用法：
    python scripts/patents_build.py                # 全申请人口径
    python scripts/patents_build.py --sector company   # 仅企业（指标 8 的正式口径）
"""
import argparse
import csv
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, CFG = ROOT / "raw", ROOT / "config"
INDUSTRIES = ("ai", "biomed", "fintech")
CITIES = ("hk", "sg")
QUARTERS = [f"{y}Q{q}" for y in range(2015, 2024) for q in range(1, 5)]   # 36 期


def load_sector_map():
    f = CFG / "patents_assignee_sector.csv"
    if not f.exists():
        return None
    with open(f, encoding="utf-8-sig", newline="") as fh:
        return {r["assignee"].strip(): r["sector"].strip() for r in csv.DictReader(fh)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sector", choices=["company", "university", "public_rd"],
                    help="只保留该 sector 的家族（指标 8 用 company）")
    ap.add_argument("--infile", default="raw/patents_families_raw.csv")
    args = ap.parse_args()

    src = ROOT / args.infile
    if not src.exists():
        raise SystemExit(
            f"⛔ 找不到 {src}\n\n"
            f"   脚本按自己的位置往上一层找 raw/，本次找的是：\n     {ROOT}\n\n"
            f"   如果上面这个路径不是 C:\\FYP\\data_repo，说明你在【解压出来的任务包目录】里跑，\n"
            f"   而底稿只在仓库里。把脚本复制进仓库再跑：\n\n"
            f"       copy <任务包>\\scripts\\*.py C:\\FYP\\data_repo\\scripts\\\n"
            f"       cd C:\\FYP\\data_repo\n"
            f"       python scripts\\patents_build.py --sector company\n\n"
            f"   （BigQuery 不用重跑——底稿 2026-08-27 就已入库）")
    with open(src, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    print(f"读入 {len(rows):,} 行家族记录")

    # ---- 完整性自检 ----
    bad_q = {r["quarter"] for r in rows} - set(QUARTERS)
    if bad_q:
        raise SystemExit(f"出现窗口外的季度：{sorted(bad_q)}——查询的窗口条件对不上")
    dup = [k for k, n in collections.Counter(
        (r["industry"], r["city"], r["family_id"]) for r in rows).items() if n > 1]
    if dup:
        raise SystemExit(f"同一「产业×城市×家族」出现多行（{len(dup)} 个），说明查询没按家族去重")
    print("✅ 季度都在窗口内；每个「产业×城市×家族」唯一一行")

    # ---- 跨产业重叠 ----
    per_fam = collections.defaultdict(set)
    for r in rows:
        per_fam[(r["city"], r["family_id"])].add(r["industry"])
    overlap = collections.Counter(len(v) for v in per_fam.values())
    print(f"跨产业重叠：" + "；".join(f"{k}个产业 {v} 族" for k, v in sorted(overlap.items())))
    multi = sum(v for k, v in overlap.items() if k > 1)
    print(f"   跨界家族 {multi} 个，占 {multi/len(per_fam)*100:.1f}%"
          f"（骨架 4.3 要求唯一分配，规则未定前先按重复计入，已如实记录）")

    # ---- 申请人清单 ----
    # 注意：rows 是家族级但**按产业展开**的，跨产业家族会出现多行。
    # 统计申请人时必须先按 (city, family_id) 去重，否则跨产业家族被重复计
    # （BigQuery 查询3 就是这么错的，见 scripts/fix_assignees.py 的说明）。
    acount = collections.Counter()
    _seen_fam = set()
    for r in rows:
        k = (r["city"], r["family_id"])
        if k in _seen_fam:
            continue
        _seen_fam.add(k)
        for a in (r["assignees"] or "").split(" | "):
            if a.strip():
                acount[(r["city"], a.strip())] += 1
    out_a = RAW / "patents_assignees.csv"
    with open(out_a, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["city", "assignee", "families"])
        # 排序与 scripts/fix_assignees.py 保持一致（城市升序、家族次降序、名称升序），
        # 否则两个脚本产出同样的内容但不同的字节序，manifest 哈希会对不上。
        w.writerows([[c, a, n] for (c, a), n in
                     sorted(acount.items(), key=lambda x: (x[0][0], -x[1], x[0][1]))])
    print(f"申请人清单 → raw/{out_a.name}（{len(acount):,} 行）")

    # ---- sector 过滤 ----
    smap = load_sector_map()
    if args.sector:
        if not smap:
            raise SystemExit("要按 sector 过滤，得先有 config/patents_assignee_sector.csv（人工归类产物）")
        keep = []
        for r in rows:
            secs = {smap.get(a.strip()) for a in (r["assignees"] or "").split(" | ") if a.strip()}
            if args.sector in secs:
                keep.append(r)
        print(f"sector={args.sector} 过滤：{len(rows):,} → {len(keep):,} 行")
        rows = keep
    elif smap:
        cov = sum(1 for (c, a) in acount if a in smap) / len(acount) * 100
        print(f"（已有归类表，覆盖 {cov:.1f}% 的申请人；本次未过滤，加 --sector company 出指标 8 口径）")
    else:
        print("（还没有 config/patents_assignee_sector.csv，本次是**全申请人口径**，不是指标 8 的正式口径）")

    # ---- 聚合 + 补零 ----
    cnt = collections.Counter((r["industry"], r["city"], r["quarter"]) for r in rows)
    full = [[i, c, q, cnt.get((i, c, q), 0)] for i in INDUSTRIES for c in CITIES for q in QUARTERS]
    out_q = RAW / "patents_families_by_quarter.csv"
    with open(out_q, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["industry", "city", "quarter", "patent_families"]); w.writerows(full)
    zeros = sum(1 for r in full if r[3] == 0)
    print(f"季度序列 → raw/{out_q.name}（{len(full)} 行，其中补零 {zeros} 行）")

    # ---- 年度 vs 季度自洽（同源，必须严格相等）----
    ay = collections.Counter((r["industry"], r["city"], r["quarter"][:4]) for r in rows)
    aq = collections.Counter()
    for i, c, q, n in full:
        aq[(i, c, q[:4])] += n
    diff = [k for k in set(ay) | set(aq) if ay[k] != aq[k]]
    print("年度/季度自洽：", "✅ 完全一致" if not diff else f"❌ {len(diff)} 处不一致 {diff[:5]}")
    print(f"\n合计 {sum(r[3] for r in full):,} 个家族次")


if __name__ == "__main__":
    main()
