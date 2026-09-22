# FYP 数据仓库（阶段 0 基建版）

> ## 👉 先看 [`STATUS.md`](STATUS.md)
> 项目**当前**进度、卡在哪、下一步做什么、以及**已被证伪的判断**（别重复踩坑），
> 全在那一份里。本 README 只讲仓库结构与七条铁律，不含进度。
>
> 看板（浏览器打开）：`docs/Phase2采集进度.html` · `docs/效度关前的最短路径.html`


2026-08-14 初始化。目标：让「数据完全真实、全程可溯源」成为机制而不是口号。

## 目录结构

```
data_repo/
├── raw/        原始响应与下载文件（只进不改；每个文件必须有 manifest）
├── manifests/  每个 raw 文件的溯源记录（URL、查询、时间戳、执行人、SHA256）
├── clean/      分析用 CSV（每个文件必须有 .prov.json 回指 manifest）
├── config/     边界规则 v1、机构清单、待裁决 case 日志
├── scripts/    见下
└── docs/       口径文档与看板
```

### scripts/ 现在有什么（2026-09-11）

| 脚本 | 干什么 |
|---|---|
| `manifest.py` | R2 的溯源登记与 `verify` 校验 |
| `collect_all.py` | Phase 2 各模块采集（papers / shares / institutions / clinicaltrials / …） |
| **`collect_openalex_master.py`** | **OpenAlex 统一采集包 v2：一次遍历产出指标 1、4、5、7 ＋指标 6 原料** |
| `authors_build.py` | 指标 1 · 三年滚动存量＋流量双序列 |
| `works_build.py` | 指标 4、5、7 |
| `patents_build.py` / `fix_assignees.py` | 指标 8 · 专利族与申请人 |
| `licenses_build.py` | 指标 9 金融 · 牌照事件流 → 累计存量 |
| `institutions_series_build.py` | 机构序列重建 |
| `rebuild_request_urls.py` | 补建 requests.tsv |

⚠️ `collect_authors.py` 已于 2026-09-11 被 `collect_openalex_master.py` 取代，移入 `_to_delete/`。

## 七条铁律（全组签署，写进 proposal 第七章）

- **R1 数据零虚构**：一切数值必须来自可存档的源响应；AI 只写代码与文档，永不产生数据值。无来源 URL 的数字一律不入库（`manifest.py add` 会直接拒绝）。
- **R2 Manifest 制**：raw/ 下每个文件配 manifest（源 URL、查询、UTC 时间戳、执行人、SHA256）。`python scripts/manifest.py verify` 一键校验。
- **R3 图表溯源**：报告每张图表脚注标注 prov/manifest 编号，评审可回查原始响应。
- **R4 双人复核**：每个数据模块由非采集者抽样 5% 对照源核对并在 commit 中签名。
- **R5 版本冻结**：进入分析的数据打 git tag；报告只引用 tag 版本。
- **R6 状态诚实**：config 中所有 ID 带验证状态；`status != confirmed` 的 ID 不得用于正式采集。
- **R7 爬虫边界**：仅解析公开目录页（园区名录、监管名单），遵守 robots.txt 与低频率；不触碰 LinkedIn、Crunchbase 等禁爬平台；每次解析存档原始 HTML 于 raw/。

## 快速上手

```bash
pip install requests pyyaml
# 1) 采集到一个文件后，立刻登记 manifest：
python scripts/manifest.py add raw/hk_ai_by_year.json \
  --url "https://api.openalex.org/works?filter=..." \
  --query "group_by=publication_year" --by "张三"
# 2) 生成 clean CSV 时写 .prov.json（模板见 docs/入库流程.md）
# 3) 每次 commit 前：
python scripts/manifest.py verify && python scripts/qa_check.py
# 4) 解析 pending 的 ID（需 OPENALEX_KEY）：
python scripts/resolve_ids.py ror
python scripts/resolve_ids.py openalex
```

## 阶段 0 完成状态（2026-08-14）

已确认（实体端点实测）：港五校＋NUS/NTU 的 ROR 与 OpenAlex 记录；浸会/教大 ROR 已解析待复核。
仍为 pending（诚实记录，resolver 首跑补齐）：岭南、ASTRI、InnoHK 实验室清单；OpenAlex AI 子领域
（subfields/1702）与生医 fields 的 display_name 确认；全部顶会/顶刊的 source ID。
教训纪念：ROR 模糊检索曾把「岭南大学」匹配成港大、把「应科院」匹配成科技园——
所以 resolver 只产出候选文件，人工确认后才允许进入正式配置（R6）。

## 阶段 2：全量采集（collect_all.py）

填好环境变量后：`python scripts/collect_all.py plan` 看计划与配额 → 按模块执行
（papers/shares/institutions/github/clinicaltrials/patentsview/orcid）。
BigQuery 两件（企业/大学专利、GH Archive 协作）在 `sql/`，控制台运行后把导出
CSV 放入 raw/ 并 `manifest.py add`。注意：AI 与生医的论文拉取会被 R6 拦住，
直到 `resolve_ids.py` 的候选经人工确认搬入 boundary_rules_v1.yaml（status 改
confirmed）——这是设计行为，不是 bug。
