# -*- coding: utf-8 -*-
r"""
geo_variant_compare.py —— 三条 geo_rule 口径的指数落差对照（方案③的「落差本身就是结果」）

为什么单独一个脚本：方案③要求把两个口径的差异**作为一个结果报告**，
这个对照表会进正文，必须可复现、可复核，不能是临时脚本算出来的数。

两处口径纪律（都是 critic 2026-09-12 报告点出的）
  1. 港星比较必须在**共同季度交集**上做。
     fintech/hk 的 IDI 有 40 期（m8 36 期 + 牌照存量 m9_lic 40 期），
     fintech/sg 只有 36 期（只有 m8）。各自按自身可得季度取均值 = 拿香港的
     2024 年（只剩牌照一项）去和新加坡的 2015–2023 比。本脚本两种都报，
     **以交集列为准**。
  2. ΔIDI 是跨维度构成相减：六个单元的 IDI 不由同一组指标构成
     （ai 只有 m8；biomed 有 m8+m9_trials+m11；fintech 有 m8+m9_lic）。
     它**不能**解释为「谁的创新强」，只能用来量化口径选择的影响幅度。

输出：clean/geo_variant_idi_compare.csv（+ .prov.json）
R1：不产生数据值，只在既有指数文件上取均值作差。
"""
import csv, json, pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLEAN = ROOT / "clean"
VARIANTS = (("asis", "原样（附录口径）"),
            ("ali_grp", "剔阿里集团·两城同剔（正文主口径）"),
            ("ali_ant_grp", "再加剔蚂蚁集团（敏感性）"))
FIELDS = ("IDI", "IDI_创新")
INDS = ("ai", "biomed", "fintech")

rows = []
for pv, plabel in VARIANTS:
    d = {(r["industry"], r["city"], r["quarter"]): r for r in
         csv.DictReader(open(CLEAN / f"index_stock_{pv}_by_quarter.csv", encoding="utf-8-sig"))}
    for field in FIELDS:
        avail = {}
        for (i, c, q), r in d.items():
            if r[field] != "":
                avail.setdefault((i, c), set()).add(q)
        for ind in INDS:
            hkq, sgq = avail.get((ind, "hk"), set()), avail.get((ind, "sg"), set())
            inter = hkq & sgq
            def mean(c, use):
                vs = [float(d[(ind, c, q)][field]) for q in sorted(use)]
                return sum(vs) / len(vs)
            own_hk, own_sg = mean("hk", hkq), mean("sg", sgq)
            int_hk, int_sg = mean("hk", inter), mean("sg", inter)
            rows.append([pv, plabel, field, ind,
                         f"{own_hk:.4f}", len(hkq), f"{own_sg:.4f}", len(sgq),
                         f"{own_hk-own_sg:+.4f}",
                         f"{int_hk:.4f}", f"{int_sg:.4f}", len(inter),
                         f"{int_hk-int_sg:+.4f}"])

HDR = ["patent_variant", "variant_label", "field", "industry",
       "hk_mean_own_window", "hk_n_own", "sg_mean_own_window", "sg_n_own", "delta_own_window",
       "hk_mean_common", "sg_mean_common", "n_common_quarters", "delta_common_window"]
out = CLEAN / "geo_variant_idi_compare.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(HDR); w.writerows(rows)

print(f"✅ clean/{out.name}（{len(rows)} 行）\n")
for field in FIELDS:
    print(f"════ {field}  Δz = hk − sg（**共同季度交集**口径）════")
    print(f"  {'产业':10s}" + "".join(f"{lab[:14]:>18s}" for _, lab in VARIANTS))
    for ind in INDS:
        cells = []
        for pv, _ in VARIANTS:
            r = next(x for x in rows if x[0] == pv and x[2] == field and x[3] == ind)
            cells.append(f"{r[12]:>12s}({r[11]}期)")
        print(f"  {ind:10s}" + "".join(f"{c:>18s}" for c in cells))
    print()

json.dump({
    "inputs": [f"clean/index_stock_{v}_by_quarter.csv" for v, _ in VARIANTS],
    "manifests": [f"patents_families_by_quarter_company_{v}.csv.manifest.json" for v, _ in VARIANTS]
                 + ["openalex_author_quarters.csv.manifest.json",
                    "openalex_works_master.csv.manifest.json"],
    "script": "scripts/geo_variant_compare.py",
    "method": "对每个口径×字段×产业，取港星在【共同可得季度交集】上的均值作差；同时报各自窗口版以显示窗口错配的影响",
    "decision": "2026-09-12 邱正陽拍板方案③：正文主口径 ali_grp，附录 asis，敏感性 ali_ant_grp",
    "interpretation_limit": "ΔIDI 是跨维度构成相减（六单元 IDI 不由同一组指标构成），"
                            "只可用于量化口径选择的影响幅度，不可解释为『谁强谁弱』（critic 2026-09-12）",
    "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}, open(str(out) + ".prov.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
