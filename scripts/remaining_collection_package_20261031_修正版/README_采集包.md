# 港新 AI 与生物医药补采包

版本日期：2026-10-31

本包针对 GitHub 核查出的未完成部分，沿用现有口径与底稿，范围如下：

1. AI 与生物医药专利：按港新申请人、专利族和既有 CPC 范围，统一刷新 2015—2025 年公开记录，重点补生物医药 2025 年。金融及金融科技专利不在范围内。
2. AI 论文：重跑 2015—2025 年选定的 10 个会议目录与既有期刊来源。修复此前失败的 AAAI、ICLR、CVPR、ECCV、ICCV 年份，并复核 IJCAI 2016、NeurIPS 2025；同时复核其他已采年份的目录覆盖。
3. 港新作者识别：通过 OpenAlex 公开元数据匹配作者及机构，保留无法确认的记录供人工复核。

## Windows 快速运行

在 Windows PowerShell 中进入解压后的文件夹，先运行论文采集和 BigQuery 预估：

```powershell
.\run_all.ps1 -ProjectId "你的Google Cloud项目ID" -SkipPatents
```

第一次运行会安装依赖，并在终端以隐藏输入方式询问 OpenAlex API key。请先在 Google Cloud 配好 BigQuery 的 Application Default Credentials：

```powershell
gcloud auth application-default login
```

该登录需要 Google 账号可用的两步验证。OpenAlex key 只在当前 PowerShell 进程中使用，不写入包内文件。

论文采集完成后，执行专利查询的 dry run，查看 BigQuery 扫描量：

```powershell
.\run_all.ps1 -ProjectId "你的Google Cloud项目ID" -SkipPapers
```

确认扫描量在可接受范围后，才提交查询并下载专利数据。脚本默认上限为 50 GB，可用 `-MaxGb` 调整：

```powershell
.\run_all.ps1 -ProjectId "你的Google Cloud项目ID" -SkipPapers -ExecutePatents
```

`-ExecutePatents` 会提交可能产生费用的 BigQuery 查询；默认上限为 50 GB 扫描量，可用 `-MaxGb` 调整。若任务因限流或网络中断，可重复运行相同命令；HTTP 响应缓存和未完成的 BigQuery job 会尽量续跑。

若论文抓取中断或目录仍显示失败，重复运行 `.\run_all.ps1 -SkipPatents`，它会从缓存继续，并重试未成功的目录。若选择在 BigQuery 网页运行 SQL，必须导出完整结果（包括最后一行 `row_type=manifest`），再执行：

```powershell
.\.venv\Scripts\python.exe .\patents.py --csv "路径\BigQuery完整导出.csv"
```

也可只重跑论文：

```powershell
.\run_all.ps1 -SkipPatents
```

## 结果位置

- `results/papers/年度论文.csv`：港新按年、来源和类别的论文观察数。
- `results/papers/conference_coverage.csv`：会议主会目录规模、港新识别数及目录状态。
- `results/papers/catalog_status.csv`：各会议年份抓取状态；`failed`、`count_review_required`、`track_review_required` 代表还要处理，不能当作零。
- `results/papers/paper_tracks_to_review.csv`、`results/papers/review_queue.csv`：会议轨道、机构匹配及缺少作者归属的待复核记录。
- `results/patents/年度专利.csv`、`results/patents/季度专利.csv`：AI 与生物医药企业专利族观察数。
- `results/patents/new_assignees_to_classify.csv`：未归类申请人。确认类型后填入 `config/new_assignees.csv`，再用已下载的 `results/patents/raw_export.csv` 重新运行汇总。
- `results/collection_summary.json`：自动汇总会议目录状态、OpenAlex 年份覆盖、待复核论文数和专利分类状态。
- `logs/`：每次运行的控制台日志。

## 统计口径与边界

- 专利按申请人所在港/新地区与同一专利族统计；AI 与生物医药按 CPC 前缀筛选。跨类别专利族可能分别出现在两个行业。Alibaba/Ant 排除规则沿用已有配置。
- 查询回溯 2015—2025 年的公开记录，年内首个申请日按查询窗口计算。较近年份受专利公开延迟影响；2024—2025 必须保留“观察值、尚未完整”的标记。查询不可能取得尚未公开的申请。
- 企业专利计数只纳入已映射为公司的申请人；大学、公共研发机构及个人不自动计入企业。无法分类者留在待处理清单，不作为零值。
- 论文目录抓取成功只表示目录已解析，不代表港新作者归属完整。看状态文件、覆盖表和 review queue 后再决定能否进入分析。
- “当前目录采集完整”不等于研究对象的全部论文/专利都已被识别；本包不会用插值或预测填补。

## 包内底稿

`baseline/` 保存本次 GitHub 核查时的历史数据，供增量合并与差异比较。包内不含账号、密码、API key 或 Google Cloud 凭证。远程页面若持续拒绝访问，采集状态会显示失败；可将官方目录导出为 CSV 后按 `papers.py import-catalog` 说明导入，不能把失败的目录当作空目录。
