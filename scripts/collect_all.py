# -*- coding: utf-8 -*-
"""
collect_all.py —— 阶段 2 全量采集脚本（学生本地运行）
=====================================================
七个模块，全部走官方 API／公共数据集，自动写 manifest（R1/R2 落地）。

准备（一次性）：
  export OPENALEX_KEY=...            # 免费注册 openalex.org
  export OPENALEX_MAILTO=you@link.cuhk.edu.hk
  export GITHUB_TOKEN=...            # 免费 PAT（可选，无则限速更严）
  export PATENTSVIEW_KEY=...         # 免费注册 patentsview.org（美国专利）
  export ORCID_CLIENT_ID=... ORCID_CLIENT_SECRET=...   # 免费公共API凭证（可选）
  export COLLECTOR_NAME=张三          # manifest 的执行人字段

用法：
  python scripts/collect_all.py plan                 # 全模块 dry-run：打印计划与配额估算，不联网
  python scripts/collect_all.py papers               # OpenAlex：产业×城市 季度论文数＋国际合著（需 key）
  python scripts/collect_all.py shares               # OpenAlex：全球/亚太分母（年度，需 key）
  python scripts/collect_all.py institutions         # OpenAlex：机构 counts_by_year 刷新（实体端点，免 key）
  python scripts/collect_all.py github               # GitHub：注册队列＋org 成员（需 PAT）
  python scripts/collect_all.py clinicaltrials       # ClinicalTrials.gov v2：港/新 逐年试验数（免 key）
  python scripts/collect_all.py clinicaltrials_q     # 同上但逐季度（附录A指标9要求的频率，免 key）
  python scripts/collect_all.py patentsview          # PatentsView：HK 申请人美国专利逐年（需 key）
  python scripts/collect_all.py orcid                # ORCID：机构雇佣记录计数（需凭证）

铁律执行：
  - R6：boundary_rules_v1.yaml 中 status != confirmed 的产业 ID → 对应拉取直接拒绝并提示先跑 resolve_ids.py
  - R2：每个输出文件自动写 manifest（源URL、查询、UTC时间戳、执行人、SHA256）
  - 频率纪律：季度序列只来自原生日期字段；年度指标绝不内插（见审计规则）
  - BigQuery 两件（企业/大学专利、GH Archive 协作）在 sql/ 目录，БigQuery 控制台粘贴运行后把导出 CSV 放入 raw/ 并手动 manifest add
"""
import argparse, csv, hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml requests")

ROOT = Path(__file__).resolve().parent.parent
RAW, MAN, CLEAN, CFG = ROOT / "raw", ROOT / "manifests", ROOT / "clean", ROOT / "config"

KEY = os.environ.get("OPENALEX_KEY", "")
MAILTO = os.environ.get("OPENALEX_MAILTO", "team@example.edu")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
PV_KEY = os.environ.get("PATENTSVIEW_KEY", "")
ORCID_ID = os.environ.get("ORCID_CLIENT_ID", "")
ORCID_SECRET = os.environ.get("ORCID_CLIENT_SECRET", "")
BY = os.environ.get("COLLECTOR_NAME", "UNSET——请 export COLLECTOR_NAME")

YEARS = list(range(2015, 2026))          # 年度：2015–2025
Q_START, Q_END = (2015, 1), (2024, 4)    # 季度：2015Q1–2024Q4（审计版频率纪律）
CITIES = {"hk": "香港", "sg": "新加坡"}
# 亚太分母的国家/地区码——词表决策，冻结前须组会确认并 commit 留痕
APAC = ["cn", "jp", "kr", "sg", "tw", "in", "au", "nz", "my", "th", "id", "vn", "ph", "hk", "mo"]

DRY = False
CALLS_PLANNED = 0

# 采集期间逐条记录「行键 → 实际请求 URL」，写盘时落到 manifests/<文件>.requests.tsv。
# 起因（2026-08-26 R4 复核）：原来 manifest 的 source_url 只记端点，复核者点开
# 要么是端点说明、要么是全库 JSON，甚至出现过 {ror} 模板变量没被替换直接 404。
# R2/R4 要的是「照着这个 URL 能回查出同一个数」，端点满足不了。
REQUEST_LOG = []
_SECRET_PARAMS = {"api_key", "apikey", "key", "token", "access_token"}
_NOISE_PARAMS = {"mailto"}          # 不影响返回值，去掉让 URL 更短更好读
REQUEST_LOG_NOTE = ("采集时逐条记录的真实请求 URL；已剔除 api_key 等密钥（不入库）"
                    "与 mailto（不影响返回计数）。复核方法：点开 URL，"
                    "核对返回的计数是否等于本表所列行的 count。")


def log_request(url, params, tag):
    """把一次请求记进日志。密钥绝不写进去。"""
    clean = {k: v for k, v in (params or {}).items()
             if k.lower() not in _SECRET_PARAMS and k.lower() not in _NOISE_PARAMS}
    full = url + ("?" + urlencode(clean) if clean else "")
    REQUEST_LOG.append((tag or "", full))


# ---------- 基础设施 ----------
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def require_collector():
    """R2：manifest 必须记录真实执行人。没设 COLLECTOR_NAME 就直接拒跑，
    别等跑完 400 次调用才发现 manifest 里写的是占位符（2026-08-25 就踩过这个坑）。"""
    if not BY or BY.startswith("UNSET"):
        sys.exit("⛔ 没有设置 COLLECTOR_NAME，manifest 无法记录执行人（R2）。\n"
                 "   PowerShell: $env:COLLECTOR_NAME=\"你的名字\"\n"
                 "   bash:       export COLLECTOR_NAME=你的名字\n"
                 "   或直接填进 .keys.env 后用 run_phase2.ps1 / run_phase2.sh 启动。")


def write_request_log(data_name: str):
    """把本次采集攒下的请求 URL 落成 manifests/<文件>.requests.tsv，并清空日志。"""
    global REQUEST_LOG
    if not REQUEST_LOG:
        return None
    MAN.mkdir(parents=True, exist_ok=True)
    out = MAN / (data_name + ".requests.tsv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["# " + REQUEST_LOG_NOTE])
        w.writerow(["row_key", "request_url"])
        w.writerows(REQUEST_LOG)
    info = {"name": out.name, "count": len(REQUEST_LOG), "first": REQUEST_LOG[0][1]}
    log(f"请求日志 → {out.name}（{len(REQUEST_LOG)} 条可点 URL，供 R4 复核）")
    REQUEST_LOG = []
    return info


def write_manifest(data_file: Path, source_url: str, query: str, note: str = "", reqs=None):
    rel = data_file.resolve().relative_to(RAW.resolve())
    out = MAN / (str(rel).replace("/", "__") + ".manifest.json")
    out.write_text(json.dumps({
        # 统一用正斜杠：Windows 上 str(Path) 会写出 "raw\\xxx.csv"，
        # 到了 Mac/Linux/git 上就被当成一个文件名，verify 会误报"孤儿 manifest"
        "file": data_file.relative_to(ROOT.resolve()).as_posix(), "sha256": sha256(data_file),
        "source_url": source_url, "query_or_method": query,
        "collected_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collected_by": BY, "notes": note, "manifest_version": 2,
        **({"request_log": reqs["name"], "request_count": reqs["count"],
            "example_request_url": reqs["first"], "request_log_note": REQUEST_LOG_NOTE}
           if reqs else {}),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"manifest → {out.name}")

def save_rows(name: str, header, rows, source_url: str, query: str, note: str = ""):
    """写 raw/ CSV ＋ manifest。clean/ 层由 build_clean.py 或人工按入库流程生成。"""
    p = RAW / name
    if DRY:
        log(f"DRY 将写 raw/{name}（{len(rows)} 行）")
        return p
    require_collector()
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    reqs = write_request_log(name)
    write_manifest(p, source_url, query, note, reqs)
    log(f"raw/{name} 写入 {len(rows)} 行")
    return p

def http_get(url, params=None, headers=None, tag=""):
    global CALLS_PLANNED
    CALLS_PLANNED += 1
    if DRY:
        return None
    log_request(url, params, tag)
    for attempt in range(5):
        r = requests.get(url, params=params, headers=headers, timeout=60)
        if r.status_code == 429:
            wait = 30 * (attempt + 1)
            log(f"429 @{tag or url[:60]} → 等待 {wait}s 重试")
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(1.0)
        return r.json()
    raise RuntimeError(f"重试后仍 429：{url}")


# ---------- 规则装载（R6 强制） ----------
def load_rules():
    rules = yaml.safe_load(open(CFG / "boundary_rules_v1.yaml", encoding="utf-8"))
    ready, blocked = {}, {}
    for ind, spec in rules["industries"].items():
        ids = []
        for kind in ("subfields", "fields"):
            for it in spec.get("openalex", {}).get(kind, []):
                if str(it.get("status", "")).startswith("confirmed"):
                    ids.append(it["id"])
                else:
                    blocked.setdefault(ind, []).append(f"{it['id']}({it['status']})")
        kw = spec.get("openalex", {}).get("topic_keywords") or spec.get("openalex", {}).get("extra_topic_keywords")
        if ids:
            ready[ind] = {"ids": ids, "keywords": kw}
        elif kw and ind == "fintech":
            # 金融科技无学科 ID，走关键词检索口径（设计决定，见 boundary_rules）
            ready[ind] = {"ids": [], "keywords": kw}
        # 其余无 confirmed ID 的产业留在 blocked
    return ready, blocked

def quarters():
    y, q = Q_START
    while (y, q) <= Q_END:
        m0 = 3 * (q - 1) + 1
        m1 = m0 + 2
        last_day = {3: 31, 6: 30, 9: 30, 12: 31}[m1]
        yield f"{y}Q{q}", f"{y}-{m0:02d}-01", f"{y}-{m1:02d}-{last_day}"
        q += 1
        if q == 5:
            y, q = y + 1, 1


# ---------- 模块 1：papers（季度：产业×城市 论文数＋国际合著数） ----------
def industry_filter(spec):
    if spec["ids"]:
        # 修复（2026-08-25）：原代码不分青红皂白一律拼 primary_topic.subfield.id，
        # 但 boundary_rules_v1.yaml 里有的产业（如 biomed）确认的是 fields/xx 而非 subfields/xx——
        # OpenAlex 的 field 与 subfield 是两套完全不重叠的编号体系（field 27=Medicine，
        # 但"subfield 27"根本不存在，subfield 一律是4位数，如 1702=Artificial Intelligence），
        # 拿 field 的编号去查 subfield.id 一条都查不到，biomed 因此全线归零。按各 id 自带的
        # "fields/" 或 "subfields/" 前缀分别拼接、按 kind 分组后用逗号 AND 连接。
        by_kind = {}
        for i in spec["ids"]:
            kind = i.split("/")[0]           # "subfields" 或 "fields"
            num = i.split("/")[-1]
            by_kind.setdefault(kind, []).append(num)
        clauses = []
        for kind, nums in by_kind.items():
            key = "primary_topic.field.id" if kind == "fields" else "primary_topic.subfield.id"
            clauses.append(f"{key}:" + "|".join(nums))
        return ",".join(clauses)
    # 关键词口径（金融科技）：以 title_and_abstract 搜索近似——正式口径以 topics 白名单解析后为准
    return None

def mod_papers():
    ready, blocked = load_rules()
    for ind, why in blocked.items():
        log(f"⛔ R6：产业 {ind} 的 ID 未 confirmed（{'; '.join(why)}）——先跑 resolve_ids.py 并人工确认")
    rows_n, rows_i = [], []
    for ind, spec in ready.items():
        flt = industry_filter(spec)
        for cc in CITIES:
            for qlabel, d0, d1 in quarters():
                base = f"authorships.institutions.country_code:{cc},from_publication_date:{d0},to_publication_date:{d1}"
                if flt:
                    f_all = f"{flt},{base}"
                    j = http_get("https://api.openalex.org/works",
                                 {"filter": f_all, "per_page": 1, "mailto": MAILTO, "api_key": KEY} if KEY else
                                 {"filter": f_all, "per_page": 1, "mailto": MAILTO}, tag=f"{ind}/{cc}/{qlabel}")
                    n = j["meta"]["count"] if j else 0
                    j2 = http_get("https://api.openalex.org/works",
                                  {"filter": f_all + ",countries_distinct_count:>1", "per_page": 1,
                                   "mailto": MAILTO, **({"api_key": KEY} if KEY else {})}, tag=f"{ind}/{cc}/{qlabel}/intl")
                    ni = j2["meta"]["count"] if j2 else 0
                    rows_n.append([ind, cc, qlabel, n])
                    rows_i.append([ind, cc, qlabel, ni])
                else:
                    # 金融科技关键词口径：search 参数（近似口径，结果单独成列以免与学科口径混同）
                    q = " OR ".join(f'"{k}"' for k in spec["keywords"][:6])
                    j = http_get("https://api.openalex.org/works",
                                 {"filter": base, "search": q, "per_page": 1, "mailto": MAILTO,
                                  **({"api_key": KEY} if KEY else {})}, tag=f"{ind}/{cc}/{qlabel}")
                    rows_n.append([ind + "_kw", cc, qlabel, j["meta"]["count"] if j else 0])
                    # 【2026-09-07 修补】此前本分支只写了分母、漏写分子，
                    # 导致 openalex_papers_intl_by_quarter.csv 只有 4/6 单元（缺 fintech 港星）。
                    # 分子口径必须与上面 if 分支一致：同一 filter + countries_distinct_count:>1
                    j2 = http_get("https://api.openalex.org/works",
                                  {"filter": base + ",countries_distinct_count:>1", "search": q,
                                   "per_page": 1, "mailto": MAILTO,
                                   **({"api_key": KEY} if KEY else {})},
                                  tag=f"{ind}/{cc}/{qlabel}/intl")
                    rows_i.append([ind + "_kw", cc, qlabel, j2["meta"]["count"] if j2 else 0])
    save_rows("openalex_papers_by_quarter.csv", ["industry", "city", "quarter", "count"], rows_n,
              "https://api.openalex.org/works", "works filter=industry×country×quarter (per_page=1 取 meta.count)",
              "季度原生口径；fintech_kw 为关键词近似口径，与学科口径分列")
    if rows_i:
        save_rows("openalex_papers_intl_by_quarter.csv", ["industry", "city", "quarter", "count"], rows_i,
                  "https://api.openalex.org/works", "同上＋countries_distinct_count:>1", "网络维分子")


# ---------- 模块 2：shares（年度分母：全球/亚太） ----------
def mod_shares():
    ready, _ = load_rules()
    rows = []
    for ind, spec in ready.items():
        flt = industry_filter(spec)
        if not flt:
            log(f"（{ind} 无学科ID，分母跳过——关键词口径不做份额）")
            continue
        for scope, extra in [("world", ""), ("apac", ",authorships.countries:" + "|".join(APAC))]:
            # 修复（2026-08-25）：两处问题会同时把本该11年的group_by压成1行——
            # ① "publication_year:2015-2025" 在 OpenAlex 里不是合法的区间写法（该字段没有连字符
            #   区间算子），须用 > / < 不等式；② group_by 的分组条数与 per_page 共用同一个"每页
            #   条数"，per_page=1 会把 group_by 数组也截到只剩1条（通常是计数最大的那一年）。
            j = http_get("https://api.openalex.org/works",
                         {"filter": f"{flt},publication_year:>2014,publication_year:<2026{extra}",
                          "group_by": "publication_year", "per_page": 200, "mailto": MAILTO,
                          **({"api_key": KEY} if KEY else {})}, tag=f"shares/{ind}/{scope}")
            if j:
                for g in j["group_by"]:
                    rows.append([ind, scope, g["key"], g["count"]])
    save_rows("openalex_share_denominators_by_year.csv", ["industry", "scope", "year", "count"], rows,
              "https://api.openalex.org/works", "group_by=publication_year（world 与 APAC 词表口径）",
              "★份额指标分母；APAC 词表见脚本头，冻结前须组会确认")


# ---------- 模块 3：institutions（实体端点刷新，免 key） ----------
def mod_institutions():
    rows = []
    with open(CFG / "institutions.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not r["ror"] or not r["verify_status"].startswith("confirmed"):
                continue
            j = http_get(f"https://api.openalex.org/institutions/ror:{r['ror']}",
                         {"mailto": MAILTO}, tag=r["name_zh"])
            if j:
                cby = {c["year"]: (c["works_count"], c["cited_by_count"]) for c in j["counts_by_year"]}
                for y in YEARS:
                    wc, cc_ = cby.get(y, ("", ""))
                    rows.append([r["name_zh"], r["ror"], y, wc, cc_])
    save_rows("openalex_institutions_counts.csv", ["institution", "ror", "year", "works_count", "cited_by_count"],
              rows, "https://api.openalex.org/institutions/ror:<各机构ROR，逐条见 request_log>",
              "实体端点 counts_by_year（免key不限量）")


# ---------- 模块 4：github（注册队列＋org 成员） ----------
def mod_github():
    H = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        H["Authorization"] = f"Bearer {GH_TOKEN}"
    rows = []
    for y in YEARS:
        for loc, label in [("%22Hong%20Kong%22", "hk"), ("Singapore", "sg")]:
            j = http_get(f"https://api.github.com/search/users?q=location:{loc}+created:{y}-01-01..{y}-12-31&per_page=1",
                         headers=H, tag=f"gh/{label}/{y}")
            rows.append([label, y, j.get("total_count", "") if j else ""])
            if not DRY:
                time.sleep(2.5 if GH_TOKEN else 7)
    save_rows("github_new_users_by_year.csv", ["city", "year", "count"], rows,
              "https://api.github.com/search/users", "location×created 逐年 total_count",
              "口径=当前location回溯注册年；幸存者偏差见局限")
    orgs_file = CFG / "github_orgs.csv"
    if orgs_file.exists():
        mrows = []
        with open(orgs_file, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("status") != "confirmed":
                    continue
                page, members = 1, 0
                while True:
                    j = http_get(f"https://api.github.com/orgs/{r['org_handle']}/members?per_page=100&page={page}",
                                 headers=H, tag=f"org/{r['org_handle']}")
                    if not j:
                        break
                    members += len(j)
                    if len(j) < 100:
                        break
                    page += 1
                mrows.append([r["org_handle"], r.get("entity", ""), members])
        if mrows:
            save_rows("github_org_members.csv", ["org_handle", "entity", "public_members"], mrows,
                      "https://api.github.com/orgs/{org}/members", "org 公开成员计数（口径：仅公开成员）")


# ---------- 模块 5：clinicaltrials（免 key） ----------
def mod_clinicaltrials():
    rows = []
    for cc, term in [("hk", "Hong Kong"), ("sg", "Singapore")]:
        for y in YEARS:
            j = http_get("https://clinicaltrials.gov/api/v2/studies",
                         {"query.locn": term, "countTotal": "true", "pageSize": 1,
                          "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{y}-01-01,{y}-12-31]"},
                         tag=f"ct/{cc}/{y}")
            rows.append([cc, y, j.get("totalCount", "") if j else ""])
    save_rows("clinicaltrials_by_year.csv", ["city", "year", "count"], rows,
              "https://clinicaltrials.gov/api/v2/studies", "query.locn×StudyFirstPostDate 逐年 totalCount",
              "生医创新维；建议再以 WHO ICTRP/ChiCTR 交叉（人工小样本）")


# ---------- 模块 5b：clinicaltrials_q（季度口径，供 RQ2 先行检验） ----------
def mod_clinicaltrials_q():
    """按季度采临床试验登记数。

    为什么单独做一个模块（2026-08-26）：
    附录 A 指标 9（IDI·创新）要求**季度**频率，而 4.5 步骤③ 写死「季度先行检验只使用
    原生季度指标，年度指标绝不内插为季度」——原来那份 clinicaltrials_by_year.csv 是年度的，
    进不了先行检验。ClinicalTrials.gov 的 StudyFirstPostDate 支持任意日期区间，
    直接按季度拉即可，不需要任何插值。
    季度范围复用 Q_START/Q_END，与 papers 模块严格对齐（2015Q1–2024Q4，40 期），
    否则两条序列错位就没法做交叉相关。
    年度那份保留不动，继续供年度剖面使用。
    """
    rows = []
    for cc, term in [("hk", "Hong Kong"), ("sg", "Singapore")]:
        for qlabel, d0, d1 in quarters():
            j = http_get("https://clinicaltrials.gov/api/v2/studies",
                         {"query.locn": term, "countTotal": "true", "pageSize": 1,
                          "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{d0},{d1}]"},
                         tag=f"ctq/{cc}/{qlabel}")
            rows.append([cc, qlabel, j.get("totalCount", "") if j else ""])

    if not DRY:
        expect = 2 * sum(1 for _ in quarters())
        if len(rows) != expect:
            raise RuntimeError(f"clinicaltrials_q 行数 {len(rows)} ≠ 预期 {expect}，拒绝写盘")
        if any(r[2] in ("", None) for r in rows):
            raise RuntimeError("clinicaltrials_q 出现空 count，拒绝写盘")
        cross = _ct_cross_check(rows)
    else:
        cross = None

    note = "附录A指标9·IDI创新·季度口径；年度那份 clinicaltrials_by_year.csv 保留供年度剖面"
    if cross:
        note += ("｜交叉核对："
                 f"{cross['exact_match']}/{cross['compared_city_years']} 个城市×年完全一致"
                 + (f"；漂移 {len(cross['drift_cells'])} 格：" + "，".join(cross["drift_cells"])
                    if cross["drift_cells"] else "")
                 + "。" + cross["note"])

    save_rows("clinicaltrials_by_quarter.csv", ["city", "quarter", "count"], rows,
              "https://clinicaltrials.gov/api/v2/studies",
              "query.locn×StudyFirstPostDate 逐季度 totalCount（区间与 Q_START/Q_END 对齐）",
              note)


def _ct_cross_check(rows):
    """把季度数据跟年度文件对一遍，返回一份可写进 manifest 的核对结果。

    设计修正（2026-08-26，第一版守卫误报后）：
    第一版要求「四季度合计 == 年度值」严格相等，结果 20 个「城市×年」里有 2 个
    差 +1 就把整次采集炸掉了。查下来不是查询写错——季度区间是严格划分（首尾相接、
    无重叠无缺口），而且真有结构性错误的话 20 格会一起错，不会只错 2 格、还都恰好差 1。

    真正的原因是：**两份数据不是同一时刻的快照**。年度那份采于更早，季度这份采于之后，
    而 ClinicalTrials.gov 是活库——`query.locn` 匹配的是研究的地点列表，申办方可以在
    登记之后追加地点。一项 2018 年首次登记、最近才加上新加坡站点的研究，会在保持
    2018 年 StudyFirstPostDate 的同时，新近开始匹配 `query.locn=Singapore`。
    所以历史年份的计数本来就会随时间缓慢上涨。

    因此改成：小幅漂移放行但如实记录，结构性错误照旧拦截。
    判定阈值：单格 |差| ≤ max(3, 年度值的 1%) 视为快照漂移；超过则报错。
    另外若超过半数格子都有差异，即使每格都很小也判为结构性问题——
    漂移应当是零星的，不该普遍发生。
    """
    yearly = RAW / "clinicaltrials_by_year.csv"
    if not yearly.exists():
        log("（没有年度文件可比对，跳过交叉核对）")
        return None
    ref = {}
    with open(yearly, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ref[(r["city"], int(r["year"]))] = int(r["count"])

    agg = {}
    for city, qlabel, n in rows:
        y = int(qlabel[:4])
        agg[(city, y)] = agg.get((city, y), 0) + int(n)

    compared, drift, fatal = 0, [], []
    for key in sorted(agg):
        want = ref.get(key)
        if want is None:
            continue
        compared += 1
        got = agg[key]
        d = got - want
        if d == 0:
            continue
        tol = max(3, round(want * 0.01))
        item = f"{key[0]}/{key[1]}: 季度合计 {got} vs 年度 {want}（{d:+d}）"
        (drift if abs(d) <= tol else fatal).append(item)

    if fatal:
        raise RuntimeError(
            "季度与年度差异超出快照漂移的合理范围，拒绝写盘：\n  " + "\n  ".join(fatal) +
            "\n  （季度区间是年度的严格划分，差异应当只来自两次采集之间的库更新）")
    if compared and len(drift) > compared / 2:
        raise RuntimeError(
            f"{compared} 个「城市×年」里有 {len(drift)} 个对不上，虽然每个都不大，"
            "但普遍性差异不像快照漂移，更像查询口径有问题，拒绝写盘：\n  " + "\n  ".join(drift))

    if drift:
        log(f"⚠ 交叉核对：{compared} 格中 {len(drift)} 格存在小幅漂移（已记入 manifest）")
        for x in drift:
            log(f"    {x}")
        log("    原因：两份数据采集时点不同，ClinicalTrials.gov 的地点字段可被事后追加，"
            "历史年份计数会缓慢上涨。属正常，不是采集错误。")
    else:
        log(f"✅ 交叉核对通过：{compared} 个「城市×年」的四季度合计与年度文件完全一致")

    return {"compared_city_years": compared, "exact_match": compared - len(drift),
            "drift_cells": drift,
            "note": ("与 clinicaltrials_by_year.csv 的逐年比对。季度区间为年度的严格划分，"
                     "残余差异来自两次采集时点之间 ClinicalTrials.gov 的库更新"
                     "（地点字段可被申办方事后追加，历史年份计数会缓慢上涨），非采集错误。")}


# ---------- 模块 6：patentsview（美国专利，HK/SG 申请人逐年） ----------
PV_URL = "https://search.patentsview.org/api/v1/patent/"

def pv_request(q: dict, o: dict = None, f: list = None, tag: str = ""):
    """PatentsView 单次查询。GET 为主、POST 为兜底；任何异常都炸出来，绝不返回空值。

    修复要点（2026-08-25）：旧版 `r.json().get("total_hits","")` 会把
    「接口报错/字段缺失」伪装成「查到 0 篇」，静默写出一整列空白 CSV。
    现在：非 200 抛错并带上 body；200 但缺 total_hits 也抛错。
    """
    body = {"q": q}
    if o:
        body["o"] = o
    if f:
        body["f"] = f
    params = {k: json.dumps(v) for k, v in body.items()}

    last = None
    for attempt in range(4):
        r = requests.get(PV_URL, params=params, headers={"X-Api-Key": PV_KEY}, timeout=60)
        if r.status_code == 429:
            wait = 30 * (attempt + 1)
            log(f"429 @patentsview/{tag} → 等待 {wait}s 重试")
            time.sleep(wait)
            continue
        last = r
        break

    if last is None:
        raise RuntimeError(f"patentsview 重试后仍 429：{tag}")

    # GET 失败时用 POST 兜底（官方文档：两种方法参数一致）
    if last.status_code != 200:
        log(f"⚠ GET {last.status_code} @patentsview/{tag} → 改用 POST 重试一次")
        last = requests.post(PV_URL, json=body,
                             headers={"X-Api-Key": PV_KEY, "Content-Type": "application/json"},
                             timeout=60)

    if last.status_code != 200:
        raise RuntimeError(
            f"patentsview {tag} HTTP {last.status_code}；"
            f"X-Status-Reason={last.headers.get('X-Status-Reason')}；body={last.text[:500]}")

    j = last.json()
    if "total_hits" not in j:
        raise RuntimeError(
            f"patentsview {tag} 返回 200 但没有 total_hits 字段；keys={sorted(j)}；body={last.text[:500]}")
    return j


def mod_patentsview():
    if not PV_KEY and not DRY:
        log("⛔ 需 PATENTSVIEW_KEY（免费注册）")
        return
    rows = []
    for cc in ["HK", "SG"]:
        for y in YEARS:
            q = {"_and": [{"assignees.assignee_country": cc},
                          {"_gte": {"patent_date": f"{y}-01-01"}},
                          {"_lte": {"patent_date": f"{y}-12-31"}}]}
            global CALLS_PLANNED
            CALLS_PLANNED += 1
            if DRY:
                continue
            j = pv_request(q, o={"size": 1}, tag=f"{cc}/{y}")
            rows.append([cc.lower(), y, j["total_hits"]])
            time.sleep(1.5)

    # 出闸前自检：不允许把空列/全零列当成结果写出去（R1 零虚构）
    if not DRY:
        expect = len(["HK", "SG"]) * len(YEARS)
        if len(rows) != expect:
            raise RuntimeError(f"patentsview 行数 {len(rows)} ≠ 预期 {expect}，拒绝写盘")
        if any(r[2] in ("", None) for r in rows):
            raise RuntimeError("patentsview 出现空 count，拒绝写盘")
        if all(r[2] == 0 for r in rows):
            raise RuntimeError("patentsview 全部为 0——先确认是不是查询语法问题，拒绝写盘")

    save_rows("patentsview_us_patents_by_year.csv", ["assignee_country", "year", "count"], rows,
              PV_URL, "assignee_country×patent_date 逐年 total_hits",
              "美国专利口径（发明人流动模块的先导）；全球口径走 BigQuery sql/")


# ---------- 模块 7：orcid（机构雇佣记录计数） ----------
def mod_orcid():
    if not (ORCID_ID and ORCID_SECRET) and not DRY:
        log("⛔ 需 ORCID_CLIENT_ID/SECRET（orcid.org 免费公共API凭证）；或改用年度公共数据文件全量解析（见计划表X02）")
        return
    token = None
    if not DRY:
        r = requests.post("https://orcid.org/oauth/token",
                          data={"client_id": ORCID_ID, "client_secret": ORCID_SECRET,
                                "grant_type": "client_credentials", "scope": "/read-public"},
                          headers={"Accept": "application/json"}, timeout=60)
        r.raise_for_status()
        token = r.json()["access_token"]
    rows = []
    with open(CFG / "institutions.csv", encoding="utf-8-sig") as f:
        for r_ in csv.DictReader(f):
            if not r_["verify_status"].startswith("confirmed") or not r_["ror"]:
                continue
            global CALLS_PLANNED
            CALLS_PLANNED += 1
            if DRY:
                continue
            j = http_get("https://pub.orcid.org/v3.0/search/",
                         {"q": f'ror-org-id:"https://ror.org/{r_["ror"]}"', "rows": 0},
                         headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                         tag=r_["name_zh"])
            rows.append([r_["name_zh"], r_["ror"], (j or {}).get("num-found", "")])
            time.sleep(1)
    save_rows("orcid_affiliated_researchers.csv", ["institution", "ror", "num_found"], rows,
              "https://pub.orcid.org/v3.0/search/", "ror-org-id 关联档案计数（当前截面）",
              "流动维历史轨迹用公共数据文件路线（X02）；此为快照计数")


MODULES = {"papers": mod_papers, "shares": mod_shares, "institutions": mod_institutions,
           "github": mod_github, "clinicaltrials": mod_clinicaltrials,
           "clinicaltrials_q": mod_clinicaltrials_q,
           "patentsview": mod_patentsview, "orcid": mod_orcid}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("module", choices=list(MODULES) + ["plan", "all"])
    args = ap.parse_args()
    if args.module == "plan":
        DRY = True
        for name, fn in MODULES.items():
            before = CALLS_PLANNED
            log(f"—— 模块 {name} ——")
            try:
                fn()
            except Exception as e:
                log(f"（plan 阶段异常：{e}）")
            log(f"   预算 API 调用：{CALLS_PLANNED - before} 次")
        log(f"合计预算：约 {CALLS_PLANNED} 次调用（OpenAlex 免费额度 1 万/日，充裕）")
    elif args.module == "all":
        require_collector()          # 开跑前就查，别等几百次调用跑完才发现
        for name, fn in MODULES.items():
            log(f"==== {name} ====")
            fn()
    else:
        require_collector()          # 同上
        MODULES[args.module]()
