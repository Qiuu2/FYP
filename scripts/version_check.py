# -*- coding: utf-8 -*-
r"""
version_check.py —— 比对两份仓库副本的脚本/配置是否同版

为什么需要（2026-09-15）：
    賈贇在他自己机器上有一份 data_repo 副本，组长这边是另一份。
    两边会持续分叉——脚本在仓库这边修了，他那边还是旧的；
    他在旧版上改 collect_all.py 再回传，会把仓库的新版覆盖掉。
    「J4 开工前先确认版本」这种口头约定靠不住，所以做成一条命令。

用法：
    # 双方各跑一次，把输出存成文件
    python scripts/version_check.py > my_versions.txt

    # 任一方拿对方的文件做比对，直接报差异
    python scripts/version_check.py --compare my_versions.txt

输出的是 SHA256，不是 mtime——复制、同步、解压都会改 mtime，但不改内容。

R1：只读文件算哈希，不修改任何东西。
"""
import argparse, hashlib, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
# 扫这两组：脚本（会被改）与配置（口径决定，必须一致）
GROUPS = [("scripts", "scripts/*.py"), ("config", "config/*")]
SKIP_DIRS = {"__pycache__"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def collect():
    out = {}
    for _, pat in GROUPS:
        for p in sorted(ROOT.glob(pat)):
            if p.is_dir() or any(d in p.parts for d in SKIP_DIRS):
                continue
            out[p.relative_to(ROOT).as_posix()] = (sha256(p), p.stat().st_size)
    return out


def render(d):
    lines = [f"# version_check  root={ROOT}", f"# {len(d)} 个文件",
             f"{'文件':<46}{'sha256':<66}{'字节'}"]
    for k, (h, n) in d.items():
        lines.append(f"{k:<46}{h:<66}{n}")
    return "\n".join(lines)


def parse(text):
    d = {}
    for ln in text.splitlines():
        if ln.startswith("#") or ln.startswith("文件"):
            continue
        parts = ln.split()
        if len(parts) >= 3 and len(parts[1]) == 64:
            d[parts[0]] = (parts[1], int(parts[2]))
    return d


ap = argparse.ArgumentParser()
ap.add_argument("--compare", metavar="文件", help="对方 version_check 输出的文本文件")
args = ap.parse_args()

mine = collect()
if not args.compare:
    print(render(mine))
    sys.exit(0)

f = pathlib.Path(args.compare)
if not f.exists():
    sys.exit(f"⛔ 找不到 {f}")
theirs = parse(f.read_text(encoding="utf-8"))
if not theirs:
    sys.exit(f"⛔ {f} 里没解析出任何条目——确认它是 version_check.py 的原样输出")

same = [k for k in mine if k in theirs and mine[k][0] == theirs[k][0]]
diff = [k for k in mine if k in theirs and mine[k][0] != theirs[k][0]]
only_mine = [k for k in mine if k not in theirs]
only_theirs = [k for k in theirs if k not in mine]

print(f"本地 {len(mine)} 个 · 对方 {len(theirs)} 个 · 内容相同 {len(same)} 个\n")
if diff:
    print(f"⚠️ 内容不同 {len(diff)} 个——**动它们之前必须先统一版本**：")
    for k in diff:
        print(f"   {k}")
        print(f"      本地 {mine[k][0][:12]}… ({mine[k][1]} 字节)")
        print(f"      对方 {theirs[k][0][:12]}… ({theirs[k][1]} 字节)")
if only_mine:
    print(f"\n本地有、对方没有 {len(only_mine)} 个（对方需要补）：")
    for k in only_mine:
        print(f"   {k}")
if only_theirs:
    print(f"\n对方有、本地没有 {len(only_theirs)} 个（可能是他的本地产物，或仓库漏收）：")
    for k in only_theirs:
        print(f"   {k}")
if not (diff or only_mine or only_theirs):
    print("✅ 两边完全一致，可以直接开工")
else:
    print("\n统一办法：以**仓库**为准，把上面标出的文件从仓库拷过去覆盖；")
    print("          若对方那份含他尚未回传的修改，先回传、合并进仓库，再反向覆盖。")
