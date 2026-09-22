# -*- coding: utf-8 -*-
r"""
oa_count_probe.py —— 验证 OpenAlex 的 meta.count 与「cursor 实际可枚举条数」是否相等

要查的悬案（STATUS.md 第二节「一个未解释的差异」）：
    biomed/hk 的论文数在两次采集之间从 70,062（2026-08-26，取 meta.count）
    变成 85,760（2026-09-11，cursor 逐页枚举计数），+22.4%。
    已排除：重复计数（work_id 全唯一）、索引回填（增量十年均匀、机构分布正常）、
    filter 差异（源码一致）、采集失败。
    剩下最可能的解释：**在大结果集上，meta.count 是估计值，与可枚举条数本来就不相等。**

本脚本对同一个 filter 同时取两个数并比对：
    A = meta.count（第一页返回的总数字段）
    B = cursor 逐页枚举到底的实际条数

判读：
    A ≈ B（差 < 1%）  → meta.count 可信，+22.4% 另有原因，悬案继续查
    A < B 明显        → meta.count 在大结果集上偏低，**两次数字不可直接比较**，
                        STATUS 里那条「未解释差异」可以结案，并在方法章声明计数口径
    A > B 明显        → 枚举提前终止（cursor 断链/翻页丢失），是采集缺陷，必须修

用法（在**你自己的 Windows 机器**上跑，会话里的 shell 连不上 OpenAlex）：
    cd C:\FYP\data_repo
    $env:COLLECTOR_NAME = "賈贇"
    python scripts\oa_count_probe.py                       # 默认 biomed/hk/2015Q1
    python scripts\oa_count_probe.py --ind ai --cc sg --q 2019Q3
    python scripts\oa_count_probe.py --ind biomed --cc hk --full-year 2015

调用量：小结果集几次，整年可能上百次（每 200 条一次）。默认的单季度很省。
R1：本脚本只做计数比对，不写任何数据文件。
"""
import argparse, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_all as ca

ap = argparse.ArgumentParser()
ap.add_argument("--ind", default="biomed", choices=["ai", "biomed", "fintech"])
ap.add_argument("--cc", default="hk", choices=["hk", "sg"])
ap.add_argument("--q", default="2015Q1", help="季度，如 2015Q1")
ap.add_argument("--full-year", type=int, help="改成整年（调用量大得多）")
ap.add_argument("--dry", action="store_true",
                help="空跑：不发任何请求，只检查路径、import、口径规则、filter 拼装是否正常。"
                     "换机器后建议先跑一次这个。")
args = ap.parse_args()
if args.dry:
    ca.DRY = True          # ⚠️ 必须改模块属性；collect_all.DRY 是 import 时定好的模块级变量，
                           #    设环境变量没用（2026-09-11 在 collect_authors.py 上踩过这个坑）

if not args.dry and not os.environ.get("COLLECTOR_NAME"):
    sys.exit("⛔ 先设 COLLECTOR_NAME（R2：采集人必须是真名）\n   $env:COLLECTOR_NAME = \"賈贇\"")

ready, blocked = ca.load_rules()
spec = ready.get(args.ind)
if not spec:
    sys.exit(f"⛔ {args.ind} 不在 ready 里（blocked: {blocked.get(args.ind)}）")

if args.full_year:
    d0, d1, label = f"{args.full_year}-01-01", f"{args.full_year}-12-31", str(args.full_year)
else:
    y, q = int(args.q[:4]), int(args.q[-1])
    d0 = f"{y}-{3*(q-1)+1:02d}-01"
    d1 = [f"{y}-03-31", f"{y}-06-30", f"{y}-09-30", f"{y}-12-31"][q-1]
    label = args.q

ifilter = ca.industry_filter(spec)
base = {}
if not ifilter:
    base["search"] = " OR ".join(f'"{k}"' for k in spec["keywords"][:6])
flt = ",".join([x for x in (ifilter,
                            f"authorships.institutions.country_code:{args.cc}",
                            f"from_publication_date:{d0}",
                            f"to_publication_date:{d1}") if x])

print(f"探针：{args.ind}/{args.cc}/{label}")
print(f"filter = {flt}")
if base:
    print(f"search = {base['search']}")
print()

KEY, MAILTO = ca.KEY, ca.MAILTO
common = {"filter": flt, "mailto": MAILTO, **base, **({"api_key": KEY} if KEY else {})}

# ── A：meta.count ──
j = ca.http_get("https://api.openalex.org/works",
                {**common, "per_page": 1}, tag=f"probe-count/{args.ind}/{args.cc}/{label}")
if j is None:
    if args.dry:
        print("\n✅ 空跑通过：路径、import、口径规则、filter 拼装都正常。")
        print("   去掉 --dry 就会真的发请求。")
        sys.exit(0)
    sys.exit("⛔ 第一页就没拿到——检查网络，或 OpenAlex 是否在限流")
A = (j.get("meta") or {}).get("count")
print(f"A · meta.count            = {A:,}")

# ── B：cursor 枚举 ──
B, page, cursor = 0, 0, "*"
t0 = time.time()
while cursor:
    j = ca.http_get("https://api.openalex.org/works",
                    {**common, "per_page": 200, "cursor": cursor,
                     # select 与 collect_openalex_master.py 逐字一致：换一组 select 理论上
                     # 不改变可枚举条数，但这次比的就是「枚举到底有多少条」，
                     # 参数留任何差异，结论都会被人质疑不是同一件事。
                     "select": "id,publication_date,authorships,"
                               "citation_normalized_percentile,primary_location"},
                    tag=f"probe-enum/{args.ind}/{args.cc}/{label}/p{page}")
    if j is None:
        print("⚠️ 某一页没拿到，枚举中断——B 不完整，不要据此下结论")
        break
    got = j.get("results") or []
    B += len(got)
    page += 1
    cursor = (j.get("meta") or {}).get("next_cursor")
    if page % 10 == 0:
        print(f"    …第 {page} 页，累计 {B:,}")
    if page > 2000:
        print("⚠️ 超过 2000 页，主动停止")
        break
print(f"B · cursor 枚举实际条数   = {B:,}   （{page} 页，{time.time()-t0:.0f} 秒）")

# ── 判读 ──
print()
if not A:
    print("⛔ meta.count 缺失，无法比对")
else:
    d = B - A
    pct = d / A * 100
    print(f"差值 B − A = {d:+,}（{pct:+.2f}%）")
    if abs(pct) < 1:
        print("→ 两者一致。meta.count 可信，+22.4% 的差异**另有原因**，悬案继续查。")
    elif d > 0:
        print("→ **可枚举条数显著多于 meta.count**。说明 meta.count 在大结果集上是估计值。")
        print("   结论：2026-08-26 的 70,062（meta.count）与 2026-09-11 的 85,760（枚举）")
        print("   **本来就不是同一个量，不可直接相减**。STATUS 里那条未解释差异可以结案，")
        print("   并需在方法章声明：论文计数一律以 cursor 枚举为准。")
    else:
        print("→ **枚举少于 meta.count**。这是采集缺陷（cursor 断链或翻页丢失），必须修，")
        print("   且已入库的枚举型序列都要重新评估。")
print("\n把以上整段输出粘回给组长即可。")
