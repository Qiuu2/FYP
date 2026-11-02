-- GoogleSQL. HK/SG assignee countries, same CPC scope as the historical project.
-- Full 2015--2025 window BEFORE family-year assignment; no financial patents.
-- The final sentinel and repeated row count detect partial web CSV exports.
WITH hits AS (
 SELECT CAST(p.family_id AS STRING) AS family_id,p.filing_date,p.publication_date,
        a.country_code AS cc,a.name AS assignee,c.code AS cpc
 FROM `patents-public-data.patents.publications` p,
      UNNEST(p.assignee_harmonized) a,UNNEST(p.cpc) c
 WHERE a.country_code IN ('HK','SG') AND p.filing_date BETWEEN 20150101 AND 20251231
), tagged AS (
 SELECT *, CASE
   WHEN cpc LIKE 'G06N%' OR cpc LIKE 'G06V%' OR cpc LIKE 'G10L%'
     OR cpc LIKE 'G06F40%' OR cpc LIKE 'B25J%' THEN 'ai'
   WHEN cpc LIKE 'A61%' OR cpc LIKE 'C12%' OR cpc LIKE 'C07K%'
     OR cpc LIKE 'C07D%' OR cpc LIKE 'G16H%' THEN 'biomed'
   ELSE NULL END AS industry
 FROM hits
), families AS (
 SELECT industry,LOWER(cc) AS city,family_id,
   MIN(filing_date) AS first_filing_in_window,
   MIN(NULLIF(publication_date,0)) AS first_pub_in_window,
   STRING_AGG(DISTINCT assignee,' | ' ORDER BY assignee) AS assignees
 FROM tagged WHERE industry IS NOT NULL
 GROUP BY industry,city,family_id
), totals AS (
 SELECT COUNT(*) AS export_total_rows FROM families
), snapshot AS (
 SELECT MAX(NULLIF(publication_date,0)) AS max_pub_in_query FROM tagged WHERE industry IS NOT NULL
)
SELECT 'data' AS row_type, f.industry,f.city,
 FORMAT('%dQ%d',DIV(first_filing_in_window,10000),DIV(MOD(DIV(first_filing_in_window,100),100)-1,3)+1) AS quarter,
 f.family_id,f.first_filing_in_window,f.first_pub_in_window,s.max_pub_in_query,f.assignees,t.export_total_rows
FROM families f CROSS JOIN totals t CROSS JOIN snapshot s
UNION ALL
SELECT 'manifest',NULL,NULL,NULL,NULL,NULL,NULL,s.max_pub_in_query,NULL,t.export_total_rows
FROM totals t CROSS JOIN snapshot s;
