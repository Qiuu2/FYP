# 金融学论文与金融相关专利采集包

## 目的和范围

分别采香港及新加坡2015—2025年的金融学论文、三年活跃研究作者和金融相关专利；两个地区同口径，方便比较。论文以OpenAlex的 Finance 子领域2003为主，非此前金融科技关键词口径。默认只选被标为主主题的期刊文章；可用 `--scope any` 做任何主题命中敏感性比较，两种口径不要混用。研究者为有相应地区机构署名且最近三年发表过筛选论文、OpenAlex作者ID去重的作者；它不是金融业就业人数，也不应把作者数和就业人数直接相加。

专利以申请人标注HK/SG和G06Q40为筛选条件，包含部分税务、会计及技术服务，需要查看明细；**它是金融相关可专利化技术的代理，并非传统金融业全部产出，也无法识别所有金融创新**。没有以狭义CPC替代金融行业；将金融企业作为申请人单独核对，不能自动把科技公司判成金融企业。

## 一、论文和研究作者

需要 Python 3.10 或以上，以及具有 OpenAlex API权限的key。首次到 https://openalex.org/ 了解注册、额度及收费；网络、配额或权限会影响运行。默认从2013年起下载，以便计算2015年的三年活跃作者。每一年每地区完成后保存，断线可重复命令续跑。API响应按当前快照，并非历年当时实时能取得的数据。

Windows PowerShell（不要在共享屏幕输入密钥）：

```powershell
$env:OPENALEX_API_KEY = Read-Host 'OpenAlex API key'
py -3 .\collect.py papers --start 2015 --end 2025 --countries HK,SG
```

如果 `py` 不可用但已安装Python，用 `python .\collect.py papers ...`。`--scope any` 输出为另一口径并覆盖年度结果CSV，可先将结果另存； `--refresh` 重新查询当次选择的范围而非沿用缓存。汇总见 `results/finance_papers_annual.csv`；缓存和manifest在 `results/`。`incomplete` 或空白不是零，失败返回非零退出码。统计为两地分别完整计数，跨地区合作可分别计入；署名缺少机构／作者ID和作者消歧误差会导致遗漏或偏差。港新映射依OpenAlex国家代码HK/SG，港校归属被编码为CN或缺失的记录可能遗漏，需要抽样审计，不能说是全量。

## 二、金融相关专利

需可使用BigQuery的Google Cloud账号及计费项目。公开数据查询也可能产生费用，请先在BigQuery网页打开 `finance_patents.sql`，检查2015—2025日期及预计扫描量，然后运行并导出**完整CSV**，例如存成 `patents.csv`；不要将凭据或原始大文件上传GitHub。BigQuery使用地区、权限和账单以账号实际设置为准。未公开专利无法采到，尤其最近年份不成熟。

然后在PowerShell运行：

```powershell
py -3 .\collect.py patents --csv .\patents.csv
```

默认 `assignees.csv` 是空分类表：输出所有CPC命中专利族与待分类名单，但金融企业数此时**尚不可作为真实零值**。在 `results/assignees_to_review.csv` 审核申请人，把名称和类型填入 `assignees.csv` 后重跑。类型允许 `financial_firm`（确认金融机构）、`other_company`、`university`、`public_rd`、`individual`、`other`、`unknown`。没有地区或主体的可靠信息不要猜；同一族可有多个主体，各类计数可重叠。名称的归属地、总部和研发地点不一定相同。`results/finance_patents_annual.csv` 按地区和申请年输出；未有记录的年份不会伪造零，`families_with_unknown_assignee` 是待核而非缺失总量估算。

按地区与专利族去重，采用2015—2025查询窗口内、同时满足地区和CPC条件的最早申请日，并非全球最早优先权日；某些早于2015年首次申请的族可能被计到窗口内。结果只包含已公开且数据源覆盖的记录，无效或无family ID被排除；不能用来计算全行业产值。先汇报全命中与已确认金融机构两列，不把未知申请人当成金融机构。2024—2025特别需要标记为未成熟。

## 离线检查

```powershell
py -3 -m unittest -v test_collect.py
```

检查为模拟数据，不代表API、BigQuery权限或数据采集已通过。结果文件只在本地生成，`results/` 不上传。来源说明： https://explore.openalex.org/subfields/2003 、 https://help.openalex.org/data/works/attributes/ 、 https://docs.cloud.google.com/bigquery/public-data 、 https://www.wipo.int/classifications/ipc/en/ITsupport/Version20260101/transformations/ipc/20260101/en/htm/G06Q.htm
