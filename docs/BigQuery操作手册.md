# BigQuery 操作手册（给賈贇）

目标：拿到附录 A **指标 8「企业专利族数」**（IDI·创新维，季度）。
这是 IDI 侧的**第二条季度序列**——有了它，RQ2 的先行检验才真正跑得起来。

预计耗时：注册 10 分钟 ＋ 跑查询 20 分钟 ＋ 入库 10 分钟。

---

## 一、开账户：不用信用卡

用 **BigQuery 沙盒（Sandbox）**，Google 官方明确说**不需要信用卡、不需要账单账户**。

1. 用你的 Google 账号打开 <https://console.cloud.google.com/bigquery>
2. 接受服务条款
3. 点「Create project」，项目名随便起（比如 `fyp-gecc4130`）
4. 组织选「No organization」
5. 建完就能用了

**沙盒的限制**（官方文档）：
- 每月 **1 TiB** 查询处理量、**10 GB** 存储
- 数据集和表 **60 天后自动过期**（我们只是查公共数据集再导出 CSV，不受影响）
- 不支持 DML（INSERT/UPDATE/DELETE）——我们也用不上
- **公共数据集默认可查**，`patents-public-data` 就是公共的

因为没绑账单账户，超额的后果是**查询被拒绝**而不是扣钱。不过这一点官方文档没有明写，
所以下面第二节那个习惯还是要养成。

---

## 二、⚠ 最重要的一个习惯：先看预估，再点运行

BigQuery 按**扫描的字节数**计费。把 SQL 粘进编辑器之后，**先别点运行**——
看编辑器右上角那行小字：

> **This query will process 123.45 GB when run.**

- 低于 200 GiB：放心跑
- 200 GiB – 500 GiB：可以跑，但一个月别跑太多次
- **超过 500 GiB：停下来，把这个数字发回群里再说**

`patents-public-data.patents.publications` 是个很大的表。我们的查询只选了
`family_id / filing_date / assignee_harmonized / cpc` 四个字段，
BigQuery 只扫这几列不扫全表，所以应该在可控范围内——**但我没有账号，估不了准数，
所以第一次跑之前那个预估数字麻烦你念给我听。**

另外：**永远不要写 `SELECT *`**。一次就能把一个月的额度烧光。

---

## 三、只跑一条查询

SQL 在 `sql/patents_bigquery.sql`，**整个文件就是一条查询**，全选粘进 BigQuery 编辑器跑。

跑完点结果面板上方的「SAVE RESULTS」→「CSV (local file)」，
存成 **`raw/patents_families_raw.csv`**。

约 1 万行（每个「产业×城市×专利族」一行，带申请人）。

### 为什么这次只有一条

前两版我让你跑四条，其中主查询输出的是聚合值——**没有申请人这一列**。
但指标 8 要的是「**企业**申请人的专利族」，聚合之后就再也过滤不出来了，
等人工把申请人分完「大学/企业/公营」，还得回来第三次跑 BigQuery。

v4 直接输出到"家族"这一级，申请人一起带出来。之后所有事情都在本地做：
三分归类、企业口径、跨产业唯一分配、季度聚合、补零——**想改规则随时改，
不用再动 BigQuery，也不再烧免费额度。**

年度值、季度值、重叠量、申请人清单，全都能从这一份文件本地算出来。

---

## 四、本地加工

```powershell
cd C:\FYP\data_repo
python scripts\patents_build.py
```

它会：

- 自检每个「产业×城市×家族」是否唯一一行、季度是否都在窗口内
- 报出跨产业重叠有多少（骨架 4.3 要定唯一分配规则，先看数字）
- 产出 `raw/patents_assignees.csv`（申请人清单，供人工归类）
- 产出 `raw/patents_families_by_quarter.csv`（**216 行，已自动补零**）
- 核对年度与季度是否自洽（同源数据，必须完全一致）

看到这两行就说明没问题：

```
✅ 季度都在窗口内；每个「产业×城市×家族」唯一一行
年度/季度自洽： ✅ 完全一致
```

⚠ 这一步产出的是**全申请人口径**，还不是指标 8。等人工归类做完，
把 `config/patents_assignee_sector.csv`（两列：`assignee,sector`，
sector 取 `university` / `company` / `public_rd`）放好，再跑一次：

```powershell
python scripts\patents_build.py --sector company
```

这才是指标 8 的正式口径。同一份原始文件，`--sector university` 还能顺手出
TAI 质量维要的大学专利，不用再跑 BigQuery。

---

## 五、入库

```powershell
python scripts\manifest.py add raw\patents_families_raw.csv ^
  --url "https://console.cloud.google.com/bigquery?p=patents-public-data&d=patents&t=publications" ^
  --query "patents-public-data.patents.publications；申请人国别HK/SG × CPC白名单(附录B v1.2) × 申请日2015-01-01..2023-12-31；每个产业×城市×family_id取窗口内最早申请日，输出到家族级并带申请人；SQL见sql/patents_bigquery.sql" ^
  --by "賈贇" ^
  --note "家族级原始件；季度序列由 scripts/patents_build.py 本地聚合产出"

python scripts\manifest.py verify
```

全绿之后把 `raw/` 和 `manifests/` 打包发回。

---

## 五之二、发回来时一并告诉我

1. 查询的**扫描量预估**是多少 GB（v2 那版是 15.37 GB，v4 窗口条件一样，应该差不多）
2. `patents_build.py` 打印的**跨产业重叠**数字
3. 两行自检有没有都是 ✅

---

## 六、GH Archive 那条先别做

`sql/gharchive_bigquery.sql` 是指标 2「活跃开发者数」用的，但它有个**前置条件还没满足**：

那条 SQL 需要先有一张 `cohort_logins` 表，也就是**驻港/驻新 GitHub 账户的 login 名单**。
而我们现在的 `github_new_users_by_year.csv` 只有**逐年的账户数量**，没有具体是哪些账户——
GitHub 模块从来没采过 login。

要凑齐这份名单不是小事：GitHub 搜索接口单次查询最多返回 1000 条，
香港的账户数远超这个量级，得按注册时间切片分批拉，是个独立的任务。

**所以这条先挂起。** 等指标 8 落地、组里也确认了要投入去建这份名单，再动。
