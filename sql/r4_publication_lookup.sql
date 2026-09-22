-- ============================================================================
-- R4 复核用：取 30 个抽样专利族的公开号
--
-- 为什么需要：raw/patents_families_raw.csv 只有 DOCDB family_id，
-- 而 Google Patents 前端【不接受 family_id 搜索】（官方语法里没有这个字段）。
-- 要做族级验证，必须先把 family_id 换成 publication_number，
-- 才能拼出 patents.google.com/patent/<公开号> 这种可点链接。
--
-- 这不是本轮 R4 的必需品——申请人层面的核查已经够抓系统性错误。
-- 想把复核做到族级再跑这条。
--
-- 输出：另存为 raw/r4_publication_lookup.csv（不要覆盖任何现有文件）
-- 预估扫描量：与主查询同量级（十几 GB），免费额度内
-- ============================================================================
SELECT
  p.family_id,
  p.publication_number,
  p.country_code,
  p.filing_date,
  (SELECT STRING_AGG(DISTINCT a.name, ' | ' ORDER BY a.name)
     FROM UNNEST(p.assignee_harmonized) AS a)          AS assignees,
  (SELECT STRING_AGG(DISTINCT c.code, ' ' ORDER BY c.code)
     FROM UNNEST(p.cpc) AS c)                          AS cpc_codes
FROM `patents-public-data.patents.publications` AS p
WHERE p.family_id IN (
  54767245, 58239605, 59439902, 59850239, 59887351, 60186027,
  60266184, 60483772, 60551970, 61108393, 62488197, 63709484,
  63778258, 64837163, 65233627, 65296601, 66734787, 74229126,
  74682582, 78106540, 78745733, 81448966, 81535398, 82668520,
  83459986, 85719325, 89029809, 89169119, 91081046, 91897360
)
ORDER BY family_id, filing_date, publication_number;
-- 表头：family_id,publication_number,country_code,filing_date,assignees,cpc_codes
-- 用法：把 publication_number 拼成 https://patents.google.com/patent/<号>
