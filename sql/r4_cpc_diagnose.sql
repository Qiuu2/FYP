-- ============================================================================
-- CPC 标签诊断 —— 查清 R4 复核发现的「白名单码对不上」到底怎么回事
--
-- 背景：陈于嘉 2026-09-02 复核 30 族抽样，发现 3 族的 CPC 与我们的产业标签对不上
--   family 65233627  ZYETRIC      他在 GP 看到 G06T & G06K  → 我们标 ai
--   family 83459986  AI PALETTE   他在 GP 看到 G06Q         → 我们标 ai
--   family 89029809  UNIV NANYANG 他在 GP 看到 B60W40       → 我们标 fintech
--   （另一族 91081046 他看到 G16H，在 biomed 白名单里，那族对得上，不是问题）
--
-- 两个待验证的假设（本查询同时检验）：
--
--   H1「家族级聚合」：主查询 GROUP BY family_id，一个家族含多国多件专利，
--      只要【任一件】带白名单码，整族就被打上标签。Google Patents 只显示
--      其中一件代表专利——他看到的那件可能不是触发标签的那件。
--      → 若成立：不是 bug，是没写明的口径；但 CPC 复核会持续误报
--
--   H2「非发明性分类」：BigQuery 的 cpc 字段带 inventive / first 两个标志位，
--      主查询【完全没用】——把「附加分类」（inventive=false，专利局为检索
--      方便加的旁支分类）也当成了产业依据。
--      → 若成立：这是真 bug，三个产业的家族数都要重算
--
-- 输出每一件专利的每一个 CPC 码，带 inventive/first 标志与是否命中白名单。
-- 看两件事：
--   (a) 触发标签的码，是不是在他看到的那件专利上？→ 判 H1
--   (b) 触发标签的码，inventive 是 true 还是 false？→ 判 H2
--
-- 另存为 raw/r4_cpc_diagnose.csv（不要覆盖任何现有文件）
-- 预估扫描量：与主查询同量级，免费额度内
-- ============================================================================
SELECT
  p.family_id,
  p.publication_number,
  p.country_code                         AS pub_country,   -- 公开国别（TW/CN/US…）
  p.filing_date,
  c.code                                 AS cpc_code,
  c.inventive                            AS cpc_inventive, -- ← 判 H2 看这列
  c.first                                AS cpc_first,
  CASE
    WHEN c.code LIKE 'G06N%'   OR c.code LIKE 'G06V%' OR c.code LIKE 'G10L%'
      OR c.code LIKE 'G06F40%' OR c.code LIKE 'B25J%'   THEN 'ai'
    WHEN c.code LIKE 'A61%'  OR c.code LIKE 'C12%'  OR c.code LIKE 'C07K%'
      OR c.code LIKE 'C07D%' OR c.code LIKE 'G16H%'     THEN 'biomed'
    WHEN c.code LIKE 'G06Q20%' OR c.code LIKE 'G06Q40%' THEN 'fintech'
    ELSE NULL
  END                                    AS whitelist_hit, -- 非空＝这个码触发了标签
  (SELECT STRING_AGG(DISTINCT a.name, ' | ' ORDER BY a.name)
     FROM UNNEST(p.assignee_harmonized) AS a)          AS assignees,
  (SELECT STRING_AGG(DISTINCT a.country_code, ',' ORDER BY a.country_code)
     FROM UNNEST(p.assignee_harmonized) AS a)          AS assignee_countries
FROM `patents-public-data.patents.publications` AS p,
  UNNEST(p.cpc) AS c
WHERE p.family_id IN (
  -- 3 个对不上的（重点看这三个）
  '65233627', '83459986', '89029809',
  -- 其余 27 个抽样族，作对照组
  '54767245', '58239605', '59439902', '59850239', '59887351', '60186027',
  '60266184', '60483772', '60551970', '61108393', '62488197', '63709484',
  '63778258', '64837163', '65296601', '66734787', '74229126', '74682582',
  '78106540', '78745733', '81448966', '81535398', '82668520', '85719325',
  '89169119', '91081046', '91897360'
)
ORDER BY family_id, publication_number, cpc_code;
-- 表头：family_id,publication_number,pub_country,filing_date,cpc_code,
--       cpc_inventive,cpc_first,whitelist_hit,assignees,assignee_countries
--
-- 注意：family_id 在 BigQuery 里是 STRING，所以上面用引号。
