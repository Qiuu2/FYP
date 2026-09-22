# -*- coding: utf-8 -*-
r"""
rebuild_request_urls.py —— 为已入库的 API 类数据回填「逐行可点的请求 URL」

为什么需要这个（2026-08-26，R4 复核时发现）：
    collect_all.py 的 save_rows() 把 source_url 记成了**端点**而不是**实际请求**：
      · https://api.openalex.org/works              → 点开是端点说明/报错，看不到我们的查询
      · https://clinicaltrials.gov/api/v2/studies   → 点开返回全库 JSON，跟我们那一行没关系
      · https://api.openalex.org/institutions/ror:{ror}
                                                    → 模板变量 {ror} 根本没被替换，
                                                      浏览器转义成 %7Bror%7D 直接 404
    R2 要求 manifest 能溯源、R4 要求复核者能照着 URL 回查——端点满足不了这个要求。

本脚本做什么：
    按采集代码的逻辑，为每个 raw CSV 的**每一行**重建出能复现该行数值的完整请求 URL，
    写成 manifests/<文件名>.requests.tsv（三列：行键 / 请求URL / 该URL对应的行数），
    并在 manifest 里加上 request_log、request_count、example_request_url 三个字段。

诚实性说明（R1）：
    这些 URL 是**按采集代码确定性重建**的，不是采集当时逐条记录下来的
    （当时的代码没记）。v5.9 起 http_get 会在采集时直接记录真实请求，
    届时不再需要重建。重建结果是否可信，恰恰由 R4 复核来验证——
    点开 URL 看返回的计数是否等于 CSV 里那一行，这正是复核该做的事。

有意省略的参数：
    · api_key / token —— 密钥绝不写进 manifest
    · mailto        —— 仅用于 OpenAlex 礼貌池路由，不影响返回计数
    省略这两个不影响复核者拿到相同的数字。

用法：
    python scripts/rebuild_request_urls.py            # 全部重建
    python scripts/rebuild_request_urls.py --check    # 只报告哪些 manifest 缺可点 URL
"""
import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
RAW, MAN, CFG = ROOT / "raw", ROOT / "manifests", ROOT / "config"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util
_spec = importlib.util.spec_from_file_location("ca", Path(__file__).resolve().parent / "collect_all.py")
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)

OA = "https://api.openalex.org/works"
NOTE = ("按采集代码确定性重建；已省略 api_key（密钥不入库）与 mailto（不影响计数）。"
        "复核方法：点开 URL，核对返回的计数是否等于本表所列行的 count。")


def read_rows(name):
    with open(RAW / name, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def qdates():
    return {q: (d0, d1) for q, d0, d1 in ca.quarters()}


def build_papers(name, intl=False):
    ready, _ = ca.load_rules()
    qd = qdates()
    out = []
    for r in read_rows(name):
        ind, cc, q = r["industry"], r["city"], r["quarter"]
        base_ind = ind[:-3] if ind.endswith("_kw") else ind
        spec = ready.get(base_ind)
        if not spec or q not in qd:
            continue
        d0, d1 = qd[q]
        base = f"authorships.institutions.country_code:{cc},from_publication_date:{d0},to_publication_date:{d1}"
        flt = ca.industry_filter(spec)
        if flt:
            f_all = f"{flt},{base}"
            if intl:
                f_all += ",countries_distinct_count:>1"
            params = {"filter": f_all, "per_page": 1}
        else:
            qy = " OR ".join(f'"{k}"' for k in spec["keywords"][:6])
            params = {"filter": base, "search": qy, "per_page": 1}
        out.append((f"{ind}/{cc}/{q}", f"{OA}?{urlencode(params)}", 1))
    return out


def build_shares(name):
    ready, _ = ca.load_rules()
    seen, out = {}, []
    for r in read_rows(name):
        key = (r["industry"], r["scope"])
        seen[key] = seen.get(key, 0) + 1
    for (ind, scope), n in seen.items():
        spec = ready.get(ind)
        if not spec:
            continue
        flt = ca.industry_filter(spec)
        extra = "" if scope == "world" else ",authorships.countries:" + "|".join(ca.APAC)
        params = {"filter": f"{flt},publication_year:>2014,publication_year:<2026{extra}",
                  "group_by": "publication_year", "per_page": 200}
        out.append((f"{ind}/{scope}", f"{OA}?{urlencode(params)}", n))
    return out


def build_institutions(name):
    seen, out = {}, []
    for r in read_rows(name):
        seen[(r["institution"], r["ror"])] = seen.get((r["institution"], r["ror"]), 0) + 1
    for (inst, ror), n in seen.items():
        out.append((inst, f"https://api.openalex.org/institutions/ror:{ror}", n))
    return out


def build_github(name):
    out = []
    for r in read_rows(name):
        loc = '"Hong Kong"' if r["city"] == "hk" else "Singapore"
        y = r["year"]
        q = f'location:{loc} created:{y}-01-01..{y}-12-31'
        out.append((f'{r["city"]}/{y}',
                    "https://api.github.com/search/users?" + urlencode({"q": q, "per_page": 1}), 1))
    return out


def build_ct_year(name):
    out = []
    for r in read_rows(name):
        y = r["year"]
        params = {"query.locn": "Hong Kong" if r["city"] == "hk" else "Singapore",
                  "countTotal": "true", "pageSize": 1,
                  "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{y}-01-01,{y}-12-31]"}
        out.append((f'{r["city"]}/{y}',
                    "https://clinicaltrials.gov/api/v2/studies?" + urlencode(params), 1))
    return out


def build_ct_quarter(name):
    qd = qdates()
    out = []
    for r in read_rows(name):
        q = r["quarter"]
        if q not in qd:
            continue
        d0, d1 = qd[q]
        params = {"query.locn": "Hong Kong" if r["city"] == "hk" else "Singapore",
                  "countTotal": "true", "pageSize": 1,
                  "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{d0},{d1}]"}
        out.append((f'{r["city"]}/{q}',
                    "https://clinicaltrials.gov/api/v2/studies?" + urlencode(params), 1))
    return out


def build_orcid(name):
    out = []
    for r in read_rows(name):
        params = {"q": f'ror-org-id:"https://ror.org/{r["ror"]}"', "rows": 0}
        out.append((r["institution"],
                    "https://pub.orcid.org/v3.0/search/?" + urlencode(params), 1))
    return out


# ── 统一采集包（collect_openalex_master.py，2026-09-11）的四个产物 ──────────
# 这四个文件在本脚本最初写成时还不存在，所以 BUILDERS 里没有它们，
# manifest.py verify 一直卡在「API 类数据缺 request_log」。2026-09-12 补上。
#
# 注意它们与上面几个的结构差别：master 采集器是**一个单元一条 cursor 分页查询**
# （works ÷ 200 ≈ 930 页），不是一行一次调用。所以 row_key 是「产业/城市」，
# covers_rows 是该单元贡献的行数，request_url 是那条查询的**第一页**
# （cursor=*，后续页由返回的 next_cursor 串起来，URL 只差 cursor 值）。
_MASTER_SELECT = "id,publication_date,authorships,citation_normalized_percentile,primary_location"


def _master_unit_url(ind_label, cc):
    import importlib.util as _iu
    _sp = _iu.spec_from_file_location("com", Path(__file__).resolve().parent / "collect_openalex_master.py")
    com = _iu.module_from_spec(_sp)
    _sp.loader.exec_module(com)
    ready, _ = ca.load_rules()
    base_ind = ind_label[:-3] if ind_label.endswith("_kw") else ind_label
    spec = ready.get(base_ind)
    if not spec:
        return None
    ifilter = ca.industry_filter(spec)
    sfilter, _, _ = com.scope_filter(cc)
    flt = ",".join([x for x in (ifilter, sfilter,
                                "from_publication_date:2015-01-01",
                                "to_publication_date:2024-12-31") if x])
    params = {"filter": flt, "select": _MASTER_SELECT, "per_page": 200, "cursor": "*"}
    if not ifilter:
        params["search"] = " OR ".join(f'"{k}"' for k in spec["keywords"][:6])
    return f"{OA}?{urlencode(params)}"


def build_master_unit(name):
    seen, out = {}, []
    for r in read_rows(name):
        k = (r["industry"], r["city"])
        seen[k] = seen.get(k, 0) + 1
    for (ind, cc), n in sorted(seen.items()):
        u = _master_unit_url(ind, cc)
        if u:
            out.append((f"{ind}/{cc}", u, n))
    return out


def build_topjournal_denoms(name):
    import importlib.util as _iu, yaml
    rules = yaml.safe_load(open(CFG / "boundary_rules_v1.yaml", encoding="utf-8"))
    seen, out = {}, []
    for r in read_rows(name):
        k = (r["industry"], r["journal"], r["source_id"])
        seen[k] = seen.get(k, 0) + 1
    for (ind, jname, sid), n in sorted(seen.items()):
        oa = (rules["industries"].get(ind) or {}).get("openalex", {})
        ifilter = ca.industry_filter(
            {"ids": [i["id"] for kk in ("subfields", "fields") for i in oa.get(kk, [])
                     if str(i.get("status", "")).startswith("confirmed")],
             "keywords": None})
        parts = [f"primary_location.source.id:{sid}",
                 "from_publication_date:2015-01-01", "to_publication_date:2024-12-31"]
        if ifilter:
            parts.insert(1, ifilter)
        params = {"filter": ",".join(parts), "group_by": "publication_year", "per_page": 200}
        out.append((f"{ind}/{jname}", f"{OA}?{urlencode(params)}", n))
    return out


BUILDERS = {
    "openalex_papers_by_quarter.csv":        lambda n: build_papers(n, intl=False),
    "openalex_papers_intl_by_quarter.csv":   lambda n: build_papers(n, intl=True),
    "openalex_share_denominators_by_year.csv": build_shares,
    "openalex_institutions_counts.csv":      build_institutions,
    "github_new_users_by_year.csv":          build_github,
    "clinicaltrials_by_year.csv":            build_ct_year,
    "clinicaltrials_by_quarter.csv":         build_ct_quarter,
    "orcid_affiliated_researchers.csv":      build_orcid,
    "openalex_works_master.csv":             build_master_unit,
    "openalex_author_quarters.csv":           build_master_unit,
    "openalex_author_inst_years.csv":         build_master_unit,
    "openalex_topjournal_denominators.csv":   build_topjournal_denoms,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只报告，不写文件")
    args = ap.parse_args()

    missing, done = [], []
    for mp in sorted(MAN.glob("*.manifest.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        name = Path(m["file"].replace("\\", "/")).name
        url = m.get("source_url", "")
        if name not in BUILDERS:
            # 人工采集的源（p2–p6）本来就是一个能打开的官方页面/PDF，不需要重建；
            # 只有当 URL 里残留未替换的模板变量时才算有问题。
            if "{" in url:
                missing.append(f"{name}（人工源但 URL 含未替换的模板变量：{url}）")
            continue
        if args.check:
            (done if m.get("request_log") else missing).append(
                f"{name}（{'已有' if m.get('request_log') else '缺'} request_log；source_url={url}）")
            continue

        if not (RAW / name).exists():
            continue
        entries = BUILDERS[name](name)
        side = MAN / (name + ".requests.tsv")
        with open(side, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(["# " + NOTE])
            w.writerow(["row_key", "request_url", "covers_rows"])
            w.writerows(entries)
        m["request_log"] = side.name
        m["request_count"] = len(entries)
        m["example_request_url"] = entries[0][1] if entries else ""
        m["request_log_note"] = NOTE
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        done.append(f"{name}：{len(entries)} 条请求 URL → {side.name}")

    for d in done:
        print("  ✅", d)
    for x in missing:
        print("  ⚠", x)


if __name__ == "__main__":
    main()
