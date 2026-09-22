# -*- coding: utf-8 -*-
r"""
odp_patents_fetch.py —— PatentsView 迁移到 USPTO ODP 之后的替代采集路线（路线 B）

背景：USPTO 于 2026-03-20 把 PatentsView 迁到 Open Data Portal，search/API 全部暂停，
      原来的 search.patentsview.org/api/v1/patent/ 已不可用。批量表已在 ODP 上提供。
口径：与原 patentsview_us_patents_by_year.csv 完全一致——
      美国授权专利 × 申请人国别(HK/SG) × 授权年，不分产业。

分三步走，每步都可以单独跑：

  1) 探测——看 ODP 上这个产品到底有哪些文件（文件名/大小/下载地址）
     python odp_patents_fetch.py discover
     python odp_patents_fetch.py discover --key <你的ODP_API_KEY>

  2) 下载——把探测到的文件抓下来（可给多个 URL），存到 raw/_bulk/
     python odp_patents_fetch.py fetch --url <URL1> --url <URL2>

  3) 聚合——读本地文件，产出 raw/patentsview_us_patents_by_year.csv + manifest
     python odp_patents_fetch.py aggregate --patent-file raw/_bulk/g_patent.tsv.zip \
                                           --assignee-file raw/_bulk/g_assignee_disambiguated.tsv.zip

为什么分三步：ODP 的产品页是 JS 渲染的，确切的文件名和下载地址没法离线断言。
本脚本不硬编码任何未经证实的表名/URL——第 3 步的列名也是**读表头自动识别**的，
识别到什么会明确打印出来，识别不出就报错停下，绝不猜。
"""
import argparse
import csv
import hashlib
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW, MAN = ROOT / "raw", ROOT / "manifests"
BULK = RAW / "_bulk"
BY = os.environ.get("COLLECTOR_NAME", "UNSET——请设置 COLLECTOR_NAME")
COUNTRIES = ["HK", "SG"]
YEARS = list(range(2015, 2026))

# 端点路径来自 USPTO 官方文档 BDSS-to-ODP-API-Mapping.pdf；
# 主机名按 2026-08-26 实测更正：data.uspto.gov 会返回 400 并明确指路——
# "Please use the api.uspto.gov endpoint as this endpoint is intended for the web UI use only"
ODP_PRODUCT = "https://api.uspto.gov/api/v1/datasets/products/{short_name}"
ODP_SEARCH = "https://api.uspto.gov/api/v1/datasets/products/search"
# PatentsView 授权专利消歧数据产品的 short name（来自 data.uspto.gov/bulkdata/datasets/pvgpatdis）
SHORT_NAME = "pvgpatdis"


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# ---------------- 步骤 1：探测 ----------------
def _fmt_size(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def _show_product(prod):
    print(f"\n  产品 {prod.get('productIdentifier')} —— {prod.get('productTitleText')}")
    print(f"    更新频率={prod.get('productFrequencyText')}  "
          f"覆盖 {prod.get('productFromDate')} … {prod.get('productToDate')}  "
          f"格式={','.join(prod.get('mimeTypeIdentifierArrayText') or [])}")
    print(f"    共 {prod.get('productFileTotalQuantity')} 个文件，"
          f"合计 {_fmt_size(prod.get('productTotalFileSize') or 0)}")
    files = ((prod.get("productFileBag") or {}).get("fileDataBag")) or []
    if not files:
        return
    print(f"    {'文件名':<52}{'大小':>12}  覆盖区间")
    for f in files:
        print(f"    {f.get('fileName',''):<52}{_fmt_size(f.get('fileSize') or 0):>12}  "
              f"{f.get('fileDataFromDate','')}…{f.get('fileDataToDate','')}")
        print(f"      {f.get('fileDownloadURI','')}")


def cmd_discover(args):
    key = args.key or os.environ.get("ODP_API_KEY", "")
    headers = {"X-API-KEY": key} if key else {}
    if not key:
        log("⚠ 没提供 ODP API key。api.uspto.gov 需要 key，"
            "先去 https://data.uspto.gov/apis/getting-started 注册一把再跑。")

    for i, short in enumerate(args.product):
        if i:
            time.sleep(4)                 # ODP 限速很紧，实测连发会 429
        url = ODP_PRODUCT.format(short_name=short)
        log(f"→ GET {url}")
        try:
            r = requests.get(url, headers=headers, timeout=60)
        except Exception as e:
            print(f"   请求异常: {type(e).__name__}: {e}")
            continue
        print(f"   status={r.status_code}")
        if r.status_code == 429:
            print("   限速了，等 30 秒后自己重跑这一条即可。")
            continue
        if r.status_code != 200:
            print("   " + r.text[:600].replace("\n", "\n   "))
            continue
        j = r.json()
        for prod in j.get("bulkDataProductBag", []):
            _show_product(prod)

    print("\n把上面整段输出发回给邱正阳/Claude，用来确定要下哪几个文件。")


# ---------------- 步骤 2：下载 ----------------
def cmd_fetch(args):
    BULK.mkdir(parents=True, exist_ok=True)
    key = args.key or os.environ.get("ODP_API_KEY", "")
    headers = {"X-API-KEY": key} if key else {}
    for url in args.url:
        name = url.split("?")[0].rstrip("/").split("/")[-1] or "download.bin"
        dest = BULK / name
        log(f"下载 {url}")
        with requests.get(url, headers=headers, stream=True, timeout=600) as r:
            if r.status_code != 200:
                raise SystemExit(f"HTTP {r.status_code}：{r.text[:400]}")
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        print(f"\r   {done>>20} / {total>>20} MiB ({pct}%)", end="", flush=True)
            print()
        log(f"→ {dest}（{dest.stat().st_size>>20} MiB, sha256={sha256(dest)[:16]}…）")
    log(f"全部下载完成，存放在 {BULK}")


# ---------------- 步骤 2.5：查看下载下来的文件里有什么 ----------------
def cmd_inspect(args):
    """把 zip 里每个表的文件名、表头、前两行样例打出来。
    PVANNUAL 每年一个 zip，里面装的是哪几张表、列名叫什么，官方文档没写清楚，
    必须实际打开看——本命令就干这个，不下载全量、不猜列名。"""
    p = Path(args.file)
    if not p.exists():
        raise SystemExit(f"找不到 {p}——先跑 fetch 下载。")
    log(f"检查 {p.name}（{p.stat().st_size >> 20} MiB）")

    if p.suffix.lower() != ".zip":
        header, rdr, delim = open_table(p)
        print(f"\n  分隔符={'TAB' if delim == chr(9) else delim!r}")
        print(f"  表头（{len(header)} 列）: {header}")
        for i, row in enumerate(rdr):
            if i >= 2:
                break
            print(f"  样例{i+1}: {str(row)[:400]}")
        return

    z = zipfile.ZipFile(p)
    members = z.infolist()
    print(f"\n  zip 内含 {len(members)} 个文件：")
    for m in members:
        print(f"    {m.filename:<46}{m.file_size:>14,} B（解压后）")

    for m in members:
        if m.is_dir() or not m.filename.lower().endswith((".csv", ".tsv", ".txt")):
            continue
        print(f"\n  ── {m.filename} ──")
        with z.open(m) as fh:
            raw = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
            first = raw.readline()
            delim = "\t" if first.count("\t") > first.count(",") else ","
            header = next(csv.reader([first], delimiter=delim))
            print(f"    分隔符={'TAB' if delim == chr(9) else delim!r}   共 {len(header)} 列")
            print(f"    表头: {header}")
            hits = [h for h in header if "countr" in h.lower()]
            print(f"    含 country 的列: {hits or '（无——这张表可能不带国别）'}")
            rdr = csv.reader(raw, delimiter=delim)
            for i, row in enumerate(rdr):
                if i >= 2:
                    break
                print(f"    样例{i+1}: {str(row)[:400]}")

    print("\n把上面整段发回来，我据此写聚合逻辑——列名不靠猜（R1）。")


# ---------------- 步骤 3：聚合 ----------------
def open_table(path: Path):
    """打开 .tsv / .csv / .zip(内含单个表)，返回 (表头list, 行迭代器, 分隔符)。"""
    if path.suffix.lower() == ".zip":
        z = zipfile.ZipFile(path)
        inner = [n for n in z.namelist() if n.lower().endswith((".tsv", ".csv", ".txt"))]
        if len(inner) != 1:
            raise SystemExit(f"{path.name} 里有 {len(inner)} 个表文件，不确定用哪个：{inner}")
        log(f"{path.name} → 内含 {inner[0]}")
        raw = io.TextIOWrapper(z.open(inner[0]), encoding="utf-8", errors="replace", newline="")
    else:
        raw = open(path, encoding="utf-8", errors="replace", newline="")
    first = raw.readline()
    delim = "\t" if first.count("\t") > first.count(",") else ","
    header = next(csv.reader([first], delimiter=delim))
    return header, csv.reader(raw, delimiter=delim), delim


def pick_column(header, must_have, label, path_name):
    """按关键词自动识别列名；命中不唯一或为 0 就报错停下，绝不猜。"""
    cands = [h for h in header if all(w in h.lower() for w in must_have)]
    if len(cands) == 1:
        log(f"   {label} → 列 '{cands[0]}'")
        return header.index(cands[0])
    raise SystemExit(
        f"在 {path_name} 里识别 {label} 失败：关键词 {must_have} 命中 {cands or '0 列'}。\n"
        f"该表实际表头：{header}\n"
        f"请把这份表头贴回对话，由人确认用哪一列，不要自行猜测（R1 零虚构）。")


def cmd_aggregate(args):
    pf, af = Path(args.patent_file), Path(args.assignee_file)
    for p in (pf, af):
        if not p.exists():
            raise SystemExit(f"找不到 {p}——先跑 fetch，或用 --patent-file/--assignee-file 指定正确路径。")

    log(f"读申请人表 {af.name}")
    a_header, a_rows, _ = open_table(af)
    i_pid = pick_column(a_header, ["patent", "id"], "专利ID", af.name)
    i_cc = pick_column(a_header, ["country"], "申请人国别", af.name)

    want = {c: set() for c in COUNTRIES}
    n = 0
    for row in a_rows:
        n += 1
        if len(row) <= max(i_pid, i_cc):
            continue
        cc = (row[i_cc] or "").strip().upper()
        if cc in want:
            want[cc].add(row[i_pid])
    log(f"   扫描 {n:,} 行；" + "，".join(f"{c}={len(want[c]):,} 件" for c in COUNTRIES))
    if all(not want[c] for c in COUNTRIES):
        raise SystemExit("HK 和 SG 一件都没匹配到——国别列的取值可能不是两位码，"
                         "把该列的若干样例值贴回对话再定，拒绝产出空数据（R1）。")

    log(f"读专利表 {pf.name}")
    p_header, p_rows, _ = open_table(pf)
    j_pid = pick_column(p_header, ["patent", "id"], "专利ID", pf.name)
    j_date = pick_column(p_header, ["patent", "date"], "授权日", pf.name)

    counts = {(c, y): 0 for c in COUNTRIES for y in YEARS}
    outside = 0
    m = 0
    for row in p_rows:
        m += 1
        if len(row) <= max(j_pid, j_date):
            continue
        pid, d = row[j_pid], (row[j_date] or "")[:4]
        if not d.isdigit():
            continue
        y = int(d)
        for c in COUNTRIES:
            if pid not in want[c]:
                continue
            if (c, y) in counts:
                counts[(c, y)] += 1
            else:
                outside += 1          # 命中 HK/SG 但授权年不在 2015–2025 区间内
    log(f"   扫描 {m:,} 行；落在 {YEARS[0]}–{YEARS[-1]} 之外的命中 {outside:,} 件（已排除）")

    rows = [[c.lower(), y, counts[(c, y)]] for c in COUNTRIES for y in YEARS]
    if len(rows) != len(COUNTRIES) * len(YEARS):
        raise SystemExit(f"行数 {len(rows)} ≠ 预期 {len(COUNTRIES)*len(YEARS)}，拒绝写盘")
    if all(r[2] == 0 for r in rows):
        raise SystemExit("全部为 0——先确认匹配逻辑，拒绝写盘（R1 零虚构）")

    RAW.mkdir(parents=True, exist_ok=True)
    MAN.mkdir(parents=True, exist_ok=True)
    out = RAW / "patentsview_us_patents_by_year.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["assignee_country", "year", "count"])
        w.writerows(rows)
    log(f"raw/{out.name} 写入 {len(rows)} 行")

    man = MAN / (out.name + ".manifest.json")
    man.write_text(json.dumps({
        "file": f"raw/{out.name}", "sha256": sha256(out),
        "source_url": f"https://data.uspto.gov/bulkdata/datasets/{SHORT_NAME}",
        "query_or_method": (
            f"ODP 批量表本地聚合：{af.name}（列 {a_header[i_cc]}）筛 HK/SG → "
            f"{pf.name}（列 {p_header[j_date]}）取授权年 → 按国别×年计数"),
        "source_files": [
            {"name": af.name, "sha256": sha256(af), "bytes": af.stat().st_size},
            {"name": pf.name, "sha256": sha256(pf), "bytes": pf.stat().st_size},
        ],
        "collected_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collected_by": BY,
        "notes": ("PatentsView API 自 2026-03-20 随 USPTO ODP 迁移暂停，改走批量表；"
                  "口径与原 API 版一致（美国授权专利×申请人国别×授权年）"),
        "manifest_version": 1,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"manifest → {man.name}")
    print("\n结果预览：")
    for c in COUNTRIES:
        print(f"  {c}: " + " ".join(f"{y}={counts[(c,y)]}" for y in YEARS))


def main():
    ap = argparse.ArgumentParser(description="PatentsView→ODP 替代采集（路线B）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover", help="探测 ODP 上的文件清单")
    d.add_argument("--key", default="")
    d.add_argument("--product", action="append", default=None,
                   help="产品短名，可给多个；默认 PVANNUAL（年度小 CSV）与 PVGPATDIS（全量大表）")
    d.set_defaults(func=cmd_discover)
    f = sub.add_parser("fetch", help="下载批量文件")
    f.add_argument("--url", action="append", required=True)
    f.add_argument("--key", default="")
    f.set_defaults(func=cmd_fetch)
    n = sub.add_parser("inspect", help="查看下载文件里有哪些表、列名是什么")
    n.add_argument("--file", required=True)
    n.set_defaults(func=cmd_inspect)
    g = sub.add_parser("aggregate", help="本地聚合产出 CSV+manifest")
    g.add_argument("--patent-file", required=True)
    g.add_argument("--assignee-file", required=True)
    g.set_defaults(func=cmd_aggregate)
    args = ap.parse_args()
    if getattr(args, "product", None) is None and args.cmd == "discover":
        args.product = ["PVANNUAL", SHORT_NAME]
    args.func(args)


if __name__ == "__main__":
    main()
