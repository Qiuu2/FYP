-- ============================================================================
-- FYP 专利数据 · BigQuery patents-public-data
-- 服务：附录 A 指标 8「企业专利族数」（IDI·创新，季度）
--       ＋ 指标「大学专利」（TAI·质量）——同一份数据按 sector 切两次即可
--
-- v4（2026-08-26）—— **只需要跑这一条查询，一次跑完，以后不用再回 BigQuery**
-- ----------------------------------------------------------------------------
-- v2/v3 的三个问题，v4 一并解决：
--
--  ① v2 按季度和按年各自 COUNT(DISTINCT family_id)，一个家族在同年有多个申请日
--     就被季度重复计数（实测 54 格里 51 格季度和偏高，中位 +3.4%）。
--  ② v3 改成"钉在最早申请日"修好了重复计数，但顺手把"2015 年前首次申请、
--     窗口内有续案"的家族整个剔除了——那是**改口径**不是修 bug。
--     组会已定：**这类家族要算**。
--  ③ v2/v3 的输出都是聚合值，没有申请人维度。而指标 8 要的是**企业**申请人，
--     聚合之后就再也过滤不出来了——等人工归类完还得回 BigQuery 重跑第三次。
--
-- v4 的做法：**输出到"家族"这一级，把申请人一起带出来**。
--   行数约 1 万（hk 3435 + sg 6649 的量级），CSV 完全扛得住。
--   之后所有事情都在本地做：三分归类、企业口径过滤、跨产业唯一分配、
--   季度/年度聚合、补零——想改规则随时改，**不用再动 BigQuery**。
--
-- 计数规则（已用合成数据验证：季度和 == 年度、零重复计数）：
--   每个「产业 × 城市 × 家族」取它**在窗口内最早的申请日**，只落一个季度。
--   窗口 2015-01-01 … 2023-12-31（18 个月公开滞后，proposal 4.2/4.6）。
--   → 序列 2015Q1–2023Q4 共 36 期，比 papers 的 40 期短 4 期，先行检验要对齐。
--
-- 成本：窗口过滤保留在 WHERE 里（跟 v2 一样），v2 实测扫描 15.37 GB。
--   习惯不变：点运行前先看右上角 "This query will process X when run"。
-- ============================================================================

WITH hits AS (
  SELECT
    p.family_id,
    p.filing_date,
    a.country_code AS cc,
    a.name         AS assignee,
    c.code         AS cpc
  FROM `patents-public-data.patents.publications` AS p,
    UNNEST(p.assignee_harmonized) AS a,
    UNNEST(p.cpc)                 AS c
  WHERE a.country_code IN ('HK', 'SG')
    AND p.filing_date BETWEEN 20150101 AND 20231231
),
tagged AS (
  SELECT family_id, filing_date, cc, assignee,
    CASE
      -- 附录 B v1.2 白名单
      WHEN cpc LIKE 'G06N%'   OR cpc LIKE 'G06V%' OR cpc LIKE 'G10L%'
        OR cpc LIKE 'G06F40%' OR cpc LIKE 'B25J%'   THEN 'ai'
      WHEN cpc LIKE 'A61%'  OR cpc LIKE 'C12%'  OR cpc LIKE 'C07K%'
        OR cpc LIKE 'C07D%' OR cpc LIKE 'G16H%'     THEN 'biomed'
      -- H04L9（密码学）附录 B 要求"须与金融语境联用"，属人工判断，不入自动查询
      WHEN cpc LIKE 'G06Q20%' OR cpc LIKE 'G06Q40%' THEN 'fintech'
      ELSE NULL
    END AS industry
  FROM hits
)
SELECT
  industry,
  LOWER(cc) AS city,
  -- 窗口内最早申请日 → 该家族唯一归属的季度
  FORMAT('%dQ%d',
         DIV(MIN(filing_date), 10000),
         DIV(MOD(DIV(MIN(filing_date), 100), 100) - 1, 3) + 1) AS quarter,
  family_id,
  MIN(filing_date) AS first_filing_in_window,
  -- 该家族在本产业本地区的全部申请人，供人工三分归类
  STRING_AGG(DISTINCT assignee, ' | ' ORDER BY assignee) AS assignees
FROM tagged
WHERE industry IS NOT NULL
GROUP BY industry, city, family_id
ORDER BY industry, city, quarter, family_id;

-- 导出 → raw/patents_families_raw.csv
-- 表头：industry,city,quarter,family_id,first_filing_in_window,assignees
--
-- 跑完之后**不用**再跑别的查询：年度值、季度值、重叠量、申请人清单
-- 全都能从这一份文件本地算出来。跑 `python scripts/patents_build.py` 即可。
