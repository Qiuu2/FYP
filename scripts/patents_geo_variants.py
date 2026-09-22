# -*- coding: utf-8 -*-
r"""
patents_geo_variants.py —— 指标 8（企业专利族）的 geo_rule 双/三口径产出

背景（2026-09-12 拍板：方案③ 双版本）
    raw/patents_assignees.csv 暴露一个构念效度问题：
      · fintech/hk 824 个企业族里 709 个（86.0%）来自阿里系单一申请人
      · ai/hk      844 个里 455 个（53.9%）同样来自阿里系
    「香港金融科技的创新产出」这条序列，实际测到的是一家公司在香港的专利申请策略。
    提案 geo_rule：「仅计在香港有实质运营或研发的实体；『上市地功能』单列为稳健性口径」。

    方案③的决定是：两个口径都算、都发布；正文用剔除口径做主分析，附录放原样版，
    并把两者的落差本身作为一个结果报告（量化「产业产出对单一企业的依赖度」）。

    ⚠️ 必须同时承认的反论：阿里的专利是**真实发生在香港的申请**。剔除它等于采取
    「产业基础（本地研发能力）」而非「产业产出（本地法域登记量）」的视角。这是一个
    立场选择，不是数据清洗，必须写在方法章里。

三个嵌套口径（"两城同剔"：同一集团在港星两地同时剔除，否则口径不对称）
    asis          原样，不剔除任何申请人            —— 附录口径
    ali_grp       剔除阿里集团主体（hk 3 家 + sg 2 家）  —— 正文主口径
    ali_ant_grp   再加剔蚂蚁集团主体（sg 3 家，hk 0 家）  —— 敏感性口径

    为什么要第三档：蚂蚁集团与阿里集团是**不同法人集团**，但同属一个生态。
    只剔阿里而留下 ALIPAY LABS SINGAPORE（sg fintech 45 族）会造成新的不对称——
    把香港的金融科技巨头剔掉、把新加坡的留下，恰好朝着我们想要的方向。
    所以第三档必须一起报。

输入
    raw/patents_families_raw.csv                家族级底稿（賈贇，BigQuery）
    config/patents_assignee_sector.csv          申请人三分（人工复核产物）
    config/patents_assignee_geo_exclude.csv     剔除名单（本脚本的口径配置）

输出
    raw/patents_families_by_quarter_company_asis.csv
    raw/patents_families_by_quarter_company_ali_grp.csv
    raw/patents_families_by_quarter_company_ali_ant_grp.csv
    clean/patents_concentration_by_unit.csv     各单元申请人集中度（依赖度证据）
    clean/patents_concentration_by_unit.csv.prov.json

R1：本脚本不产生任何数据值，只在既有家族底稿上做集合过滤与计数。
用法：python scripts/patents_geo_variants.py
"""
import csv, json, collections, hashlib, pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, CFG, CLEAN = ROOT / "raw", ROOT / "config", ROOT / "clean"
INDUSTRIES = ("ai", "biomed", "fintech")
CITIES = ("hk", "sg")
QUARTERS = [f"{y}Q{q}" for y in range(2015, 2024) for q in range(1, 5)]  # 36 期
VARIANTS = {"asis": set(), "ali_grp": {"ali_grp"}, "ali_ant_grp": {"ali_grp", "ant_grp"}}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def parts(r):
    return [a.strip() for a in (r["assignees"] or "").split(" | ") if a.strip()]


rows = list(csv.DictReader(open(RAW / "patents_families_raw.csv", encoding="utf-8-sig")))
smap = {r["assignee"].strip(): r["sector"].strip()
        for r in csv.DictReader(open(CFG / "patents_assignee_sector.csv", encoding="utf-8-sig"))}
gx = list(csv.DictReader(open(CFG / "patents_assignee_geo_exclude.csv", encoding="utf-8-sig")))

# ── 剔除名单自检：名单里的每个申请人都必须在底稿里真实出现（防止名单写错字白剔）──
present = {(r["city"], a) for r in rows for a in parts(r)}
missing = [(g["city"], g["assignee"]) for g in gx if (g["city"], g["assignee"]) not in present]
if missing:
    raise SystemExit(f"⛔ 剔除名单里这些申请人在底稿中不存在（名字写错？）：{missing}")

# ── 对称性自检：ali_grp / ant_grp 两档都必须是「集团级」名单，不能只剔一个城市的同集团主体 ──
by_grp = collections.defaultdict(set)
for g in gx:
    by_grp[g["corporate_group"]].add(g["city"])
for grp, cs in sorted(by_grp.items()):
    print(f"  剔除名单·{grp}: 覆盖城市 {sorted(cs)}"
          + ("" if len(cs) == 2 else "  ← 该集团只在一个城市有申请人（底稿事实，非名单遗漏）"))

EXSET = {lvl: {(g["city"], g["assignee"]) for g in gx if g["exclude_level"] == lvl}
         for lvl in ("ali_grp", "ant_grp")}

# 只保留 company sector 的家族（指标 8 正式口径）
comp = [r for r in rows
        if "company" in {smap.get(a) for a in parts(r)}]
print(f"\n读入 {len(rows):,} 族次 → company 口径 {len(comp):,} 族次")

# ── 三个口径的季度序列 ──
series, drop_stat = {}, {}
for vname, lvls in VARIANTS.items():
    ex = set().union(*[EXSET[l] for l in lvls]) if lvls else set()
    keep, dropped, mixed = [], collections.Counter(), []
    for r in comp:
        cps = [a for a in parts(r) if smap.get(a) == "company"]
        hit = [a for a in cps if (r["city"], a) in ex]
        if hit and len(hit) == len(cps):
            dropped[(r["industry"], r["city"])] += 1
            continue
        if hit:   # 混合族：既有被剔主体、也有本地企业共同申请人 → 保留，如实记录
            mixed.append((r["industry"], r["city"], r["family_id"],
                          [a for a in cps if a not in [h for h in hit]]))
        keep.append(r)
    cnt = collections.Counter((r["industry"], r["city"], r["quarter"]) for r in keep)
    full = [[i, c, q, cnt.get((i, c, q), 0)] for i in INDUSTRIES for c in CITIES for q in QUARTERS]
    out = RAW / f"patents_families_by_quarter_company_{vname}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["industry", "city", "quarter", "patent_families"])
        w.writerows(full)
    series[vname] = {(i, c, q): n for i, c, q, n in full}
    drop_stat[vname] = (dropped, mixed)
    print(f"\n── 口径 {vname}（剔除 {len(ex)} 个申请人）→ raw/{out.name}")
    for i in INDUSTRIES:
        for c in CITIES:
            tot = sum(series[vname][(i, c, q)] for q in QUARTERS)
            base = sum(series["asis"][(i, c, q)] for q in QUARTERS)
            d = dropped[(i, c)]
            print(f"     {i:8s}/{c}  窗内 {tot:5d} 族"
                  f"（剔 {d:5d}，相对原样 {tot/base*100 if base else 0:5.1f}%）"
                  f"  季均 {tot/len(QUARTERS):5.1f}")
    if mixed:
        print(f"     混合族（被剔主体与本地企业共同申请，已保留）{len(mixed)} 个：")
        for m in mixed[:5]:
            print(f"        {m[0]}/{m[1]} family={m[2]} 共同申请人={m[3]}")

# ── asis 必须与既有入库文件完全一致（可复现性硬校验）──
old = RAW / "patents_families_by_quarter_company.csv"
if old.exists():
    a = sha256(old)
    b = sha256(RAW / "patents_families_by_quarter_company_asis.csv")
    print(f"\nasis vs 既有 _company.csv：{'✅ 字节完全一致' if a == b else '❌ 不一致 —— 口径漂移，先查清再用'}")
    if a != b:
        o = {(r["industry"], r["city"], r["quarter"]): int(r["patent_families"])
             for r in csv.DictReader(open(old, encoding="utf-8-sig"))}
        diff = [(k, o[k], series["asis"][k]) for k in o if o[k] != series["asis"].get(k)]
        print(f"   数值不同的格 {len(diff)} 个；前 5：{diff[:5]}")

# ── 集中度证据表（「依赖单一企业」的量化）──
conc = []
for i in INDUSTRIES:
    for c in CITIES:
        fams = [r for r in comp if r["industry"] == i and r["city"] == c]
        cc = collections.Counter()
        for r in fams:
            for a in parts(r):
                if smap.get(a) == "company":
                    cc[a] += 1
        n = len(fams)
        top = cc.most_common(1)[0] if cc else ("", 0)
        ali = sum(v for k, v in cc.items() if (c, k) in EXSET["ali_grp"])
        ant = sum(v for k, v in cc.items() if (c, k) in EXSET["ant_grp"])
        conc.append([i, c, n, top[0], top[1], f"{top[1]/n:.4f}" if n else "",
                     ali, f"{ali/n:.4f}" if n else "", ant, f"{ant/n:.4f}" if n else "",
                     len(cc)])
outc = CLEAN / "patents_concentration_by_unit.csv"
with open(outc, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["industry", "city", "company_families", "top1_assignee", "top1_families",
                "top1_share", "alibaba_grp_families", "alibaba_grp_share",
                "ant_grp_families", "ant_grp_share", "n_distinct_company_assignees"])
    w.writerows(conc)
print(f"\n✅ clean/{outc.name}（{len(conc)} 行）")
for r in conc:
    print(f"   {r[0]:8s}/{r[1]}  n={r[2]:5d}  top1 {float(r[5])*100:5.1f}%  "
          f"阿里系 {float(r[7])*100:5.1f}%  蚂蚁系 {float(r[9])*100:5.1f}%  «{r[3]}»")

json.dump({
    "inputs": ["raw/patents_families_raw.csv", "config/patents_assignee_sector.csv",
               "config/patents_assignee_geo_exclude.csv"],
    "manifests": ["patents_families_raw.csv.manifest.json"],
    "script": "scripts/patents_geo_variants.py",
    "method": "在家族级底稿上按申请人集合过滤并计数；不产生任何数据值（R1）",
    "variants": {k: sorted(v) or ["无剔除"] for k, v in VARIANTS.items()},
    "decision": "2026-09-12 邱正陽拍板方案③：正文主口径 ali_grp，附录 asis，敏感性 ali_ant_grp",
    "counter_argument": "阿里的专利是真实发生在香港的申请；剔除等于采取『产业基础』而非『产业产出』视角，须在方法章写明",
    "pending_human_review": "config/patents_assignee_geo_exclude.csv 的 substantive_rd_verdict 列仍为空——"
                            "『该主体在本地是否有实质研发』是事实判定，AI 不臆断（R1）",
    "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}, open(str(outc) + ".prov.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
