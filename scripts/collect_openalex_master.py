# -*- coding: utf-8 -*-
"""OpenAlex 统一采集包 v2 —— 一次遍历，五个指标

【为什么把它们合起来采】
    v1 为了指标 1，把 184,635 篇 works 的完整 authorships 全拉了下来，
    用完 author.id 一个字段，其余全部丢弃。而附录 A 五个指标所需的原始字段
    都藏在同一份响应里：

        指标 1 研究者存量    authorships[].author.id + institutions
        指标 4 前10%高引占比  citation_normalized_percentile
        指标 5 顶刊份额(分子) primary_location.source.id
        指标 6 流动·学术通道  authorships[].institutions + 年份（只是原料，见规划文档）
        指标 7 国际合著比例   authorships[].institutions[].country_code

    调用次数完全不变（works ÷ 200 ≈ 930 次），只是 select 多两个顶层字段、
    落盘多两张表。指标 7 原本另花 480 次单独采，这里是零额外调用。

【输出】
    raw/openalex_works_master.csv        一行一篇论文   → 指标 4、5、7
    raw/openalex_author_quarters.csv     一行一(作者,季) → 指标 1
    raw/openalex_author_inst_years.csv   一行一(作者,年,机构) → 指标 6 原料
    raw/openalex_topjournal_denominators.csv  顶刊分母 → 指标 5（--journals 单独跑）

【用法】
    python scripts/collect_openalex_master.py --smoke          # 只跑 ai/hk 试水
    python scripts/collect_openalex_master.py --all --resume   # 全量（断点续跑）
    python scripts/collect_openalex_master.py --journals       # 顶刊分母（约 24 次调用）
    python scripts/collect_openalex_master.py --all --dry      # 只数调用次数，不发请求
    加 --no-instyears 可跳过第三张表（省内存，代价是指标 6 没有原料）

【口径】
    INSTITUTION_SCOPE=country（2026-09-11 组长拍板）
"""
import argparse, csv, json, os, sys, time, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_all as _ca
from collect_all import (ROOT, KEY, MAILTO, CITIES, load_rules,
                         industry_filter, http_get, log, require_collector)

RAW = ROOT / "raw"
CKPT = RAW / "_ckpt_master"
CFG = ROOT / "config"

INSTITUTION_SCOPE = os.environ.get("INSTITUTION_SCOPE", "country")
YEARS = list(range(2015, 2025))


# ── 口径 ──────────────────────────────────────────────────
def roster_ids(cc):
    rors = []
    with open(CFG / "institutions.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            grp = r.get("group", "")
            if cc == "hk" and grp in ("hk8", "public_rd"):
                rors.append(r["ror"].strip())
            elif cc == "sg" and grp == "sg":
                rors.append(r["ror"].strip())
    return {x.rstrip("/").rsplit("/", 1)[-1].lower() for x in rors if x and x.lower() != "nan"}


def scope_filter(cc):
    if INSTITUTION_SCOPE == "roster":
        rset = roster_ids(cc)
        if not rset:
            raise SystemExit(f"⛔ roster 口径下 {cc} 没有可用 ROR")
        return ("authorships.institutions.ror:" + "|".join(sorted(rset)),
                f"roster({len(rset)}家)", rset)
    return f"authorships.institutions.country_code:{cc}", "country_code", None


# ── 字段容错解析（R1：拿不到就留空，绝不填 0 冒充「不是」）──────
def parse_pct(w):
    """返回 (前10%标志, 前1%标志)。空字符串＝该篇没有这个字段，不是 0。
    2026-09-11 试水实测结构：
      {"value":0.99995799,"is_in_top_1_percent":true,"is_in_top_10_percent":true}
    前 1% 是白给的——同一个对象里，零额外调用，留作质量维的稳健性口径。"""
    cnp = w.get("citation_normalized_percentile")
    if not isinstance(cnp, dict):
        return "", ""
    val = cnp.get("value")
    def flag(key, thr):
        v = cnp.get(key)
        if v is not None:
            return int(bool(v))
        return int(val >= thr) if isinstance(val, (int, float)) else ""
    return flag("is_in_top_10_percent", 0.9), flag("is_in_top_1_percent", 0.99)


def parse_source_id(w):
    pl = w.get("primary_location") or {}
    src = pl.get("source") or {}
    sid = src.get("id") or ""
    return sid.rstrip("/").rsplit("/", 1)[-1] if sid else ""


def quarter_of(d):
    if not d or len(d) < 7:
        return None, None
    y, m = int(d[:4]), int(d[5:7])
    return f"{y}Q{(m - 1) // 3 + 1}", y


# ── 主遍历 ────────────────────────────────────────────────
def pull_unit(ind, spec, cc, args):
    ifilter = industry_filter(spec)
    if ifilter:
        base_params, ind_label = {}, ind
    else:
        kw = " OR ".join(f'"{k}"' for k in spec["keywords"][:6])
        base_params, ind_label = {"search": kw}, ind + "_kw"

    sfilter, sdesc, rset = scope_filter(cc)
    flt = ",".join([p for p in (ifilter, sfilter,
                                "from_publication_date:2015-01-01",
                                "to_publication_date:2024-12-31") if p])

    w_rows = []                      # works 表：一行一篇，不需去重
    a_pairs = {}                     # (quarter, author_id) -> is_local
    i_set = set()                    # (year, author_id, inst_id, inst_cc)
    cursor, page, n_works = "*", 0, 0
    miss_cnp = miss_src = 0

    while cursor:
        params = {
            "filter": flt,
            "select": "id,publication_date,authorships,citation_normalized_percentile,primary_location",
            "per_page": 200, "cursor": cursor, "mailto": MAILTO,
            **base_params, **({"api_key": KEY} if KEY else {}),
        }
        j = http_get("https://api.openalex.org/works", params,
                     tag=f"{ind_label}/{cc}/master/p{page}")
        if j is None:                                  # dry run
            return None, None, None, ind_label, sdesc, 0

        if page == 0:
            probe(j, ind_label, cc)

        for w in j.get("results", []):
            q, year = quarter_of(w.get("publication_date"))
            if not q:
                continue
            n_works += 1
            wid = (w.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
            aus = w.get("authorships") or []
            ccs, n_local = set(), 0
            for a in aus:
                aid_full = (a.get("author") or {}).get("id") or ""
                aid = aid_full.rstrip("/").rsplit("/", 1)[-1]
                insts = a.get("institutions") or []
                for it in insts:
                    c = (it.get("country_code") or "").lower()
                    if c:
                        ccs.add(c)
                if not aid:
                    continue
                # 作者级归属判定（v1 的缺陷就在这里：整篇论文的作者全算本地）
                if rset is None:
                    local = any((it.get("country_code") or "").lower() == cc for it in insts)
                else:
                    local = any((it.get("ror") or "").rstrip("/").rsplit("/", 1)[-1].lower()
                                in rset for it in insts)
                if local:
                    n_local += 1
                k = (q, aid)
                a_pairs[k] = a_pairs.get(k, False) or local
                if not args.no_instyears:
                    for it in insts:
                        iid = (it.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
                        if iid:
                            i_set.add((year, aid, iid, (it.get("country_code") or "").lower()))

            t10, t1 = parse_pct(w)
            sid = parse_source_id(w)
            if t10 == "":
                miss_cnp += 1
            if not sid:
                miss_src += 1
            w_rows.append([ind_label, cc, wid, w.get("publication_date"), q, year,
                           len(ccs), int(len(ccs) >= 2), t10, t1, sid, len(aus), n_local])

        cursor = (j.get("meta") or {}).get("next_cursor")
        page += 1
        if page % 25 == 0:
            log(f"  {ind_label}/{cc}  第 {page} 页  works {n_works:,}  "
                f"(作者,季) {len(a_pairs):,}  (作者,年,机构) {len(i_set):,}")

    if n_works:
        log(f"  字段缺失率 {ind_label}/{cc}：citation_normalized_percentile "
            f"{miss_cnp/n_works:.1%}，primary_location.source {miss_src/n_works:.1%}")
    return w_rows, a_pairs, i_set, ind_label, sdesc, n_works


def probe(j, ind_label, cc):
    """首页探针：select 到底把哪些嵌套字段带回来了。不验就跑 900 次，白跑。"""
    n_au = n_inst = n_cnp = n_src = 0
    sample = None
    for w in j.get("results", []):
        if w.get("citation_normalized_percentile") is not None:
            n_cnp += 1
            if sample is None:
                sample = w["citation_normalized_percentile"]
        if parse_source_id(w):
            n_src += 1
        for a in w.get("authorships", []):
            n_au += 1
            if a.get("institutions"):
                n_inst += 1
    n_w = len(j.get("results", []))
    log(f"  [探针] {ind_label}/{cc} 首页 {n_w} 篇：署名位次 {n_au}，带机构 {n_inst} "
        f"({n_inst/max(n_au,1):.0%})；有 cnp {n_cnp}/{n_w}；有 source {n_src}/{n_w}")
    if sample is not None:
        log(f"  [探针] citation_normalized_percentile 实际结构：{json.dumps(sample, ensure_ascii=False)}")
        if "is_in_top_1_percent" not in sample:
            log("  ⚠️ 该结构里没有 is_in_top_1_percent，前 1% 口径将回退到 value>=0.99 推算")
    if n_au and n_inst == 0:
        sys.exit("⛔ institutions 全为空——select 把嵌套机构字段裁掉了，is_local 会全是 0。\n"
                 "   处理：删掉 params 里 'select' 那一行再跑（体积变大但一定带机构）。")
    if n_w and n_cnp == 0:
        log("  ⚠️ 首页没有一篇带 citation_normalized_percentile —— 指标 4 会全空。\n"
            "     先跑完试水把这行发给组长判断，别直接跑全量。")


# ── 顶刊分母（指标 5）──────────────────────────────────────
def journal_denominators(dry=False):
    """全球该刊该年论文数。分子来自 works_master 的 source_id，零调用。
    ⚠️ fintech 的 boundary_rules 里 venues 是空的——指标 5 只能做 ai 与 biomed。"""
    import yaml
    rules = yaml.safe_load(open(CFG / "boundary_rules_v1.yaml", encoding="utf-8"))
    rows = []
    for ind, spec in rules["industries"].items():
        oa = spec.get("openalex", {})
        journals = (oa.get("journals") or []) + (oa.get("journals_sensitivity") or [])
        if not journals:
            log(f"  ⚠️ {ind} 没有期刊清单（venues/journals 为空）——指标 5 该产业做不了")
            continue
        # 分母必须与分子同产业口径：综合刊（Nature/Science）只计该产业学科的论文
        ifilter = industry_filter({"ids": [i["id"] for k in ("subfields", "fields")
                                           for i in oa.get(k, [])
                                           if str(i.get("status", "")).startswith("confirmed")],
                                   "keywords": None})
        for jr in journals:
            sid = jr["id"].rstrip("/").rsplit("/", 1)[-1]
            parts = [f"primary_location.source.id:{sid}",
                     "from_publication_date:2015-01-01",
                     "to_publication_date:2024-12-31"]
            if ifilter:
                parts.insert(1, ifilter)
            j = http_get("https://api.openalex.org/works",
                         {"filter": ",".join(parts), "group_by": "publication_year",
                          "per_page": 200, "mailto": MAILTO,
                          **({"api_key": KEY} if KEY else {})},
                         tag=f"journals/{ind}/{jr['name']}")
            if j is None:
                continue
            got = {int(g["key"]): g["count"] for g in j.get("group_by", [])
                   if str(g.get("key", "")).isdigit()}
            for y in YEARS:
                rows.append([ind, jr["name"], sid, y, got.get(y, 0),
                             "sensitivity" if jr in (oa.get("journals_sensitivity") or []) else "core"])
    if dry:
        log(f"DRY 顶刊分母将写 {len(rows)} 行")
        return
    out = RAW / "openalex_topjournal_denominators.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["industry", "journal", "source_id", "year", "global_works", "tier"])
        w.writerows(rows)
    log(f"✅ {out.name}  {len(rows)} 行")


# ── 合并 checkpoint ───────────────────────────────────────
def merge(name, header, n_units):
    files = sorted(CKPT.glob(f"*_{name}.csv"))
    if len(files) < n_units:
        log(f"⚠️ {name}: 只有 {len(files)}/{n_units} 个单元，先补齐再合并")
        return None
    out = RAW / f"openalex_{name}.csv"
    n = 0
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for f in files:
            with open(f, encoding="utf-8-sig", newline="") as g:
                rd = csv.reader(g); next(rd)
                for row in rd:
                    w.writerow(row); n += 1
    log(f"✅ raw/{out.name}  {n:,} 行  {out.stat().st_size/1e6:.1f} MB")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--journals", action="store_true", help="只跑顶刊分母")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-instyears", action="store_true", help="跳过第三张表（省内存）")
    args = ap.parse_args()
    if not (args.smoke or args.all or args.journals):
        ap.error("要么 --smoke，要么 --all，要么 --journals")

    if args.dry:
        _ca.DRY = True          # 注意：必须改模块属性，collect_all 不读环境变量
    else:
        require_collector()

    if args.journals:
        journal_denominators(args.dry)
        if args.dry:
            log(f"预计调用次数：{_ca.CALLS_PLANNED}")
        return

    CKPT.mkdir(parents=True, exist_ok=True)
    ready, blocked = load_rules()
    for ind, why in blocked.items():
        log(f"⛔ R6：产业 {ind} 的 ID 未 confirmed（{'; '.join(why)}）")

    units = [("ai", "hk")] if args.smoke else [(i, c) for i in ready for c in CITIES]
    log(f"口径：INSTITUTION_SCOPE={INSTITUTION_SCOPE}　单元数 {len(units)}"
        f"{'　（跳过 instyears 表）' if args.no_instyears else ''}")

    t0 = time.time()
    for ind, cc in units:
        tag = f"{ind}_{cc}"
        if args.resume and (CKPT / f"{tag}_works_master.csv").exists():
            log(f"⏭  {tag} 已有 checkpoint，跳过")
            continue
        t1 = time.time()
        w_rows, a_pairs, i_set, ind_label, sdesc, n_works = pull_unit(ind, ready[ind], cc, args)
        if args.dry:
            continue
        with open(CKPT / f"{tag}_works_master.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["industry", "city", "work_id", "pub_date", "quarter", "year",
                        "n_inst_countries", "is_intl", "is_top10pct", "is_top1pct",
                        "source_id", "n_authors", "n_local_authors"])
            w.writerows(w_rows)
        with open(CKPT / f"{tag}_author_quarters.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["industry", "city", "quarter", "author_id", "is_local"])
            for (q, aid), loc in sorted(a_pairs.items()):
                w.writerow([ind_label, cc, q, aid, int(loc)])
        if not args.no_instyears:
            with open(CKPT / f"{tag}_author_inst_years.csv", "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["industry", "city", "year", "author_id", "inst_id", "inst_cc"])
                for year, aid, iid, icc in sorted(i_set):
                    w.writerow([ind_label, cc, year, aid, iid, icc])
        n_loc = sum(1 for v in a_pairs.values() if v)
        log(f"✅ {ind_label}/{cc}  works {n_works:,}  (作者,季) {len(a_pairs):,}  "
            f"其中本地署名 {n_loc:,} ({n_loc/max(len(a_pairs),1):.1%})  "
            f"(作者,年,机构) {len(i_set):,}  耗时 {(time.time()-t1)/60:.1f} 分")

    if args.dry:
        log(f"\n预计调用次数：{_ca.CALLS_PLANNED}（dry 只走首页，实际按 works/200 估约 930）")
        return
    if args.smoke:
        log("\n试水完成。把上面的 [探针] 两行和 ✅ 那行发给组长，确认后再跑 --all --resume")
        return

    merge("works_master", ["industry", "city", "work_id", "pub_date", "quarter", "year",
                           "n_inst_countries", "is_intl", "is_top10pct", "is_top1pct",
                           "source_id", "n_authors", "n_local_authors"], len(units))
    merge("author_quarters", ["industry", "city", "quarter", "author_id", "is_local"], len(units))
    if not args.no_instyears:
        merge("author_inst_years", ["industry", "city", "year", "author_id", "inst_id", "inst_cc"],
              len(units))
    log(f"\n总耗时 {(time.time()-t0)/60:.1f} 分钟")
    log("\n下一步：")
    log("   python scripts/collect_openalex_master.py --journals   # 顶刊分母，约 24 次调用")
    log("   python scripts/authors_build.py                        # 指标 1")
    log("   python scripts/works_build.py                          # 指标 4、5、7")


if __name__ == "__main__":
    main()
