# -*- coding: utf-8 -*-
"""从 raw/openalex_works_master.csv 算出指标 4、5、7

输入：raw/openalex_works_master.csv           （collect_openalex_master.py 产出）
      raw/openalex_topjournal_denominators.csv（--journals 产出，指标 5 才需要）
      config/boundary_rules_v1.yaml            （期刊白名单）

输出：clean/intl_collab_by_quarter.csv     指标 7 · TAI 网络 · 季度
      clean/top10pct_by_quarter.csv        指标 4 · TAI 质量 · 季度（原生聚合，非内插）
      clean/top10pct_by_year.csv           指标 4 · 年度（附录 A 原定频率）
      clean/topjournal_share_by_year.csv   指标 5 · TAI 质量 · 年度

【R1 纪律】
    is_top10pct 为空＝该篇没有 citation_normalized_percentile 字段，**不是**「不在前10%」。
    分母一律只计有该字段的论文，并同时输出 coverage 列。覆盖率过低时指标 4 不可用——
    由人看着 coverage 判断，脚本不替你决定。
"""
import csv, collections, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "raw" / "openalex_works_master.csv"
DEN = ROOT / "raw" / "openalex_topjournal_denominators.csv"
CLEAN = ROOT / "clean"
QUARTERS = [f"{y}Q{q}" for y in range(2015, 2025) for q in range(1, 5)]
YEARS = list(range(2015, 2025))

if not SRC.exists():
    sys.exit(f"⛔ 找不到 {SRC}\n   先跑 python scripts/collect_openalex_master.py --all")

rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
print(f"读入 {len(rows):,} 篇 works")
units = sorted({(r["industry"], r["city"]) for r in rows})
print(f"单元 {len(units)} 个：{units}")

bad = {r["quarter"] for r in rows} - set(QUARTERS)
if bad:
    sys.exit(f"⛔ 出现窗口外季度：{sorted(bad)}")

CLEAN.mkdir(parents=True, exist_ok=True)


def dump(path, header, data, prov):
    with open(CLEAN / path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(data)
    json.dump(prov, open(CLEAN / (path + ".prov.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"✅ clean/{path}  {len(data)} 行")


# ── 指标 7 · 国际合著比例（季度）──────────────────────────
tot = collections.Counter(); intl = collections.Counter()
for r in rows:
    k = (r["industry"], r["city"], r["quarter"])
    tot[k] += 1
    if r["is_intl"] == "1":
        intl[k] += 1
out7 = []
for ind, city in units:
    for q in QUARTERS:
        k = (ind, city, q)
        n, i = tot[k], intl[k]
        out7.append([ind, city, q, n, i, f"{i/n:.6f}" if n else ""])
dump("intl_collab_by_quarter.csv",
     ["industry", "city", "quarter", "works", "intl_works", "intl_share"], out7,
     {"manifests": ["openalex_works_master.csv.manifest.json"],
      "script": "scripts/works_build.py",
      "method": "指标7·TAI网络：涉及两个及以上国家/地区机构的论文占比；"
                "国家数由 authorships[].institutions[].country_code 去重得到",
      "note": "分母与 raw/openalex_papers_by_quarter.csv 同源同 filter，可交叉验证；"
              "本口径一并解决了 v1 只有 4/6 单元有分子的问题",
      "units": [f"{a}/{b}" for a, b in units]})

# 与旧文件交叉验证（能对上就说明新旧口径一致）
old = ROOT / "raw" / "openalex_papers_by_quarter.csv"
if old.exists():
    o = {}
    for r in csv.DictReader(open(old, encoding="utf-8-sig")):
        o[(r["industry"], r["city"], r["quarter"])] = int(r["count"])
    diff = [(k, tot[k], o[k]) for k in o if k in tot and tot[k] != o[k]]
    same = sum(1 for k in o if k in tot and tot[k] == o[k])
    delta = sum(tot[k] - o[k] for k in o if k in tot)
    base = sum(o[k] for k in o if k in tot) or 1
    print(f"   ↳ 与 openalex_papers_by_quarter.csv（2026-08-26 采）对照："
          f"{same}/{len(o)} 格完全一致，总量差 {delta:+,} 篇（{delta/base:+.2%}）")
    print(f"      ⚠️ 不一致是【预期的】：两次采集相隔半个月，OpenAlex 会持续回填索引。"
          f"判断标准是总量差在 ±1% 内、且新采不小于旧采；不是逐格必须相同。")
    if diff[:3]:
        print(f"      样例：{diff[:3]}")

# ── 指标 4 · 前10%高引占比（季度＋年度）────────────────────
HAS_T1 = "is_top1pct" in (rows[0] if rows else {})

def top10(keyfn, keys, label):
    den = collections.Counter(); num = collections.Counter()
    num1 = collections.Counter(); miss = collections.Counter()
    for r in rows:
        k = (r["industry"], r["city"], keyfn(r))
        if r["is_top10pct"] == "":
            miss[k] += 1
        else:
            den[k] += 1
            if r["is_top10pct"] == "1":
                num[k] += 1
            if HAS_T1 and r.get("is_top1pct") == "1":
                num1[k] += 1
    out = []
    for ind, city in units:
        for t in keys:
            k = (ind, city, t)
            d, n, n1, m = den[k], num[k], num1[k], miss[k]
            out.append([ind, city, t, d + m, d, n,
                        f"{n/d:.6f}" if d else "",
                        n1 if HAS_T1 else "",
                        (f"{n1/d:.6f}" if d else "") if HAS_T1 else "",
                        f"{d/(d+m):.4f}" if (d + m) else ""])
    return out


for label, keyfn, keys, fname in (
        ("季度", lambda r: r["quarter"], QUARTERS, "top10pct_by_quarter.csv"),
        ("年度", lambda r: r["year"], [str(y) for y in YEARS], "top10pct_by_year.csv")):
    data = top10(keyfn, keys, label)
    cov = [float(x[9]) for x in data if x[9]]
    dump(fname,
         ["industry", "city", "period", "works", "works_with_cnp", "top10_works",
          "top10_share", "top1_works", "top1_share", "cnp_coverage"], data,
         {"manifests": ["openalex_works_master.csv.manifest.json"],
          "script": "scripts/works_build.py",
          "method": f"指标4·TAI质量·{label}：citation_normalized_percentile 的 "
                    f"is_in_top_10_percent 为真的论文 ÷ 有该字段的论文",
          "r1_note": "分母只计有 citation_normalized_percentile 的论文；"
                     "缺失既不计入分子也不计入分母，cnp_coverage 列如实汇报覆盖率",
          "top1_note": "top1_share 为前 1% 高引占比——附录 A 未定义此指标，"
                       "字段与前 10% 同在一个响应对象里、零额外调用，留作质量维稳健性口径。"
                       "用不用由组会定；若用须在方法章声明为超出附录 A 的新增稳健性检验",
          "frequency_note": "季度版是对单篇论文属性的原生季度聚合，不是年度值内插，"
                            "不违反提案 §4.2；附录 A 原定频率为年，是否用季度版由组会定",
          "units": [f"{a}/{b}" for a, b in units]})
    if cov:
        print(f"   ↳ {label} cnp 覆盖率：最低 {min(cov):.1%}　中位 "
              f"{sorted(cov)[len(cov)//2]:.1%}　最高 {max(cov):.1%}")

# ── 指标 5 · 顶刊份额（年度）──────────────────────────────
if not DEN.exists():
    print(f"\n⚠️ 没有 {DEN.name}，跳过指标 5。\n"
          f"   先跑 python scripts/collect_openalex_master.py --journals")
else:
    import yaml
    rules = yaml.safe_load(open(ROOT / "config" / "boundary_rules_v1.yaml", encoding="utf-8"))
    # source_id -> (industry, tier)
    jmap = {}
    for ind, spec in rules["industries"].items():
        oa = spec.get("openalex", {})
        for tier, key in (("core", "journals"), ("sensitivity", "journals_sensitivity")):
            for jr in oa.get(key) or []:
                jmap[jr["id"].rstrip("/").rsplit("/", 1)[-1]] = (ind, tier, jr["name"])
    den = collections.Counter()
    for r in csv.DictReader(open(DEN, encoding="utf-8-sig")):
        den[(r["industry"], int(r["year"]), r["tier"])] += int(r["global_works"])
    num = collections.Counter()
    for r in rows:
        hit = jmap.get(r["source_id"])
        if hit:
            ind_j, tier, _ = hit
            num[(r["industry"], r["city"], int(r["year"]), tier)] += 1
    out5 = []
    inds_with_j = sorted({v[0] for v in jmap.values()})
    for ind, city in units:
        base = ind.replace("_kw", "")
        if base not in inds_with_j:
            continue
        for y in YEARS:
            for tier in ("core", "sensitivity"):
                n, d = num[(ind, city, y, tier)], den[(base, y, tier)]
                out5.append([ind, city, y, tier, n, d, f"{n/d:.8f}" if d else ""])
    dump("topjournal_share_by_year.csv",
         ["industry", "city", "year", "tier", "local_works", "global_works", "share"], out5,
         {"manifests": ["openalex_works_master.csv.manifest.json",
                        "openalex_topjournal_denominators.csv.manifest.json"],
          "script": "scripts/works_build.py",
          "method": "指标5·TAI质量：本地该产业顶刊论文 ÷ 全球该产业顶刊论文（按年）；"
                    "综合刊（Nature/Science）分子分母都加了同一产业学科过滤",
          "coverage_note": "fintech 的 boundary_rules 里期刊清单为空——"
                           "指标 5 只能做 ai 与 biomed，六个单元里只有四个有值",
          "tier_note": "core=2015 前创刊；sensitivity=窗口内创刊，按 time_window_rule 只进敏感性附表",
          "units": [f"{a}/{b}" for a, b in units]})
    miss_ind = [f"{a}/{b}" for a, b in units if a.replace("_kw", "") not in inds_with_j]
    if miss_ind:
        print(f"   ↳ ⚠️ 无期刊清单、指标 5 做不了的单元：{miss_ind}")

# ── source_id 覆盖率（指标 5 的分子基础，如实汇报）──────────
src_tot = collections.Counter(); src_has = collections.Counter()
for r in rows:
    k = (r["industry"], r["city"])
    src_tot[k] += 1
    if r["source_id"]:
        src_has[k] += 1
print("\nprimary_location.source 覆盖率（缺失多为 preprint/repository，顶刊论文必带 source，"
      "故不影响指标 5 的分子）：")
for ind, city in units:
    k = (ind, city)
    print(f"   {ind:12s}{city:4s} {src_has[k]:>7,} / {src_tot[k]:>7,}  ({src_has[k]/max(src_tot[k],1):.1%})")

print("\n完成。")
