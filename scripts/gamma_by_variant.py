# -*- coding: utf-8 -*-
"""剔除阿里系后 RQ1 结论会变成什么？——三档口径下的 γ 对照（2026-09-22）

═══ 为什么跑这个 ═══

创新维的 γ(fintech/hk) = +0.312 是 RQ1 两条实质结论之一，
但该格 86.2% 来自 ALIBABA GROUP SERVICES LTD（香港，1052 族）。

该主体在阿里 FY2024 年报 p.74 自述为「our treasury center in Hong Kong」，
香港企业财资中心的三项法定合资格活动均不含研发。

若判定其无实质研发，m8 须按 ali_grp 档重算。本脚本给出三档对照：

    asis        原样（不剔除任何主体）
    ali_grp     剔除阿里集团系（香港侧）
    ali_ant_grp 剔除阿里+蚂蚁系（两城同剔，R-geo）

═══ 方法 ═══
沿用 industry_vs_city_decomp.py 的分解：
    z = 总均值 + 产业效应 + 城市效应 + 交互 + 时间残差
    γ = 单元均值 − 产业均值 − 城市均值 + 总均值

z 标准化以「全部单元×全部季度」为冻结参照集（R-A），每档各自标准化。

R1：只读既有清洁序列，不产生任何数据值。
"""
import csv, collections, pathlib, statistics as st

ROOT = pathlib.Path("/mnt/user-data/uploads/FYP/data_repo")
INDS = ("ai", "biomed", "fintech")
CITIES = ("hk", "sg")


def load(path, valcol, keycol="quarter"):
    """读成 {(industry, city, quarter): float}，空值跳过。"""
    out = {}
    with open(ROOT / path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            v = r.get(valcol, "")
            if v in ("", None):
                continue
            try:
                # 论文类序列的金融科技代号是 fintech_kw，专利类是 fintech。
                # 统一归一化，否则六单元对不上（2026-09-22 实测发现）。
                ind = "fintech" if r["industry"] == "fintech_kw" else r["industry"]
                out[(ind, r["city"], r[keycol])] = float(v)
            except ValueError:
                continue
    return out


def zscore(series):
    """冻结参照集 = 全部单元×全部季度。"""
    vals = list(series.values())
    if len(vals) < 2:
        return {}
    mu = st.mean(vals)
    sd = st.pstdev(vals)
    if sd == 0:
        return {}
    return {k: (v - mu) / sd for k, v in series.items()}


def decomp(z):
    """返回 (占比字典, gamma字典, 期数)。仅在六单元齐备时计算。"""
    qs = sorted({q for (_, _, q) in z})
    cell = {(i, c): [z[(i, c, q)] for q in qs if (i, c, q) in z]
            for i in INDS for c in CITIES}
    m_ic = {k: st.mean(v) for k, v in cell.items() if v}
    if len(m_ic) < 6:
        return None, None, 0
    grand = st.mean(m_ic.values())
    m_i = {i: st.mean([m_ic[(i, c)] for c in CITIES]) for i in INDS}
    m_c = {c: st.mean([m_ic[(i, c)] for i in INDS]) for c in CITIES}
    alpha = {i: m_i[i] - grand for i in INDS}
    beta = {c: m_c[c] - grand for c in CITIES}
    gamma = {(i, c): m_ic[(i, c)] - m_i[i] - m_c[c] + grand
             for i in INDS for c in CITIES}
    n_t = len(qs)
    ss_ind = len(CITIES) * n_t * sum(a * a for a in alpha.values())
    ss_city = len(INDS) * n_t * sum(b * b for b in beta.values())
    ss_int = n_t * sum(g * g for g in gamma.values())
    ss_time = sum((v - m_ic[k]) ** 2 for k, vs in cell.items() for v in vs)
    tot = ss_ind + ss_city + ss_int + ss_time
    p = {"ind": 100 * ss_ind / tot, "city": 100 * ss_city / tot,
         "int": 100 * ss_int / tot, "time": 100 * ss_time / tot}
    return p, gamma, n_t


print("=" * 78)
print("剔除阿里系后 RQ1 结论会变成什么 —— 三档口径对照")
print("=" * 78)

# ── 不受阿里影响的三个指标，先算一次作为对照 ────────────────
fixed = {
    "m1_stock 研究者存量": zscore(load("clean/researchers_stock_by_quarter.csv", "unique_authors")),
    "m4 前10%高引占比":    zscore(load("clean/top10pct_by_quarter.csv", "top10_share", "period")),
    "m7 国际合著比例":      zscore(load("clean/intl_collab_by_quarter.csv", "intl_share")),
}

print("\n【对照】不含专利的三个指标（不受阿里判定影响）")
print("-" * 78)
print(f"{'指标':22s}{'产业':>8s}{'交互':>8s}{'γ ai/hk':>11s}{'γ bio/hk':>11s}{'γ fin/hk':>11s}{'期数':>6s}")
for name, z in fixed.items():
    p, g, n = decomp(z)
    if not p:
        print(f"{name:22s}  六单元不齐，跳过")
        continue
    print(f"{name:22s}{p['ind']:>7.1f}%{p['int']:>7.1f}%"
          f"{g[('ai','hk')]:>+11.3f}{g[('biomed','hk')]:>+11.3f}"
          f"{g[('fintech','hk')]:>+11.3f}{n:>6d}")

# ── m8 三档 ────────────────────────────────────────────────
VARIANTS = [
    ("asis",        "原样（不剔除）",              "raw/patents_families_by_quarter_company_asis.csv"),
    ("ali_grp",     "剔除阿里集团系",              "raw/patents_families_by_quarter_company_ali_grp.csv"),
    ("ali_ant_grp", "剔除阿里+蚂蚁系（两城同剔）", "raw/patents_families_by_quarter_company_ali_ant_grp.csv"),
]

print("\n\n【核心】m8 企业专利族 —— 三档口径")
print("-" * 78)
print(f"{'口径':30s}{'产业':>8s}{'城市':>8s}{'交互':>8s}{'期数':>6s}")
res = {}
for key, label, path in VARIANTS:
    z = zscore(load(path, "patent_families"))
    p, g, n = decomp(z)
    res[key] = (p, g, n, label)
    if p:
        print(f"{label:30s}{p['ind']:>7.1f}%{p['city']:>7.1f}%{p['int']:>7.1f}%{n:>6d}")

print(f"\n{'口径':30s}{'γ ai/hk':>12s}{'γ biomed/hk':>14s}{'γ fintech/hk':>14s}")
for key, label, _ in VARIANTS:
    p, g, n, _ = res[key]
    if g:
        print(f"{label:30s}{g[('ai','hk')]:>+12.3f}"
              f"{g[('biomed','hk')]:>+14.3f}{g[('fintech','hk')]:>+14.3f}")

# ── 判读 ───────────────────────────────────────────────────
print("\n" + "=" * 78)
print("判读")
print("=" * 78)

g_asis = res["asis"][1][("fintech", "hk")]
g_ali = res["ali_grp"][1][("fintech", "hk")]
g_ant = res["ali_ant_grp"][1][("fintech", "hk")]

print(f"\n创新维 γ(fintech/hk)：")
print(f"  原样            {g_asis:+.3f}")
print(f"  剔阿里          {g_ali:+.3f}   （变动 {g_ali-g_asis:+.3f}）")
print(f"  剔阿里+蚂蚁     {g_ant:+.3f}   （变动 {g_ant-g_asis:+.3f}）")

print()
for key, label, _ in VARIANTS[1:]:
    g = res[key][1][("fintech", "hk")]
    if g > 0.15:
        print(f"  {label}：γ 仍为正且有实质幅度 → 结论方向不变")
    elif g > 0:
        print(f"  {label}：γ 转为微弱正值 → 结论显著削弱，不足以支撑实质陈述")
    else:
        print(f"  {label}：γ 转为负值 → **结论方向反转**")

# m7 是否仍是最大的 γ
g_m7 = decomp(fixed["m7 国际合著比例"])[1]
if g_m7 is None:
    print("\n  m7 六单元不齐，无法比较。")
    raise SystemExit
m7_max = max(abs(g_m7[(i, "hk")]) for i in INDS)
print(f"\n网络维 m7 的最大 |γ| = {m7_max:.3f}（不受阿里判定影响）")
if abs(g_ali) < m7_max:
    print("  → 剔除后，m7 成为唯一具实质幅度的城市特异性发现。")
