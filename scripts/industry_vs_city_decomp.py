# -*- coding: utf-8 -*-
"""产业效应 vs 城市效应：RQ1 的方法论前提检验（2026-09-22）

═══ 为什么要跑这个 ═══

2026-09-22 重写关一后发现：五个指标里有四个，香港与新加坡的**产业排序完全相同**。

    m1_stock  港 biomed>ai>fintech    星 biomed>ai>fintech
    m1_flow   港 biomed>ai>fintech    星 biomed>ai>fintech
    m4        港 fintech>ai>biomed    星 fintech>ai>biomed
    m8        港 biomed>ai>fintech    星 biomed>ai>fintech
    m7        港 biomed>fintech>ai    星 ai>fintech>biomed   ← 唯一不同

如果两个城市的产业排序一样，那这个排序测的多半是**学科本身的性质**
（生医论文天然比金融科技多），不是城市的特征。

这直接决定 RQ1 能不能成立。RQ1 问：
    「三产业的 TAI–IDI 剖面呈现何种匹配或错配结构？与新加坡相比处于何种相对位置？」
这个问题的答案**完全落在「产业 × 城市」的交互项上**——
「香港的 AI 相对香港的生医」与「新加坡的 AI 相对新加坡的生医」之差。
若交互项接近 0，RQ1 就没有可答的内容。

═══ 三件事 ═══
  ① 方差分解：把每个指标的变异拆成 产业 / 城市 / 交互 / 时间 四块
  ② 逐期秩相关：港星产业排序的 Spearman ρ 分布（不只看均值）
  ③ 去学科基准后的剖面：减掉「该产业两城均值」，剩下的才是城市特征

R1：只读 clean/indicator_rank_by_quarter.csv，不产生任何数据值。
"""
import csv, collections, math, pathlib, statistics as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLEAN = ROOT / "clean"
INDS = ("ai", "biomed", "fintech")
CITIES = ("hk", "sg")
LABEL = {"m1_stock": "研究者存量", "m1_flow": "新增作者", "m4": "前10%高引占比",
         "m7": "国际合著比例", "m8": "企业专利族"}

rows = list(csv.DictReader(open(CLEAN / "indicator_rank_by_quarter.csv", encoding="utf-8-sig")))
data = collections.defaultdict(dict)          # indicator -> (ind,city,q) -> z
for r in rows:
    data[r["indicator"]][(r["industry"], r["city"], r["quarter"])] = float(r["z"])

print("═" * 78)
print("产业效应 vs 城市效应 —— RQ1 的方法论前提检验")
print("═" * 78)

# ════════════════════════════════════════════════════
# ① 方差分解
# ════════════════════════════════════════════════════
print("\n① 方差分解　z = 总均值 + 产业效应 + 城市效应 + 交互 + 时间残差")
print("─" * 78)
print(f"{'指标':20s}{'产业':>9s}{'城市':>9s}{'交互':>9s}{'时间':>9s}{'期数':>6s}")

decomp = {}
for mk, d in data.items():
    qs = sorted({q for (_, _, q) in d})
    cell = {(i, c): [d[(i, c, q)] for q in qs if (i, c, q) in d] for i in INDS for c in CITIES}
    m_ic = {k: st.mean(v) for k, v in cell.items() if v}
    if len(m_ic) < 6:
        continue
    grand = st.mean(m_ic.values())
    m_i = {i: st.mean([m_ic[(i, c)] for c in CITIES]) for i in INDS}
    m_c = {c: st.mean([m_ic[(i, c)] for i in INDS]) for c in CITIES}
    alpha = {i: m_i[i] - grand for i in INDS}
    beta = {c: m_c[c] - grand for c in CITIES}
    gamma = {(i, c): m_ic[(i, c)] - m_i[i] - m_c[c] + grand for i in INDS for c in CITIES}

    n_t = len(qs)
    ss_ind = len(CITIES) * n_t * sum(a * a for a in alpha.values())
    ss_city = len(INDS) * n_t * sum(b * b for b in beta.values())
    ss_int = n_t * sum(g * g for g in gamma.values())
    ss_time = sum((v - m_ic[k]) ** 2 for k, vs in cell.items() for v in vs)
    tot = ss_ind + ss_city + ss_int + ss_time
    p = {k: 100 * v / tot for k, v in
         (("ind", ss_ind), ("city", ss_city), ("int", ss_int), ("time", ss_time))}
    decomp[mk] = dict(p, gamma=gamma, n_t=n_t)
    print(f"{mk+' '+LABEL[mk]:20s}{p['ind']:>8.1f}%{p['city']:>8.1f}%"
          f"{p['int']:>8.1f}%{p['time']:>8.1f}%{n_t:>6d}")

avg_int = st.mean([v["int"] for v in decomp.values()])
avg_ind = st.mean([v["ind"] for v in decomp.values()])
print(f"\n  平均：产业 {avg_ind:.1f}%　交互 {avg_int:.1f}%")
print("  ★ 交互项 = 「城市特有的产业格局」= RQ1 唯一可答的部分。")

# ════════════════════════════════════════════════════
# ② 逐期秩相关
# ════════════════════════════════════════════════════
print("\n\n② 逐期港星产业排序的 Spearman ρ（n=3，取值只能是 +1 / +0.5 / −0.5 / −1）")
print("─" * 78)
print(f"{'指标':20s}{'均值':>8s}{'ρ=+1 占比':>11s}{'ρ≤0 占比':>11s}{'期数':>6s}")


def spearman3(a, b):
    """三个产业的秩相关。a,b 是 {产业: 值}。"""
    ra = {k: i for i, k in enumerate(sorted(a, key=lambda x: -a[x]))}
    rb = {k: i for i, k in enumerate(sorted(b, key=lambda x: -b[x]))}
    dsq = sum((ra[k] - rb[k]) ** 2 for k in ra)
    return 1 - 6 * dsq / (3 * (9 - 1))


for mk, d in data.items():
    qs = sorted({q for (_, _, q) in d})
    rhos = []
    for q in qs:
        hk = {i: d[(i, "hk", q)] for i in INDS if (i, "hk", q) in d}
        sg = {i: d[(i, "sg", q)] for i in INDS if (i, "sg", q) in d}
        if len(hk) == 3 and len(sg) == 3:
            rhos.append(spearman3(hk, sg))
    if not rhos:
        continue
    print(f"{mk+' '+LABEL[mk]:20s}{st.mean(rhos):>+8.2f}"
          f"{sum(1 for r in rhos if r == 1)/len(rhos)*100:>10.0f}%"
          f"{sum(1 for r in rhos if r <= 0)/len(rhos)*100:>10.0f}%{len(rhos):>6d}")

# ════════════════════════════════════════════════════
# ③ 去学科基准后的剖面
# ════════════════════════════════════════════════════
print("\n\n③ 去学科基准后的剖面　γ = 单元均值 − 产业均值 − 城市均值 + 总均值")
print("─" * 78)
print("   这一步把「生医论文天然比金融科技多」这类学科性质减掉了，")
print("   剩下的 γ 才是「这个城市在这个产业上相对于自身平均水平的特异表现」。\n")
print(f"{'指标':20s}" + "".join(f"{i+'/'+c:>12s}" for i in INDS for c in CITIES))
for mk in data:
    if mk not in decomp:
        continue
    g = decomp[mk]["gamma"]
    print(f"{mk+' '+LABEL[mk]:20s}" + "".join(f"{g[(i,c)]:>+12.3f}" for i in INDS for c in CITIES))

print("\n   注意 γ 的结构：同一产业的两城 γ 必然大小相等、符号相反（这是分解的恒等式），")
print("   所以每个指标实际只有 3 个独立的数，不是 6 个。")

print(f"\n{'指标':20s}{'|γ| 最大的产业':>18s}{'γ 幅度':>10s}{'交互占比':>10s}")
for mk in data:
    if mk not in decomp:
        continue
    g = decomp[mk]["gamma"]
    per_ind = {i: abs(g[(i, "hk")]) for i in INDS}
    top = max(per_ind, key=per_ind.get)
    print(f"{mk+' '+LABEL[mk]:20s}{top+'（港'+('高' if g[(top,'hk')]>0 else '低')+'）':>18s}"
          f"{per_ind[top]:>10.3f}{decomp[mk]['int']:>9.1f}%")

# ════════════════════════════════════════════════════
# 判读
# ════════════════════════════════════════════════════
print("\n" + "═" * 78)
print("判读")
print("═" * 78)
strong = [mk for mk, v in decomp.items() if v["int"] >= 10]
weak = [mk for mk, v in decomp.items() if v["int"] < 10]
print(f"  交互占比 ≥10% 的指标（携带城市信息）：{', '.join(strong) if strong else '无'}")
print(f"  交互占比 <10% 的指标（主要是学科性质）：{', '.join(weak) if weak else '无'}")
print()
if avg_int < 10:
    print("  → 平均交互占比不足 10%：**产业排序主要由学科性质决定**。")
    print("     RQ1 若按「谁排第几」来答，答的是学科常识，不是香港的产业特征。")
    print("     可行的修法：RQ1 改问 γ（去学科基准后的偏离），而不是原始水平或秩。")
else:
    print("  → 交互项有实质份额，RQ1 的剖面比较有可答内容，但仍应以 γ 而非原始秩呈现。")
