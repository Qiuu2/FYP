# -*- coding: utf-8 -*-
"""
manifest.py —— 真实性规范 R1/R2/R5 的落地工具
================================================
每个进入 raw/ 的数据文件必须有 manifest（来源 URL、查询、时间戳、执行人、SHA256）。
无 manifest 的文件 = 不存在的数据（qa_check.py 会拦截）。

用法：
  python scripts/manifest.py add raw/xxx.csv --url "https://..." --query "..." --by "姓名" [--note "..."]
  python scripts/manifest.py verify          # 校验 raw/ 全部文件：有 manifest 且哈希一致
"""
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, MAN = ROOT / "raw", ROOT / "manifests"

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def man_path(data_file: Path) -> Path:
    rel = data_file.resolve().relative_to(RAW.resolve())
    # ⚠️ as_posix() 不能省（2026-09-15 修）：Windows 上 str(rel) 是反斜杠，
    #    replace("/", "__") 替换不到，子目录里的文件会算出一个不存在的路径。
    #    写入端 jobs_panel_fetch.py 用的是同一套规则，两边必须一致。
    return MAN / (rel.as_posix().replace("/", "__") + ".manifest.json")

def cmd_add(a):
    p = Path(a.file).resolve()
    if RAW.resolve() not in p.parents:
        sys.exit(f"[拒绝] 数据文件必须放在 raw/ 下：{p}")
    if not p.exists():
        sys.exit(f"[拒绝] 文件不存在：{p}")
    if not a.url.startswith(("http://", "https://")):
        sys.exit("[拒绝] --url 必须是可回访的 http(s) 来源（R1：无来源的数据不入库）")
    m = {
        "file": p.relative_to(ROOT.resolve()).as_posix(),   # 跨平台一致：统一正斜杠
        "sha256": sha256(p),
        "source_url": a.url,
        "query_or_method": a.query,
        "collected_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collected_by": a.by,
        "notes": a.note or "",
        "manifest_version": 1,
    }
    out = man_path(p)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] manifest 写入 {out.relative_to(ROOT)}  sha256={m['sha256'][:12]}…")

def cmd_verify(_a):
    problems, n = [], 0
    for p in sorted(RAW.rglob("*")):
        if p.is_dir() or p.name == ".gitkeep":
            continue
        # _archive/ 是归档区：文件连同自己的 manifest 一起存放，不参与 raw/ 的溯源校验
        if "_archive" in p.relative_to(RAW).parts:
            continue
        n += 1
        mp = man_path(p)
        if not mp.exists():
            problems.append(f"缺 manifest：{p.relative_to(ROOT)}")
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        if m.get("sha256") != sha256(p):
            problems.append(f"哈希不匹配（文件被改动？）：{p.relative_to(ROOT)}")
        # R4 可复核性：source_url 必须是能点开的真实地址，且 API 类数据要有逐行请求日志
        su = m.get("source_url", "") or ""
        if "{" in su or "}" in su:
            problems.append(f"source_url 含未替换的模板变量（点开会 404）：{mp.name} → {su}")
        # 带查询串的 API URL 本身就能点开复现（p2/p6 这类人工采集就是如此）；
        # 只有「光秃秃的端点」才需要逐行请求日志来补
        bare_api = (("/api/" in su) or su.startswith(("https://api.", "https://pub."))) and "?" not in su
        if bare_api and not m.get("request_log"):
            problems.append(
                f"API 类数据缺 request_log（复核者拿端点回查不出具体那一行）：{mp.name}"
                f"；跑 python scripts/rebuild_request_urls.py 回填")
        elif m.get("request_log") and not (MAN / m["request_log"]).exists():
            problems.append(f"request_log 指向的文件不存在：{mp.name} → {m['request_log']}")

        # 人工采集的多源包裹：raw 里出现多个 URL 就必须在 manifest 里列全，
        # 否则复核者只拿到主源一个链接，会把"核不到"误判成"数据错"（2026-08-26 实际发生过）
        if p.suffix.lower() == ".txt":
            import re as _re
            txt = p.read_text(encoding="utf-8", errors="replace")
            n_url = len(set(_re.findall(r'https?://[^\s（）；;，,、"\'｜|]+', txt)))
            if n_url > 1 and not m.get("sources"):
                problems.append(
                    f"多源人工包裹缺 sources 列表（raw 内有 {n_url} 个不同 URL，manifest 只给了 1 个）："
                    f"{mp.name}；跑 python scripts/expand_manual_sources.py 展开")

        for k in ("source_url", "query_or_method", "collected_utc", "collected_by"):
            v = m.get(k)
            if not v:
                problems.append(f"manifest 字段缺失 {k}：{mp.name}")
            elif isinstance(v, str) and v.startswith("UNSET"):
                # 占位符是 truthy 的，光判空会漏过去——R2 要求记录真实执行人
                problems.append(f"manifest 的 {k} 还是占位符 {v!r}：{mp.name}"
                                f"（跑之前要设 COLLECTOR_NAME）")
    # 反向：孤儿 manifest
    for mp in MAN.glob("*.manifest.json"):
        f = ROOT / json.loads(mp.read_text(encoding="utf-8"))["file"].replace("\\", "/")
        if not f.exists():
            problems.append(f"孤儿 manifest（数据文件已不存在）：{mp.name}")
    print(f"扫描 raw/ 数据文件 {n} 个")
    if problems:
        print("❌ 未通过：")
        [print("  -", x) for x in problems]
        sys.exit(1)
    print("✅ 全部通过：每个文件都有完整 manifest 且哈希一致")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("file"); a.add_argument("--url", required=True)
    a.add_argument("--query", required=True); a.add_argument("--by", required=True); a.add_argument("--note")
    sub.add_parser("verify")
    args = ap.parse_args()
    {"add": cmd_add, "verify": cmd_verify}[args.cmd](args)
