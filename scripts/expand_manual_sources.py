# -*- coding: utf-8 -*-
r"""
expand_manual_sources.py —— 把人工采集包裹（p2–p6）的多来源展开进 manifest

起因（2026-08-26，陈于嘉 R4 复核）：
    manifest 的 schema 只有一个 `source_url` 字段，但 p2–p6 每一份都是**多源人工采集**：
      · p3：18C 官方表（SRC2）只有 14 家；18A 那 84 家来自头豹研报（SRC1）＋几十条媒体/律所链接
      · p4：SFC VATP 名册页只覆盖 13 家虚拟资产平台；8 家虚拟银行与 16 张 SVF 牌照
             各自来自 info.gov.hk 的独立新闻稿
      · p6：manifest 记的是岭南一校的 ROR 查询；逐年 works_count 来自 4 个 OpenAlex 机构端点，
             InnoHK 名录来自 ITC 的 PDF
    复核者点开那一个 source_url，自然只能核到一部分，于是判成"对不上"。
    **数据本身没问题——raw 文件里每一行都带自己的 source_url 或 SRC 声明，
    是 manifest 把多源压成了一个链接。**

本脚本做什么：
    从 raw 文件里**机械提取**所有出现过的 URL（不新增、不改写），
    统计每个 URL 被多少行引用、出现在哪个小节，写进 manifest 的 `sources` 数组。
    同时把 `source_url` 保留为主源，并加一句说明指向 sources。

诚实性（R1）：
    sources 里的每个 URL 都逐字来自 raw 文件，`covers` 只记「出现在哪个小节、被几行引用」
    这类可机械核对的事实，不做任何主观归纳。

用法：
    python scripts/expand_manual_sources.py
    python scripts/expand_manual_sources.py --check
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, MAN = ROOT / "raw", ROOT / "manifests"
# 两类引用都要抓：
#   ① 完整 URL —— 注意 ASCII 的 ')' 不能一律排除，p6 的主源就长这样：
#      https://api.ror.org/organizations?affiliation=Lingnan%20University%20(Hong%20Kong)
#   ② 裸域名 —— p3 的几十条媒体/律所引用没写 https://，形如
#      finance.sina.com.cn/roll/2026-06-17/doc-inicthnt6028877.shtml、phirda.com/artilce_31436.html
URL_RE = re.compile(r'https?://[^\s（）；;，,、"\'｜|]+')
BARE_RE = re.compile(
    r'(?<![\w/@.])((?:[a-z0-9][a-z0-9-]*\.)+(?:com|org|net|gov|edu|io|hk|cn)'
    r'(?:\.[a-z]{2})?/[^\s（）；;，,、"\'｜|)]+)')


def _tidy(u: str) -> str:
    u = u.rstrip('.,;：:')
    # 结尾的 ')' 若没有配对的 '(' 就是中文行文带出来的，去掉；配对的（如 (Hong%20Kong)）保留
    while u.endswith(')') and u.count('(') < u.count(')'):
        u = u[:-1]
    return u
SEC_RE = re.compile(r'^===\s*(.+?)\s*===')

NOTE = ("本包裹为多源人工采集：raw 文件内每一行都带自己的 source_url 或 SRC 声明。"
        "manifest 的 source_url 只是主源，**复核请以下方 sources 数组与 raw 文件内的逐行 URL 为准**。")


def scan(path: Path):
    """扫一遍 raw 文件，返回 {url: {rows, sections}}。纯机械提取。"""
    found = {}
    section = "（文件头）"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = SEC_RE.match(line.strip())
        if m:
            section = m.group(1)
            continue
        hits = [_tidy(u) for u in URL_RE.findall(line)]
        rest = URL_RE.sub(' ', line)          # 裸域名只在「完整 URL 之外」的部分找，避免重复
        hits += ['https://' + _tidy(u) for u in BARE_RE.findall(rest)]
        for u in hits:
            e = found.setdefault(u, {"rows": 0, "sections": []})
            e["rows"] += 1
            if section not in e["sections"]:
                e["sections"].append(section)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    for mp in sorted(MAN.glob("*.manifest.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        name = Path(m["file"].replace("\\", "/")).name
        raw = RAW / name
        if not raw.exists() or raw.suffix.lower() != ".txt":
            continue                      # 只处理人工采集的 .txt 包裹
        found = scan(raw)
        if len(found) <= 1:
            continue                      # 单一来源，无需展开

        if args.check:
            has = len(m.get("sources", []))
            print(f"  {name}: raw 内 {len(found)} 个不同 URL，manifest 已记 {has} 个"
                  f" {'✅' if has == len(found) else '⚠ 缺 %d 个' % (len(found) - has)}")
            continue

        primary = m.get("source_url", "")
        srcs = []
        for u, e in sorted(found.items(), key=lambda kv: (-kv[1]["rows"], kv[0])):
            srcs.append({
                "url": u,
                "referenced_by_lines": e["rows"],
                "appears_in_sections": e["sections"],
                **({"is_manifest_primary": True} if u == primary else {}),
            })
        m["sources"] = srcs
        m["sources_note"] = NOTE
        m["manifest_version"] = max(int(m.get("manifest_version", 1)), 2)
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        flagged = "（主源在列）" if any(s.get("is_manifest_primary") for s in srcs) else "（⚠ 主源不在 raw 文件中出现）"
        print(f"  ✅ {name}: 展开 {len(srcs)} 个来源 {flagged}")


if __name__ == "__main__":
    main()
