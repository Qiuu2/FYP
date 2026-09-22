> # ⚠️ 已过期（2026-08-25 那一轮）
> 这份是 **papers / shares / institutions** 重跑那一轮的说明，保留作记录。
> **当前这一轮请看 `FYP_OpenAlex统一采集包_给賈贇_2026-09-11.zip` 里的「请先读我.md」。**
> 那一轮之后 `collect_authors.py` 已被 `collect_openalex_master.py` 取代，
> 这份里的命令不要再照抄。

# 給賈贇：Phase 2 采集重跑（papers / shares / institutions）

> 2026-08-25 邱正阳整理。你上次跑出来的 raw.zip 里有两处是**脚本 bug**导致的坏数据，
> bug 已经修好，这个包里的 `collect_all.py` 是修复版。
> 从这一轮起，Phase 2 的采集统一由你来跑（邱正阳的机器另有任务）。

## 一、修了什么（你不用改代码，知道一下就行）

1. **biomed 论文数全是 0** —— 不是真的没论文。原来的 `industry_filter()` 不分青红皂白把所有产业 ID 都拼成
   `primary_topic.subfield.id`，但 OpenAlex 的 field 和 subfield 是**两套不重叠的编号体系**
   （field 是两位数，27=Medicine、13=Biochemistry；subfield 一律四位数，1702=AI）。
   biomed 确认的是 `fields/27` + `fields/13`，拿 field 的号去查 subfield 一条都查不到，所以全线归零。
   现在按各 ID 自带的 `fields/` / `subfields/` 前缀分别拼接。

2. **shares 分母只有 2 行**（应该有 44 行）—— 两个 bug：
   - `publication_year` 不支持 `2015-2025` 这种连字符区间写法，改成 `publication_year:>2014,publication_year:<2026`；
   - `group_by` 的分组条数和 `per_page` 共用同一个每页上限，原来 `per_page=1` 导致每次只拿回 1 组，改成 200。

3. **patentsview 这次不用跑**。USPTO 已于 2026-03-20 把 PatentsView 迁到 Open Data Portal，
   search / API / 可视化全部"暂时暂停"，官方没给恢复时间表。那份 22 行全空的 CSV 不是你的操作问题，
   是接口本身没了。替代方案邱正阳定了口径后另行安排。

## 二、环境准备

```
pip install requests pyyaml
```

Python 3.8+ 即可。需要能访问 `api.openalex.org`——浏览器打开
<https://api.openalex.org/works?per_page=1> 能出 JSON 就行。
打不开的话跑 `python scripts/net_diag.py`，它会告诉你是 DNS、TCP 还是 TLS 哪一层断的。

## 三、填密钥

把 `.keys.env.example` 复制成 `.keys.env`，填入你自己的值：

```
OPENALEX_KEY=          你的 OpenAlex key
OPENALEX_MAILTO=       你的学号邮箱
COLLECTOR_NAME=        填你自己的名字（会写进每个 manifest 的 collected_by，R2 溯源要求）
```

这三个模块只需要这三项，其它行留空即可。`.keys.env` 已被 `.gitignore` 排除，不会进 git。

## 四、开跑（三个模块，按顺序）

**Windows PowerShell：**
```powershell
cd <解压目录>\data_repo\scripts
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # 只需一次
.\run_phase2.ps1 plan            # 先干跑，不联网，确认无报错
.\run_phase2.ps1 papers
.\run_phase2.ps1 shares
.\run_phase2.ps1 institutions
```

**macOS / Linux / Git Bash：**
```bash
cd <解压目录>/data_repo
set -a; . ./.keys.env; set +a
python3 scripts/collect_all.py plan
python3 scripts/collect_all.py papers
python3 scripts/collect_all.py shares
python3 scripts/collect_all.py institutions
```

调用量：papers 约 400 次、shares 4 次、institutions 11 次。OpenAlex 免费额度 1 万/日，很充裕。
papers 因为逐条 sleep，大概十几分钟，中途别关窗口；另外两个各几十秒。

### 为什么这次要多跑一个 institutions

你上次产出的 `openalex_institutions_counts.csv` 数据本身是**干净可用的**（行数齐、数值有真实波动，
已经跟另一份交叉核对过）。问题是那份没有配套 manifest，R2 要求的源URL / UTC时间戳 / SHA256 全缺，
不补齐就进不了 `clean/`。

与其回头去翻你当时的源URL和时间戳（多半也记不清了），不如直接重跑一遍——
`institutions` 走的是 OpenAlex 实体端点、免 key、只有 11 次调用、几十秒就完，
脚本会**自动生成 manifest**，一步就把溯源缺口补上，比事后手工补可靠得多。

## 五、跑完请核对这几个数（对不上先别发，直接跟我说）

| 文件 | 应有行数 | 算式 | 重点 |
|---|---|---|---|
| `raw/openalex_papers_by_quarter.csv` | 240 | 3产业 × 2城市 × 40季度 | **biomed 那 80 行不能再是 0** |
| `raw/openalex_papers_intl_by_quarter.csv` | 160 | 2产业 × 2城市 × 40季度 | — |
| `raw/openalex_share_denominators_by_year.csv` | **44** | 2产业 × 2口径 × 11年 | 上次只有 2 行 |
| `raw/openalex_institutions_counts.csv` | 11所机构 × 有数据的年份 | — | 主要是为了配套的 manifest |

`plan` 干跑时会打印一行"fintech 无学科ID，分母跳过"——这是**预期行为**不是报错，
fintech 走关键词口径不做份额。

跑完顺手自查一下——注意是 **`manifest.py verify`**，不是 `qa_check.py`：

```
python scripts/manifest.py verify
```

它扫 `raw/` 下每个文件，检查①有没有配套 manifest ②manifest 里的 SHA256 跟文件当前内容对不对得上
③源URL/查询/时间戳/执行人四个字段有没有缺。全绿就说明这批数据的溯源链是完整的，可以发回来了。

`qa_check.py` **这个阶段用不上**——它只扫 `clean/`，而 `clean/` 是入库流程第 3–4 步的产物
（见 `docs/入库流程.md`：采集 → 登记 → 清洗 → 溯源 → 校验 → 复核）。你现在做完的是第 1 步，
第 2 步由脚本自动完成。**千万别把 `raw/` 里的 CSV 直接拷进 `clean/`**，那样只会跑出一堆假报错。

## 六、发回来什么

把整个 `raw/` 和 `manifests/` 两个文件夹一起打包发回。

**`manifests/` 千万别漏**——上次那版没带，R2 要求的源URL/时间戳/SHA256 全缺，没法验证溯源。
脚本会自动写，你不用手动做，只要打包时别落下这个文件夹就行。

如果中途报错，把**完整的报错输出**整段发回来（别只发最后一行）。修复版脚本在数据异常时会主动抛错、
带上原始响应内容，就是为了让错误看得见——看到报错反而是好事，比默默写出一份坏 CSV 强。

---

# 七、这一轮只有一件事：临床试验改季度重采

## 先说为什么改

我们回头把已入库的数据对照 proposal 附录 A 的指标表核了一遍，发现一个问题：

附录 A 指标 9（IDI·创新维）要求的是**季度**频率，而 4.5 步骤③ 写死了
「季度先行检验只使用原生季度指标，年度指标绝不内插为季度」。
你上次跑出来的 `clinicaltrials_by_year.csv` 是年度的——数据本身没问题，
但它进不了 RQ2 的先行检验。

好消息是 ClinicalTrials.gov 的 `StudyFirstPostDate` 支持任意日期区间，
按季度直接拉就行，不需要任何插值。所以只是重采一遍，不是返工。

**年度那份不用删**，继续留着供年度剖面用；季度是新增的一份。

## 跑这一条

```powershell
cd C:\FYP\data_repo\scripts
.\run_phase2.ps1 clinicaltrials_q
```

2 城市 × 40 季度（2015Q1–2024Q4）= **80 次调用**，免 key，大概一两分钟。
季度区间跟 papers 模块用的是同一组常量，两条序列严格对齐——这是做交叉相关的前提。

## 上一版为什么会报错（v5.8/v5.9 的那个）

你跑 v5.8 和 v5.9 都撞上这个：

```
RuntimeError: 季度数据与年度数据对不上，拒绝写盘：
  hk/2024: 四季度合计 434 ≠ 年度 433（差 +1）
  sg/2018: 四季度合计 243 ≠ 年度 242（差 +1）
```

**你没做错，数据也没问题，是我那道检查写得太死了。**

我原来要求「四季度合计必须严格等于年度值」。这个假设在两份数据是同一时刻的快照时才成立，
但年度那份是你上午 09:51 采的，季度这份是之后才跑的，中间隔了几个小时——
而 ClinicalTrials.gov 是活库：`query.locn` 匹配的是研究的**地点列表**，
申办方可以在登记之后追加地点。一项 2018 年首次登记、最近才加上新加坡站点的研究，
会在保持 2018 年 StudyFirstPostDate 的同时，新近开始匹配 `query.locn=Singapore`。
所以历史年份的计数本来就会随时间缓慢上涨。

佐证也很清楚：季度区间是严格划分的（首尾相接、无重叠无缺口，我复查过），
真有结构性错误的话 20 个「城市×年」会一起错，不会只错 2 个、还都恰好差 1、还都是季度那边偏高。

v5.10 把判定改成了：**小幅漂移放行但如实记入 manifest，结构性错误照旧拦截**。

## 脚本会自己查一道

跑完写盘之前，脚本仍会拿季度数据跟年度文件对一遍，但判定标准放宽了：

- 单格差值 ≤ max(3, 年度值的 1%) → **算快照漂移，放行**，并把差了哪几格写进 manifest
- 超过这个幅度 → 报错拒绝写盘
- 或者超过半数格子都有差异（哪怕每格都很小）→ 也报错，因为漂移应该是零星的，普遍性差异更像查询口径出了问题

所以这次你大概率会看到这样的输出，**这是正常通过**：

```
⚠ 交叉核对：20 格中 2 格存在小幅漂移（已记入 manifest）
    hk/2024: 季度合计 434 vs 年度 433（+1）
    sg/2018: 季度合计 243 vs 年度 242（+1）
[..] raw/clinicaltrials_by_quarter.csv 写入 80 行
```

看到「写入 80 行」就是成功了，把 `raw/` 和 `manifests/` 打包发回来即可。
漂移的格子会如实记在 manifest 的 notes 里，将来复核时看得到，不会被藏起来。

要是真报错了，把完整报错发回来，别自己改脚本。

## 记得填 COLLECTOR_NAME

前两轮七份 manifest 的执行人都是占位符，我这边替你改成了「賈贇」并在 notes 里注明是事后更正。
脚本现在加了守卫，没设名字会在开跑前直接拒绝：

```powershell
notepad ..\.keys.env      # 最后一行 COLLECTOR_NAME=賈贇
```

## 另外：ODP 那条线先停

你注册的那把 ODP key 先留着别浪费，但这一轮不用跑了。
我们核对指标表时发现，之前在追的那个专利口径（按申请人国别数专利数量）
对不上附录 A 里的任何一个指标——真正要的是 BigQuery 那条线，跟 PatentsView 不是一回事。
是我这边判断失误让你多跑了几轮，抱歉。等指标 6（人才流动）正式排期时再回来找你。
