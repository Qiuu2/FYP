# -*- coding: utf-8 -*-
"""
resolve_ids.py —— 把 boundary_rules_v1.yaml 与 institutions.csv 里的 pending ID 解析为候选
================================================================================
设计原则（吸取 2026-08-14 实测教训：ROR 模糊检索会把「岭南大学」匹配成港大）：
  本脚本【只产出候选文件】，绝不自动写回正式配置——人工确认后手动搬运，留痕于 git。

用法：
  export OPENALEX_KEY=...   # 免费注册
  python scripts/resolve_ids.py ror        # 解析 institutions.csv 中 pending 的 ROR（affiliation 匹配模式）
  python scripts/resolve_ids.py openalex   # 解析 venues/journals/subfields/fields 的 OpenAlex ID
产出：
  config/_candidates_ror.csv / config/_candidates_openalex.csv（含候选、佐证字段、确认列）
"""
import csv, os, sys, time
from pathlib import Path
import requests, yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config"
KEY = os.environ.get("OPENALEX_KEY", "")
MAILTO = os.environ.get("OPENALEX_MAILTO", "team@example.edu")

def oa(path, **params):
    params.setdefault("mailto", MAILTO)
    if KEY:
        params["api_key"] = KEY
    r = requests.get(f"https://api.openalex.org/{path}", params=params, timeout=30)
    r.raise_for_status()
    time.sleep(1)
    return r.json()

def resolve_ror():
    rows = list(csv.DictReader(open(CFG / "institutions.csv", encoding="utf-8-sig")))
    out = []
    for row in rows:
        if row["verify_status"] not in ("pending", "resolved_pending_review"):
            continue
        name = row["name_en"] or row["name_zh"]
        # affiliation 匹配模式：ROR 官方推荐用于机构名消歧，返回 chosen 标记
        r = requests.get("https://api.ror.org/organizations",
                         params={"affiliation": name}, timeout=30).json()
        for item in r.get("items", [])[:3]:
            org = item["organization"]
            out.append({"query": name, "candidate_ror": org["id"].split("/")[-1],
                        "candidate_name": org["name"],
                        "country": org.get("country", {}).get("country_name", ""),
                        "chosen_by_api": item.get("chosen", False),
                        "score": round(item.get("score", 0), 3),
                        "human_confirm(填Y后搬入institutions.csv)": ""})
        time.sleep(1)
    _write(CFG / "_candidates_ror.csv", out)

def resolve_openalex():
    rules = yaml.safe_load(open(CFG / "boundary_rules_v1.yaml", encoding="utf-8"))
    out = []
    # 1) 分类学：subfields / fields —— 直接取实体，核对 display_name
    for ind in rules["industries"].values():
        oa_cfg = ind.get("openalex", {})
        for kind in ("subfields", "fields"):
            for it in oa_cfg.get(kind, []):
                if it["status"] == "pending":
                    j = oa(it["id"])
                    out.append({"type": kind, "query": it["id"],
                                "candidate_id": j["id"], "candidate_name": j["display_name"],
                                "expected": it["name_expected"],
                                "match": j["display_name"] == it["name_expected"],
                                "evidence_works_count": j.get("works_count", ""),
                                "human_confirm": ""})
        # 2) venues / journals —— sources 搜索，带佐证字段供人工判断
        for kind in ("venues", "journals", "journals_sensitivity"):
            for it in oa_cfg.get(kind, []):
                if it.get("status") != "pending":
                    continue
                names = [it["name"]] + it.get("aliases", [])
                for q in names:
                    j = oa("sources", search=q, per_page=3)
                    for s in j.get("results", []):
                        out.append({"type": kind, "query": it["name"],
                                    "candidate_id": s["id"], "candidate_name": s["display_name"],
                                    "source_type": s.get("type", ""),
                                    "evidence_works_count": s.get("works_count", ""),
                                    "expected": q, "match": "", "human_confirm": ""})
                    if j.get("results"):
                        break
    _write(CFG / "_candidates_openalex.csv", out)

def _write(path, rows):
    if not rows:
        print(f"[i] 无 pending 项 → {path.name} 未生成")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"[OK] 候选 {len(rows)} 条 → {path.relative_to(ROOT)}；人工确认后手动搬入正式配置并 commit")

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("ror", "openalex"):
        sys.exit(__doc__)
    if sys.argv[1] == "openalex" and not KEY:
        print("[警告] 未设 OPENALEX_KEY——sources 搜索属列表端点，匿名配额小易 429")
    {"ror": resolve_ror, "openalex": resolve_openalex}[sys.argv[1]]()
