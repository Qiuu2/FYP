# -*- coding: utf-8 -*-
"""步骤① 效度关一：指标层秩比对（2026-09-22 按 R-A 重写）

═══ 这个文件被重写了两次，先读这段再看代码 ═══

【第一次问题·2026-09-12 独立复查】
    旧版用 index_*_by_quarter.csv 的 TAI/IDI 做跨单元相减。
    六个单元的 IDI 由不同指标集构成，相减不是同质量之差。
    旧版的 avg() 还按**各单元自身可得季度**取均值——窗口没对齐，
    等于拿香港的某些季度去和新加坡的另一些季度比。

【第二次问题·2026-09-18 文献复核（陈于嘉）】
    关一要检验「实测剖面重现三条已知格局」。回查提案 §3.1 的引证后：

      格局1 金融科技双高    → 文献（InvestHK 2025）只说它是**公司数最大**的板块，
                              「没有提到人才规模或产出」。双高零出处。
      格局2 生医高研究低商业 → 文献（BioPharma APAC 2024 访谈）有「高研究」
                              （ITF 847 项目/17.6 亿港元、HKSTP 14,000 研发人员），
                              但**没有提及「低商业化」**——原文谈的全是「支持商业化」。
      格局3 AI 人才陡升在前  → 两份文献（HKPC&HIEBS 2024；PoD 2025）都是**剖面**命题
                              （研究强/商业化人才不足），**没有任何时序分析**。

    三条格局**全部无文献支持**。已知组效度检验的前提是组间差异由独立证据确立，
    这个前提不成立。

【因此本文件的定位改了】
    关一**降级为弱证据**，不再作为「指数是否有效」的判据。
    它现在只做一件事：**如实呈现指标层的秩模式**，不下「重现/未重现」的判定。
    效度论证的重心移到关二（外部校准）与关三（判别效度）。

    ⚠️ 这不是「没通过所以改标准」——判定表述与文献命题不对齐是提案文本内部的问题，
       即使当初判「通过」，那个「通过」同样没有意义。

═══ 口径规则 ═══
    R-A  只读 clean/indicator_rank_by_quarter.csv（六单元齐备的四个指标）
    窗口 所有参与比较的单元取**交集**，不再各取各的
"""
import csv, collections, pathlib, statistics as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLEAN = ROOT / "clean"
UNITS = [("ai", "hk"), ("ai", "sg"), ("biomed", "hk"), ("biomed", "sg"),
         ("fintech", "hk"), ("fintech", "sg")]
IND_LABEL = {"m1_stock": "研究者存量", "m1_flow": "新增作者", "m4": "前10%高引占比",
             "m7": "国际合著比例", "m8": "企业专利族"}

rows = list(csv.DictReader(open(CLEAN / "indicator_rank_by_quarter.csv", encoding="utf-8-sig")))
by = collections.defaultdict(dict)
for r in rows:
    by[(r["indicator"], r["quarter"])][(r["industry"], r["city"])] = r

print("═" * 76)
print("效度关一 · 指标层秩模式（R-A）　—— 只呈现，不判定")
print("═" * 76)
print("三条已知格局经文献复核后全部无出处（见文件头），故本表不给「重现/未重现」结论。\n")

# ── 每个指标的可用窗口（六单元交集，秩表生成时已保证六单元齐全）──
windows = {}
for ind in IND_LABEL:
    qs = sorted({q for (i, q) in by if i == ind})
    windows[ind] = qs
print("── 各指标的可比窗口（六单元交集）──")
for ind, qs in windows.items():
    print(f"  {ind:10s} {IND_LABEL[ind]:12s} {len(qs):>2} 期  {qs[0]}–{qs[-1]}" if qs
          else f"  {ind:10s} 无可比季度")

# ── 跨全部指标的共同窗口：任何多指标联合陈述都必须落在这里 ──
common = sorted(set.intersection(*[set(v) for v in windows.values() if v]))
print(f"\n  ★ 五指标共同窗口：{len(common)} 期  {common[0]}–{common[-1]}")
print("    任何同时引用多个指标的陈述，只能在这个窗口内做。")

# ── 香港三产业的秩模式（文献命题讲的是香港产业间对比）──
print("\n" + "─" * 76)
print("香港三产业 · 各指标的平均秩（1 = 该指标上最高；窗口 = 该指标自身六单元交集）")
print("─" * 76)
print(f"{'指标':22s}{'ai/hk':>9s}{'biomed/hk':>11s}{'fintech/hk':>12s}{'期数':>6s}")
hk_rank = {}
for ind, qs in windows.items():
    if not qs:
        continue
    acc = collections.defaultdict(list)
    for q in qs:
        for (i, c), r in by[(ind, q)].items():
            if c == "hk" and r["rank_hk3"]:
                acc[i].append(float(r["rank_hk3"]))
    m = {i: st.mean(v) for i, v in acc.items()}
    hk_rank[ind] = m
    print(f"{ind+' '+IND_LABEL[ind]:22s}"
          + "".join(f"{m.get(i, float('nan')):>9.2f}" if i == "ai" else
                   f"{m.get(i, float('nan')):>11.2f}" if i == "biomed" else
                   f"{m.get(i, float('nan')):>12.2f}" for i in ("ai", "biomed", "fintech"))
          + f"{len(qs):>6d}")

# ── 秩的稳定性：只看均值会掩盖「靠少数几期撑起来」──
print("\n" + "─" * 76)
print("秩的稳定性 · 香港三产业中排第 1 的期数占比")
print("─" * 76)
print(f"{'指标':22s}{'ai/hk':>9s}{'biomed/hk':>11s}{'fintech/hk':>12s}")
for ind, qs in windows.items():
    if not qs:
        continue
    top = collections.Counter()
    for q in qs:
        for (i, c), r in by[(ind, q)].items():
            if c == "hk" and r["rank_hk3"] and float(r["rank_hk3"]) == 1:
                top[i] += 1
    print(f"{ind+' '+IND_LABEL[ind]:22s}"
          + "".join(f"{top[i]/len(qs)*100:>8.0f}%" if i == "ai" else
                   f"{top[i]/len(qs)*100:>10.0f}%" if i == "biomed" else
                   f"{top[i]/len(qs)*100:>11.0f}%" for i in ("ai", "biomed", "fintech")))

# ── 新加坡侧：不设预期，用作判别效度对照 ──
print("\n" + "─" * 76)
print("新加坡三产业 · 平均秩　—— 文献只讲香港，此处**不设预期**")
print("─" * 76)
print(f"{'指标':22s}{'ai/sg':>9s}{'biomed/sg':>11s}{'fintech/sg':>12s}")
sg_rank = {}
for ind, qs in windows.items():
    if not qs:
        continue
    acc = collections.defaultdict(list)
    for q in qs:
        for (i, c), r in by[(ind, q)].items():
            if c == "sg" and r["rank_sg3"]:
                acc[i].append(float(r["rank_sg3"]))
    m = {i: st.mean(v) for i, v in acc.items()}
    sg_rank[ind] = m
    print(f"{ind+' '+IND_LABEL[ind]:22s}"
          + "".join(f"{m.get(i, float('nan')):>9.2f}" if i == "ai" else
                   f"{m.get(i, float('nan')):>11.2f}" if i == "biomed" else
                   f"{m.get(i, float('nan')):>12.2f}" for i in ("ai", "biomed", "fintech")))

print("\n★ 港星秩模式是否一致，是判别效度的信息：")
for ind in windows:
    if ind not in hk_rank or ind not in sg_rank:
        continue
    oh = sorted(hk_rank[ind], key=lambda i: hk_rank[ind][i])
    os_ = sorted(sg_rank[ind], key=lambda i: sg_rank[ind][i])
    same = oh == os_
    print(f"  {ind:10s} 港 {'>'.join(oh):24s} 星 {'>'.join(os_):24s} "
          + ("→ 一致：该模式可能是**学科层面的普遍现象**，不是香港特征"
             if same else "→ 不一致：该模式在两城不同"))

# ── 港星同产业直接对比（同指标同参照集，合法）──
print("\n" + "─" * 76)
print("港星同产业对比 · 同一指标的 z 差（香港 − 新加坡），**共同窗口**")
print("─" * 76)
print(f"{'指标':22s}{'ai':>10s}{'biomed':>10s}{'fintech':>10s}{'期数':>6s}")
for ind, qs in windows.items():
    if not qs:
        continue
    cells = []
    for i in ("ai", "biomed", "fintech"):
        d = [float(by[(ind, q)][(i, "hk")]["z"]) - float(by[(ind, q)][(i, "sg")]["z"])
             for q in qs if (i, "hk") in by[(ind, q)] and (i, "sg") in by[(ind, q)]]
        cells.append(st.mean(d) if d else float("nan"))
    print(f"{ind+' '+IND_LABEL[ind]:22s}" + "".join(f"{c:>+10.3f}" for c in cells)
          + f"{len(qs):>6d}")
print("\n  这一组是合法的跨单元比较：同一个指标、同一个参照集、同一个窗口。")

print("\n" + "═" * 76)
print("本表不给效度判定。关一已降级为弱证据，效度论证见关二（外部校准）与关三（判别效度）。")
print("═" * 76)
