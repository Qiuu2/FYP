# -*- coding: utf-8 -*-
"""
qa_check.py —— 真实性规范 R2/R3/R6 的落地工具
================================================
clean/ 下每个分析用 CSV 必须有同名 .prov.json（溯源：由哪些 manifest 生成、用什么脚本）。
校验内容：溯源完整性 → 结构 schema → 数值合理性。任何 ❌ 都会以退出码 1 阻断。

用法：python scripts/qa_check.py
"""
import csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLEAN, MAN = ROOT / "clean", ROOT / "manifests"

# schema 登记表：文件名模式 → 规则（新数据类型在此登记后方可入 clean/）
SCHEMAS = {
    "_by_year.csv":    {"cols": ["year", "count"], "year_col": "year", "num_cols": ["count"]},
    "_by_quarter.csv": {"cols": ["quarter", "count"], "num_cols": ["count"]},
    "_events.csv":     {"cols": ["date", "entity", "event_type", "source_url"], "url_col": "source_url"},
    "_series.csv":     None,  # 宽表：首列为标识列，其余列须可数值化（如机构×年份）
    # mixed=True：既有文本标识列、又有数值列的表。只校验 num_cols 可数值化，
    # 不套「首列以外全部必须是数字」那条宽表规则（申请人名、口径标签本来就是文本）。
    "_by_unit.csv":    {"mixed": True,
                        "num_cols": ["company_families", "top1_families", "top1_share",
                                     "alibaba_grp_families", "alibaba_grp_share",
                                     "ant_grp_families", "ant_grp_share",
                                     "n_distinct_company_assignees"]},
    "_compare.csv":    {"mixed": True,
                        "num_cols": ["hk_mean_own_window", "hk_n_own", "sg_mean_own_window",
                                     "sg_n_own", "delta_own_window", "hk_mean_common",
                                     "sg_mean_common", "n_common_quarters",
                                     "delta_common_window"]},
}
YEAR_RANGE = (2010, 2026)

def check_file(p: Path):
    errs = []
    prov = p.with_suffix(p.suffix + ".prov.json")
    if not prov.exists():
        return [f"缺溯源文件 {prov.name}（clean 数据必须能回指 manifest）"]
    meta = json.loads(prov.read_text(encoding="utf-8"))
    if not meta.get("manifests"):
        errs.append(f"{prov.name}: manifests 列表为空")
    for m in meta.get("manifests", []):
        if not (MAN / m).exists():
            errs.append(f"{prov.name}: 引用的 manifest 不存在 → {m}")
    if not meta.get("script"):
        errs.append(f"{prov.name}: 未记录生成脚本")

    rule = next((r for suf, r in SCHEMAS.items() if p.name.endswith(suf)), "UNREG")
    if rule == "UNREG":
        return errs + [f"{p.name}: 文件名不匹配任何已登记 schema（先在 qa_check.py 登记）"]
    with open(p, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return errs + [f"{p.name}: 空文件"]
    cols = list(rows[0].keys())
    if isinstance(rule, dict) and rule.get("mixed"):
        miss = [c for c in rule["num_cols"] if c not in cols]
        if miss:
            errs.append(f"{p.name}: 缺数值列 {miss}")
        for i, r in enumerate(rows, 2):
            for c in rule["num_cols"]:
                v = (r.get(c) or "").strip()
                if not v:
                    continue
                try:
                    float(v)
                except ValueError:
                    errs.append(f"{p.name}: 第{i}行 {c} 非数值 {v!r}")
        return errs
    if rule is None:  # 宽表
        for r in rows:
            for c in cols[1:]:
                v = (r[c] or "").strip()
                if v and not v.replace(".", "", 1).replace("-", "", 1).isdigit():
                    errs.append(f"{p.name}: 非数值单元格 {c}={v!r}（行首={r[cols[0]]!r}）")
        return errs
    missing = [c for c in rule["cols"] if c not in cols]
    if missing:
        errs.append(f"{p.name}: 缺列 {missing}")
        return errs
    seen = set()
    for i, r in enumerate(rows, 2):
        key = tuple(r[c] for c in rule["cols"][:2])
        if key in seen:
            errs.append(f"{p.name}: 第{i}行重复键 {key}")
        seen.add(key)
        if "year_col" in rule:
            y = r[rule["year_col"]]
            if not (y.isdigit() and YEAR_RANGE[0] <= int(y) <= YEAR_RANGE[1]):
                errs.append(f"{p.name}: 第{i}行年份越界 {y!r}")
        for c in rule.get("num_cols", []):
            v = (r[c] or "").strip()
            if not v.lstrip("-").isdigit():
                errs.append(f"{p.name}: 第{i}行 {c} 非整数 {v!r}")
            elif int(v) < 0:
                errs.append(f"{p.name}: 第{i}行 {c} 为负 {v}")
        if "url_col" in rule and not (r[rule["url_col"]] or "").startswith("http"):
            errs.append(f"{p.name}: 第{i}行缺来源 URL（R1：事件类数据逐条带源）")
    return errs

def main():
    files = [p for p in sorted(CLEAN.rglob("*.csv"))]
    all_errs, ok = [], 0
    for p in files:
        e = check_file(p)
        if e:
            all_errs += e
        else:
            ok += 1
            print(f"✅ {p.relative_to(ROOT)}")
    print(f"\nclean/ 共 {len(files)} 个 CSV，通过 {ok} 个")
    if all_errs:
        print("❌ 未通过：")
        [print("  -", x) for x in all_errs]
        sys.exit(1)
    if files:
        print("✅ QA 全部通过")

if __name__ == "__main__":
    main()
