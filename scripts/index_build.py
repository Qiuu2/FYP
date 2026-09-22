# -*- coding: utf-8 -*-
"""TAI / IDI 季度合成与指标层秩表（2026-09-22 按三条口径规则重写）

═══ 为什么重写（这是本文件最重要的一段，改之前先读完）═══

2026-09-12 的独立复查指出：效度关两关没过，根因不是数据不够，
而是**把指数用在了它承载不了的那一层**。

    六个单元的 IDI 由**不同的指标集**构成：
        ai/hk      IDI_创新 = m8
        biomed/hk  IDI_创新 = m8 + m9_trials
        fintech/hk IDI_创新 = m8 + m9_lic
        fintech/sg IDI_创新 = m8
    拿它们相减，不是同一个量之差。

    更要命的是：「维度内对可得指标取均值」**在数学上就是一种插补**——
    它把缺失的指标插补成「该单元自身其它指标的均值」。
    这不是中性的，它系统性地让指标少的单元向自己的已有指标靠拢。
    旧版文件头写的「不做插补」是错的。

═══ 三条口径规则（写死，不得因结果而改）═══

R-A  跨单元比较只在**指标层**做，用秩与方向，不用 z 差。
     → 输出 clean/indicator_rank_by_quarter.csv
     → 只含**六单元齐备**的四个指标：m1 · m4 · m7 · m8

R-B  指数（TAI/IDI）只用于**单元内时序**：同一单元构成不变，变化量才有意义。
     → 输出 clean/index_{ver}_{variant}_by_quarter.csv，**禁止跨单元相减**
     → 每个文件都带 comparability 字段标明这一点

R-C  同一维度内**时间属性必须统一**。
     → IDI 创新维三项全部改为**流量**：
        m8 专利族（当季首次申请）· m9_trials 临床试验（当季新登记）
        · m9_lic 牌照（当季新增，原为累计存量 lag1≈0.95）
     → 累计序列的方差被自相关放大，与流量等权平均时实际权重由方差决定，
        不由我们决定。

═══ 维度构成（2026-09-22 起）═══

    TAI 规模 ← m1  研究者（stock 版=三年滚动存量 / flow 版=当季新增作者）
    TAI 质量 ← m4  前 10% 高引占比
    TAI 网络 ← m7  国际合著比例
    IDI 创新 ← m8 企业专利族 ＋ m9_trials 临床试验 ＋ m9_lic 牌照（均为流量）
    IDI 商业 ← **空**。原指标 m11（18A/18C 上市）已退出，理由见下
    IDI 资本 ← 无季度指标，只进年度剖面

    ⚠️ **IDI 目前只实现了创新维**，所以 IDI 的数值等于创新维本身。
       输出仍保留 IDI 列是为了下游脚本兼容，读的时候要知道它没有合成任何东西。

    m11 退出的理由（`docs/指标11_geo判定结果_2026-09-18.md`）：
       窗口内 70 家 18A/18C 上市企业中 **69 家主运营不在香港**，
       实质运营口径下只剩 1 家、序列是条阶跃直线，无时序信息。

═══ 指标 8 的 geo_rule 三档口径（2026-09-12 方案③）═══
    asis / ali_grp（**正文主口径**）/ ali_ant_grp
    不带后缀的 clean/index_{ver}_by_quarter.csv == 主口径 ali_grp
"""
import csv, json, math, pathlib, collections
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLEAN, RAW = ROOT / "clean", ROOT / "raw"
QUARTERS = [f"{y}Q{q}" for y in range(2015, 2025) for q in range(1, 5)]
UNITS = [("ai", "hk"), ("ai", "sg"), ("biomed", "hk"), ("biomed", "sg"),
         ("fintech", "hk"), ("fintech", "sg")]
PATENT_VARIANTS = ("asis", "ali_grp", "ali_ant_grp")
MAIN_VARIANT = "ali_grp"
# R-A：六单元齐备、可用于跨单元比较的指标。其余一律只进单元内时序。
CORE4 = ("m1", "m4", "m7", "m8")
norm = lambda i: i.replace("_kw", "")


def load(path, ind_col, city_col, q_col, val_col, gate=None, fixed_ind=None, fixed_city=None):
    d = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if gate and not gate(r):
            continue
        ind = fixed_ind or norm(r[ind_col])
        city = fixed_city or r[city_col]
        q, v = r[q_col], r[val_col]
        if v == "" or q not in QUARTERS:
            continue
        d[(ind, city, q)] = float(v)
    return d


# ══ 载入指标序列 ══════════════════════════════════════
S = {}
S["m1_stock"] = load(CLEAN/"researchers_stock_by_quarter.csv", "industry", "city", "quarter",
                     "unique_authors", gate=lambda r: r["window_full"] == "True")
S["m1_flow"] = load(CLEAN/"researchers_stock_by_quarter.csv", "industry", "city", "quarter",
                    "new_authors", gate=lambda r: r["new_authors_usable"] == "True")
S["m4"] = load(CLEAN/"top10pct_by_quarter.csv", "industry", "city", "period", "top10_share")
S["m7"] = load(CLEAN/"intl_collab_by_quarter.csv", "industry", "city", "quarter", "intl_share")
S["m9_trials"] = load(RAW/"clinicaltrials_by_quarter.csv", None, "city", "quarter", "count",
                      fixed_ind="biomed")
# R-C：牌照改用**当季新增**，不再用 licenses_cumulative（累计，lag1≈0.95）
S["m9_lic"] = load(CLEAN/"fintech_licenses_by_quarter.csv", "industry", "city", "quarter",
                   "new_this_quarter")
# m11 已退出，不再载入 listings_by_quarter.csv

M8 = {v: load(RAW/f"patents_families_by_quarter_company_{v}.csv", "industry", "city", "quarter",
              "patent_families") for v in PATENT_VARIANTS}
S["m8"] = M8[MAIN_VARIANT]

print("── 指标序列 ──")
for k, v in S.items():
    us = sorted({(a, b) for a, b, _ in v})
    print(f"  {k:10s} {len(v):>4} 格  {len(us)} 单元  期数 {len(v)//max(len(us),1)}"
          + ("   ← 六单元齐备" if len(us) == 6 else "   ← 结构性不齐，只进单元内时序"))


def zscore(ser):
    """冻结参照集 z-score：在该指标自己的全部可得格上标准化。"""
    vals = list(ser.values())
    mu = sum(vals) / len(vals)
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / len(vals)) or 1.0
    return {k: (v - mu) / sd for k, v in ser.items()}, mu, sd


Z = {}
print("\n── z 标准化（冻结参照集）──")
for k, ser in S.items():
    Z[k], mu, sd = zscore(ser)
    print(f"  z({k:10s}) n={len(ser):>4}  mean={mu:>12.4f}  sd={sd:>12.4f}")

DIMS = {
    "TAI_规模": {"stock": ["m1_stock"], "flow": ["m1_flow"]},
    "TAI_质量": {"stock": ["m4"], "flow": ["m4"]},
    "TAI_网络": {"stock": ["m7"], "flow": ["m7"]},
    "IDI_创新": {"stock": ["m8", "m9_trials", "m9_lic"],
                 "flow": ["m8", "m9_trials", "m9_lic"]},
}
TAI_DIMS = ("TAI_规模", "TAI_质量", "TAI_网络")
IDI_DIMS = ("IDI_创新",)          # 商业维空、资本维无季度源


# ══ R-A：指标层秩表（跨单元比较的唯一合法载体）══════════
def build_rank_table():
    """对六单元齐备的四个指标，逐指标逐季度给出秩。

    三套秩并存，因为它们回答不同的问题：
      rank6    六单元内的秩（1=最高）
      rank_hk  香港三产业内的秩 —— 文献讲的是香港产业间对比，这一套才对应
      rank_sg  新加坡三产业内的秩 —— 不设预期，用作判别效度对照
    """
    rows = []
    for mkey in ("m1_stock", "m1_flow", "m4", "m7", "m8"):
        ser = S[mkey]
        base = mkey.split("_")[0]
        if base not in CORE4:
            continue
        for q in QUARTERS:
            cells = {(i, c): ser[(i, c, q)] for i, c in UNITS if (i, c, q) in ser}
            if len(cells) < 6:
                continue                      # 六单元不齐的季度不排秩
            r6 = _rank({k: v for k, v in cells.items()})
            rhk = _rank({k: v for k, v in cells.items() if k[1] == "hk"})
            rsg = _rank({k: v for k, v in cells.items() if k[1] == "sg"})
            for (i, c), val in cells.items():
                rows.append([mkey, q, i, c, f"{val:.6f}", f"{Z[mkey][(i,c,q)]:.6f}",
                             r6[(i, c)], rhk.get((i, c), ""), rsg.get((i, c), "")])
    return rows


def _rank(d):
    """1 = 最大。并列取平均秩。"""
    order = sorted(d.items(), key=lambda kv: -kv[1])
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][1] == order[i][1]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k][0]] = f"{avg:g}"
        i = j + 1
    return out


rank_rows = build_rank_table()
out_rank = CLEAN / "indicator_rank_by_quarter.csv"
with open(out_rank, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["indicator", "quarter", "industry", "city", "value", "z",
                "rank6", "rank_hk3", "rank_sg3"])
    w.writerows(rank_rows)
print(f"\n✅ clean/{out_rank.name}（{len(rank_rows)} 行）"
      f"　← R-A：跨单元比较**只能**用这张表")

# 秩表的可用期数
per_ind = collections.Counter(r[0] for r in rank_rows)
print("   每个指标的可排秩季度数：" +
      "　".join(f"{k}={v//6}" for k, v in sorted(per_ind.items())))


# ══ R-B：指数（单元内时序专用）═══════════════════════
def build_index(ver):
    rows, cov = [], []
    for ind, city in UNITS:
        for q in QUARTERS:
            dimv, used, miss = {}, {}, {}
            for dn, spec in DIMS.items():
                have = [m for m in spec[ver] if (ind, city, q) in Z[m]]
                lack = [m for m in spec[ver] if m not in have]
                if have:
                    dimv[dn] = sum(Z[m][(ind, city, q)] for m in have) / len(have)
                    used[dn], miss[dn] = have, lack
            tai = [dimv[d] for d in TAI_DIMS if d in dimv]
            idi = [dimv[d] for d in IDI_DIMS if d in dimv]
            rows.append([
                ind, city, q,
                f"{sum(tai)/len(tai):.6f}" if tai else "", len(tai),
                f"{sum(idi)/len(idi):.6f}" if idi else "", len(idi),
                *[f"{dimv[d]:.6f}" if d in dimv else "" for d in DIMS],
                sum(len(v) for v in used.values()),
                "|".join(sorted(m for v in used.values() for m in v)),
                "|".join(sorted(m for v in miss.values() for m in v)),
            ])
            if q == QUARTERS[0]:
                cov.append((ind, city, used, miss))
    return rows


HDR = ["industry", "city", "quarter", "TAI", "TAI_n_dims", "IDI", "IDI_n_dims",
       *DIMS.keys(), "n_indicators", "indicators_used", "indicators_imputed"]

summary = {}
for pv in PATENT_VARIANTS:
    Z["m8"], mu8, sd8 = zscore(M8[pv])
    tag = "（正文主口径）" if pv == MAIN_VARIANT else ""
    print(f"\n════ 指标8 口径 {pv}{tag}　z 参照集 n={len(M8[pv])} "
          f"mean={mu8:.4f} sd={sd8:.4f} ════")
    for ver in ("stock", "flow"):
        rows = build_index(ver)
        outs = [CLEAN / f"index_{ver}_{pv}_by_quarter.csv"]
        if pv == MAIN_VARIANT:
            outs.append(CLEAN / f"index_{ver}_by_quarter.csv")
        for out in outs:
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(HDR)
                w.writerows(rows)
        full = [r for r in rows if r[3] != "" and r[5] != ""]
        qs = sorted({r[2] for r in full})
        print(f"  ✅ {' / '.join('clean/'+o.name for o in outs)}　{len(rows)} 行；"
              f"TAI 与 IDI 同时有值 {len(full)} 格（{len(qs)} 期 {qs[0]}–{qs[-1]}）")
        agg = collections.defaultdict(list)
        for r in rows:
            if r[5] != "":
                agg[(r[0], r[1])].append(float(r[5]))
        summary[(pv, ver)] = {k: sum(v)/len(v) for k, v in agg.items()}
Z["m8"] = zscore(M8[MAIN_VARIANT])[0]


# ══ 显式的插补报告（critic 第 2 项）════════════════════
print("\n" + "═" * 74)
print("【插补报告】「维度内对可得指标取均值」是一种插补，不是中性处理")
print("═" * 74)
print("  它把缺失指标插补成『该单元自身其它指标的均值』，")
print("  系统性地让指标少的单元向自己已有的指标靠拢。以下如实列出各单元的实际构成：\n")
print(f"  {'单元':16s}{'IDI_创新 实际用到':34s}{'缺（被插补掉）'}")
cov_rows = []
for ind, city in UNITS:
    have = [m for m in DIMS["IDI_创新"]["stock"] if any((ind, city, q) in Z[m] for q in QUARTERS)]
    lack = [m for m in DIMS["IDI_创新"]["stock"] if m not in have]
    print(f"  {ind+'/'+city:16s}{' + '.join(have):34s}{' + '.join(lack) or '—'}")
    cov_rows.append([ind, city, "IDI_创新", "|".join(have), "|".join(lack), len(have)])
print("\n  ⚠️ 四种不同的指标组合 → 六个单元的 IDI_创新 **不是同一个量**。")
print("     跨单元比较请改用 clean/indicator_rank_by_quarter.csv（R-A）。")

out_cov = CLEAN / "index_coverage_report.csv"
with open(out_cov, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["industry", "city", "dimension", "indicators_used",
                "indicators_imputed", "n_used"])
    w.writerows(cov_rows)
print(f"\n✅ clean/{out_cov.name}")


# ══ 口径落差对照（仅量化影响幅度，不作强弱解释）════════
print("\n════ 三档专利口径的 IDI 单元均值落差 ════")
print(f"{'ver':6s}{'产业':9s}" + "".join(f"{v:>24s}" for v in PATENT_VARIANTS))
for ver in ("stock", "flow"):
    for ind in ("ai", "biomed", "fintech"):
        cells = []
        for pv in PATENT_VARIANTS:
            m = summary[(pv, ver)]
            hk, sg = m.get((ind, "hk")), m.get((ind, "sg"))
            cells.append(f"hk{hk:+.3f} sg{sg:+.3f}" if hk is not None and sg is not None
                         else " " * 22)
        print(f"{ver:6s}{ind:9s}" + "".join(f"{c:>24s}" for c in cells))
print("\n⚠️ 上表只量化口径选择的影响幅度。**不得**据此比较单元强弱——")
print("   六单元的 IDI 构成不同（见插补报告），相减不是同质量之差。")


# ══ prov ═══════════════════════════════════════════
PROV = {
    "manifests": ["openalex_author_quarters.csv.manifest.json",
                  "openalex_works_master.csv.manifest.json",
                  *[f"patents_families_by_quarter_company_{v}.csv.manifest.json"
                    for v in PATENT_VARIANTS]],
    "script": "scripts/index_build.py",
    "rules": {
        "R-A": "跨单元比较只在指标层做，用秩与方向；载体是 clean/indicator_rank_by_quarter.csv",
        "R-B": "指数只用于单元内时序；禁止跨单元相减",
        "R-C": "同一维度内时间属性统一；IDI 创新维三项均为流量（牌照已由累计改当季新增）",
    },
    "method": "冻结参照集 z-score（全部单元×全部可得季度）；维度内等权、维度间等权",
    "dims": {k: v["stock"] for k, v in DIMS.items()},
    "idi_state": "IDI 目前只实现创新维：商业维因 m11 退出而空，资本维无季度源。"
                 "IDI 列的数值等于创新维本身，未合成任何东西。",
    "m11_removed": "2026-09-18：窗口内 70 家 18A/18C 上市企业 69 家主运营不在香港，"
                   "实质运营口径下序列退化为阶跃直线，无时序信息。"
                   "见 docs/指标11_geo判定结果_2026-09-18.md",
    "imputation_disclosure": "「维度内对可得指标取均值」等于把缺失指标插补成该单元自身"
                             "其它指标的均值，不是中性处理。各单元实际构成见 "
                             "clean/index_coverage_report.csv",
    "comparability": "本文件仅可用于单元内时序（R-B）。跨单元比较见 indicator_rank_by_quarter.csv",
    "patent_variants": {"asis": "原样（附录口径）",
                        "ali_grp": "剔除阿里集团主体·两城同剔（正文主口径）",
                        "ali_ant_grp": "再加剔蚂蚁集团主体（敏感性口径）"},
    "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}
n_prov = 0
for pv in PATENT_VARIANTS:
    for ver in ("stock", "flow"):
        names = [f"index_{ver}_{pv}_by_quarter.csv"]
        if pv == MAIN_VARIANT:
            names.append(f"index_{ver}_by_quarter.csv")
        for nm in names:
            d = dict(PROV)
            d["file"] = f"clean/{nm}"
            d["patent_variant_of_this_file"] = pv + ("（正文主口径）" if pv == MAIN_VARIANT else "")
            d["scale_version_of_this_file"] = ("三年滚动存量" if ver == "stock"
                                               else "当季新增作者（流量）")
            d["manifests"] = [m for m in PROV["manifests"]
                              if "patents_families" not in m
                              or m.endswith(f"_{pv}.csv.manifest.json")]
            json.dump(d, open(CLEAN / (nm + ".prov.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            n_prov += 1

for nm, note in ((out_rank.name, "R-A 跨单元比较的唯一合法载体：指标层秩"),
                 (out_cov.name, "各单元维度实际构成与被插补指标")):
    d = dict(PROV)
    d["file"], d["comparability"] = f"clean/{nm}", note
    json.dump(d, open(CLEAN / (nm + ".prov.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    n_prov += 1
print(f"\n✅ 写出 {n_prov} 个 prov.json")
