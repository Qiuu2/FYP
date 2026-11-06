-- BigQuery Standard SQL. 先运行 Dry run 查看数据量/费用，再自行执行。
-- 2015–2025；G06Q40仅代表金融相关的可专利化计算技术，并不覆盖传统金融业全部创新。
-- HK/SG 为申请人地址国别，不是发明人、研发地点或总部的确认。
WITH hits AS (
 SELECT CAST(p.family_id AS STRING) AS family_id, a.country_code AS city,
        a.name AS assignee, c.code AS cpc_code,
        p.filing_date, p.publication_date
 FROM `patents-public-data.patents.publications` AS p,
      UNNEST(p.assignee_harmonized) AS a,
      UNNEST(p.cpc) AS c
 WHERE a.country_code IN ('HK','SG') AND a.name IS NOT NULL
   AND p.family_id IS NOT NULL
   AND p.filing_date BETWEEN 20150101 AND 20251231
   AND STARTS_WITH(c.code, 'G06Q40')
)
SELECT family_id, city,
       MIN(filing_date) AS first_filing_in_window,
       MIN(NULLIF(publication_date, 0)) AS first_publication_in_window,
       STRING_AGG(DISTINCT assignee, ' | ' ORDER BY assignee) AS assignees,
       STRING_AGG(DISTINCT cpc_code, ' | ' ORDER BY cpc_code) AS cpc_codes
FROM hits
GROUP BY family_id, city
ORDER BY city, first_filing_in_window, family_id;
