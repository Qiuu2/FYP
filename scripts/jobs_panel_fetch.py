# -*- coding: utf-8 -*-
"""
jobs_panel_fetch.py —— 阶段 3 前瞻面板：招聘页职位周度快照（学生本地运行）
==========================================================================
合规边界（不可越）：
  - 只调用公司主动公开给求职者的 ATS 职位板 JSON 接口（Greenhouse boards API /
    Lever postings API），绝不抓取 HTML 页面、绝不绕过任何访问控制；
  - 请求间隔 ≥ 2 秒；User-Agent 带团队联系邮箱（COLLECTOR_MAILTO）。

R6 闸门：config/jobs_panel_companies.csv 中 status 不以 confirmed 开头的公司
一律跳过——token 须人工在浏览器验证（打开 api_url 能看到 JSON 才算确认）。

用法（建议每周一，同一时段）：
  export COLLECTOR_NAME=姓名  COLLECTOR_MAILTO=组邮箱
  python scripts/jobs_panel_fetch.py            # 写 raw/forward_panel/jobs_snapshot_YYYY-MM-DD.csv ＋ manifest
  python scripts/jobs_panel_fetch.py --dry-run  # 只打印将采集哪些公司，不联网

口径说明（写入论文附录时引用）：
  - 快照 = 当日该公司职位板全部在招岗位（不筛选产业岗位，筛选在 clean 层做，规则留痕）；
  - 每周一个独立文件一个 manifest（不可变包裹模型）；缺采的周就空缺，绝不回填估计。
"""
import argparse, csv, hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CFG, RAW, MAN = ROOT / "config", ROOT / "raw", ROOT / "manifests"
OUT_DIR = RAW / "forward_panel"
BY = os.environ.get("COLLECTOR_NAME", "UNSET——请 export COLLECTOR_NAME")
MAILTO = os.environ.get("COLLECTOR_MAILTO", "team@example.edu")
UA = {"User-Agent": f"CUHK-GECC4130-FYP-research/1.0 (mailto:{MAILTO})"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(data_file: Path, source_urls: str, query: str, note: str = ""):
    rel = data_file.resolve().relative_to(RAW.resolve())
    # ⚠️ 必须 as_posix()（2026-09-15 修）：Windows 上 str(rel) 用反斜杠，
    #    .replace("/", "__") 根本替换不到，于是路径拼成
    #    manifests/forward_panel\xxx.json —— 那个子目录不存在 → FileNotFoundError。
    #    raw/ 下此前全是平铺文件，forward_panel/ 是第一个子目录，所以今天才暴露。
    #    scripts/manifest.py 的 man_path() 必须用同一套扁平化规则，否则 verify 找不到。
    out = MAN / (rel.as_posix().replace("/", "__") + ".manifest.json")
    MAN.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        # 同理：file 字段统一写 posix 分隔符，跨平台 manifest 才长得一样
        "file": data_file.relative_to(ROOT.resolve()).as_posix(), "sha256": sha256(data_file),
        "source_url": source_urls, "query_or_method": query,
        "collected_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collected_by": BY, "notes": note, "manifest_version": 1,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] manifest → {out.name}")


def fetch_greenhouse(token):
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                     headers=UA, timeout=60)
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        yield (str(j.get("id", "")), j.get("title", ""),
               (j.get("location") or {}).get("name", ""), j.get("updated_at", ""))


def fetch_lever(token):
    r = requests.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"},
                     headers=UA, timeout=60)
    r.raise_for_status()
    for j in r.json():
        ts = j.get("createdAt")
        created = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat() if ts else ""
        yield (j.get("id", ""), j.get("text", ""),
               (j.get("categories") or {}).get("location", ""), created)


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # R2（2026-09-15 补）：原来没有这道检查，没设 COLLECTOR_NAME 时 BY 会是
    # "UNSET——请 export COLLECTOR_NAME" 这个**非空字符串**，静默写进 manifest 的
    # collected_by，事后谁也看不出这份数据是谁采的。占位符是 truthy 的，判空拦不住。
    if not os.environ.get("COLLECTOR_NAME"):
        msg = ("没有设置 COLLECTOR_NAME，manifest 无法记录真实执行人（R2）。\n"
               "   PowerShell:  $env:COLLECTOR_NAME = \"你的名字\"\n"
               "   bash      :  export COLLECTOR_NAME=你的名字")
        if args.dry_run:
            print(f"[R2] ⚠️ {msg}\n   （--dry-run 不写 manifest，所以本次放行；真跑前必须设）")
        else:
            sys.exit(f"⛔ {msg}")

    companies = list(csv.DictReader(open(CFG / "jobs_panel_companies.csv", encoding="utf-8-sig")))
    todo = [c for c in companies if str(c.get("status", "")).startswith("confirmed")]
    skipped = [c["company"] for c in companies if c not in todo]
    if skipped:
        print(f"[R6] 跳过未确认公司 {len(skipped)} 家：{', '.join(skipped)}")
    if not todo:
        sys.exit("[R6] 没有任何 status=confirmed 的公司——先人工验证 token（浏览器打开 api_url 见 JSON），填好确认状态再跑")

    if args.dry_run:
        for c in todo:
            print(f"DRY 将采集 {c['company']}（{c['ats']}:{c['board_token']}）")
        sys.exit(0)

    today = datetime.now(timezone.utc).date().isoformat()
    out = OUT_DIR / f"jobs_snapshot_{today}.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows, failed, urls = [], [], []
    for c in todo:
        ats, token = c["ats"], c["board_token"]
        if ats not in FETCHERS or not token:
            failed.append(f"{c['company']}（ats/token 配置不完整）")
            continue
        try:
            n0 = len(rows)
            for job_id, title, loc, ts in FETCHERS[ats](token):
                rows.append([c["company"], c["industry"], ats, job_id, title, loc, ts])
            print(f"[OK] {c['company']}：{len(rows) - n0} 个在招岗位")
            urls.append(c["api_url"])
        except Exception as e:
            failed.append(f"{c['company']}（{e}）")
        time.sleep(2)

    if not rows:
        sys.exit(f"[中止] 全部公司采集失败，不写空文件。失败：{'; '.join(failed)}")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company", "industry", "ats", "job_id", "title", "location", "posted_or_updated"])
        w.writerows(rows)
    write_manifest(out, " ; ".join(urls),
                   "ATS 公开职位板 JSON 全量快照（Greenhouse boards API / Lever postings API）",
                   f"每周快照；失败公司如实留档：{'; '.join(failed) if failed else '无'}")
    print(f"[完成] raw/forward_panel/{out.name}：{len(rows)} 行；失败 {len(failed)} 家" +
          (f"（{'; '.join(failed)}）——失败即空缺，绝不回填" if failed else ""))
