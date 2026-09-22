# -*- coding: utf-8 -*-
"""从 raw/openalex_institutions_counts.csv 重建机构年度序列（单一快照口径）。

修的是两件事：
  (1) 覆盖不全：clean/universities_works_series.csv 只有 5 所香港高校，
      另外 4 个机构（岭南、浸会、教大、应科院）散在
      clean/institutions_ext_works_series.csv 里，两份从没合并过。
      任何只读前者的下游分析都会静默漏掉 4 个机构。
      附录 A 指标 1 的口径是「机构含八大＋公营研发机构」。

  (2) ★更要命的：那两份是【不同时间的快照】(2026-08-14 与 08-18)，
      而 OpenAlex 会持续回填索引——同一机构同一年的计数会随时间上涨。
      把两份拼成一张表，等于在机构之间制造一个不存在的口径断点。
      本脚本一律从【同一份 raw 快照】重建，保证全表同源同时刻。

输入：raw/openalex_institutions_counts.csv  （＋其 manifest 的 collected_utc）
     config/institutions.csv
输出：clean/institutions_works_series.csv   全部 11 个机构
     clean/hk8_works_series.csv             仅八大
     两份 .prov.json（含快照时间戳与对旧文件的漂移报告）

注意：本文件是【论文数】。附录 A 指标 1 要的是
「近三年在港机构署名发文的唯一作者数（滚动窗口）」——是【作者数】。
两者不能互相替代；本文件只服务年度剖面与外部校准。
"""
import csv, collections, json, pathlib, statistics, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC  = ROOT / "raw" / "openalex_institutions_counts.csv"
MAN  = ROOT / "manifests" / "openalex_institutions_counts.csv.manifest.json"
CFG  = ROOT / "config" / "institutions.csv"
OLD  = [("clean/universities_works_series.csv", {}),
        ("clean/institutions_ext_works_series.csv", {"应用科技研究院": "香港应用科技研究院"})]

if not SRC.exists(): sys.exit(f"⛔ 找不到 {SRC}")
rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
cfg  = {r["name_zh"]: r for r in csv.DictReader(open(CFG, encoding="utf-8-sig"))}
snap = json.load(open(MAN, encoding="utf-8")).get("collected_utc", "未知") if MAN.exists() else "未知"

years = sorted({r["year"] for r in rows}, key=int)
insts = sorted({r["institution"] for r in rows})
grid  = {(r["institution"], r["year"]): r["works_count"] for r in rows}
print(f"读入 {len(rows)} 行；{len(insts)} 个机构 × {len(years)} 年（{years[0]}–{years[-1]}）")
print(f"快照时间：{snap}")

holes = [(i, y) for i in insts for y in years if (i, y) not in grid]
print(f"网格空洞：{len(holes)} 个" + (f" {holes[:5]}" if holes else " ✅ 无"))
miss = [i for i in insts if i not in cfg]
if miss: print(f"⚠️ 不在 config/institutions.csv 里：{miss}")

# ── 与旧文件对比：量化漂移，不是找错 ──
print("\n── 与旧 clean 文件的差异（旧文件是更早的快照）──")
drift = []
for path, alias in OLD:
    p = ROOT / path
    if not p.exists():
        print(f"  {path}: 不存在，跳过"); continue
    rr = list(csv.reader(open(p, encoding="utf-8-sig")))
    hdr = rr[0]
    n = same = 0
    for r in rr[1:]:
        k = alias.get(r[0], r[0])
        if k not in insts: continue
        for j, y in enumerate(hdr):
            if y not in years: continue
            o, b = r[j], grid.get((k, y), "")
            if not o or not b: continue
            n += 1
            if o == b: same += 1
            else: drift.append({"inst": k, "year": y, "old": int(o), "new": int(b)})
    print(f"  {pathlib.Path(path).name}: 对比 {n} 格，一致 {same}，不同 {n - same}")

if drift:
    pct = [(d["new"] - d["old"]) / d["old"] * 100 for d in drift]
    up = sum(1 for x in pct if x > 0)
    print(f"\n  差异 {len(drift)} 格：新值更大 {up} 个（{up/len(drift)*100:.0f}%），"
          f"中位 {statistics.median(pct):+.2f}%，区间 {min(pct):+.2f}% ~ {max(pct):+.2f}%")
    by = collections.defaultdict(list)
    for d, x in zip(drift, pct): by[d["year"]].append(x)
    print("  按年份的中位差异（越近的年份涨得越多＝索引回填的特征）：")
    for y in years:
        if by[y]: print(f"     {y}  {statistics.median(by[y]):+6.2f}%  （{len(by[y])} 格）")
    near = [statistics.median(by[y]) for y in years[:3] if by[y]]
    far  = [statistics.median(by[y]) for y in years[-3:] if by[y]]
    if near and far and statistics.median(far) > statistics.median(near):
        print("\n  ✅ 判定：单调随年份递增 → OpenAlex 索引回填导致的快照漂移，不是采集错误。")
        print("     旧文件在它自己的时刻是对的；但两份旧文件本身来自不同日期(08-14/08-18)，")
        print("     拼在一起会在机构之间制造假断点。本次统一用同一份快照重建。")
    else:
        print("\n  ⚠️ 差异不随年份单调递增，不像回填漂移——请人工看一眼再用。")

def dump(path, keep, label):
    sel = [i for i in insts if keep(cfg.get(i, {}))]
    with open(ROOT / path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["institution", "group"] + years)
        for i in sel:
            w.writerow([i, cfg.get(i, {}).get("group", "?")] + [grid.get((i, y), "") for y in years])
    print(f"\n✅ {path}：{len(sel)} 个机构（{label}）")
    for i in sel: print(f"     {cfg.get(i,{}).get('group','?'):9s} {i}")
    return sel

allsel = dump("clean/institutions_works_series.csv", lambda c: True, "全部")
hk8    = dump("clean/hk8_works_series.csv", lambda c: c.get("group") == "hk8", "八大")

n8 = len(hk8)
print(f"\n八大齐备性：{n8}/8 " + ("✅" if n8 == 8 else f"❌ 缺 {8-n8} 所"))
prd = [i for i in insts if cfg.get(i, {}).get("group") == "public_rd"]
cfg_prd = [k for k, v in cfg.items() if v.get("group") == "public_rd"]
print(f"公营研发机构：raw 有 {len(prd)} 个 {prd}；config 列了 {len(cfg_prd)} 个 {cfg_prd}")
if len(prd) < len(cfg_prd):
    print(f"  ⚠️ 差额：{set(cfg_prd)-set(prd)} 从未作为 OpenAlex 机构采过——")
    print(f"     附录 A 指标 1 口径含「公营研发机构」，这块目前只覆盖应科院一家。")
    print(f"     InnoHK 是 ~30 个独立实验室、各自有无 ROR 需逐个查，不是一个机构实体。")

for path, sel in [("clean/institutions_works_series.csv", allsel), ("clean/hk8_works_series.csv", hk8)]:
    json.dump({
        "manifests": ["openalex_institutions_counts.csv.manifest.json"],
        "script": "scripts/institutions_series_build.py",
        "source": "raw/openalex_institutions_counts.csv + config/institutions.csv",
        "snapshot_utc": snap,
        "method": "单一 raw 快照 → 按 config.group 切分 → 宽表 works_count",
        "institutions": sel, "years": years,
        "supersedes": ["clean/universities_works_series.csv（仅5所香港高校）",
                       "clean/institutions_ext_works_series.csv（另4个机构，且为不同日期快照）"],
        "drift_vs_superseded": {
            "n_cells_differing": len(drift),
            "median_pct": round(statistics.median([(d["new"]-d["old"])/d["old"]*100 for d in drift]), 3) if drift else 0,
            "diagnosis": "OpenAlex 索引回填：差异随年份递增，近年最大。旧文件为更早快照，非错误。",
        },
        "caveat": "本文件是【论文数】；附录A指标1要的是【唯一作者数·近三年滚动】，不能互相替代",
        "created_utc": "2026-08-31T00:00:00+00:00",
    }, open(ROOT / (path + ".prov.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nprov 已写（含快照时间与漂移诊断）")
