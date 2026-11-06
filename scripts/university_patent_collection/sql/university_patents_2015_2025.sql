-- HK/SG universities + local applicant universe; AI/biomed, historical 2015-2025.
-- Google Patents Public Data; publication-level, full export including manifest.
-- This requires BigQuery access and may incur charges: inspect dry-run cost first.
-- Within-window records only: earliest filing here is NOT global first priority.
WITH candidate AS (
 SELECT DISTINCT CAST(p.family_id AS STRING) AS family_id
 FROM `patents-public-data.patents.publications` p
 WHERE p.filing_date BETWEEN 20150101 AND 20251231
   AND CAST(p.family_id AS STRING) NOT IN ('', '0', '-1')
   AND EXISTS (SELECT 1 FROM UNNEST(p.cpc) c WHERE
      STARTS_WITH(c.code,'G06N') OR STARTS_WITH(c.code,'G06V') OR STARTS_WITH(c.code,'G10L') OR
      STARTS_WITH(c.code,'G06F40') OR STARTS_WITH(c.code,'B25J') OR STARTS_WITH(c.code,'A61') OR
      STARTS_WITH(c.code,'C12') OR STARTS_WITH(c.code,'C07K') OR STARTS_WITH(c.code,'C07D') OR STARTS_WITH(c.code,'G16H'))
   AND EXISTS (SELECT 1 FROM UNNEST(p.assignee_harmonized) a WHERE
      a.country_code IN ('HK','SG') OR
      (REGEXP_CONTAINS(UPPER(COALESCE(a.name,'')),r'HONG.?KONG|HKUST|CUHK|HKBU|LINGNAN|SINGAPORE|NANYANG|\bNUS\b')
       AND REGEXP_CONTAINS(UPPER(COALESCE(a.name,'')),r'UNIV|POLYTECH|HKUST|CUHK|HKBU|LINGNAN|\bNUS\b')))
), pubs AS (
 SELECT DISTINCT p.publication_number, CAST(p.family_id AS STRING) AS family_id,
   p.filing_date, p.publication_date, p.priority_date, p.country_code AS publication_country,
   TO_JSON_STRING(ARRAY(SELECT AS STRUCT a.name, a.country_code FROM UNNEST(p.assignee_harmonized) a)) AS applicants_json,
   TO_JSON_STRING(ARRAY(SELECT c.code FROM UNNEST(p.cpc) c)) AS cpc_json,
   TO_JSON_STRING(ARRAY(SELECT DISTINCT i.country_code FROM UNNEST(p.inventor_harmonized) i WHERE i.country_code IS NOT NULL)) AS inventor_countries_json
 FROM `patents-public-data.patents.publications` p JOIN candidate c ON CAST(p.family_id AS STRING)=c.family_id
 WHERE p.filing_date BETWEEN 20150101 AND 20251231 AND p.publication_number IS NOT NULL
), meta AS (SELECT COUNT(*) AS total_rows, MAX(publication_date) AS max_publication_date FROM pubs)
SELECT 'data' AS row_type,p.publication_number,p.family_id,p.filing_date,p.publication_date,p.priority_date,
 p.publication_country,p.applicants_json,p.cpc_json,p.inventor_countries_json,
 m.total_rows,m.max_publication_date,CAST(CURRENT_TIMESTAMP() AS STRING) AS query_utc
FROM pubs p CROSS JOIN meta m
UNION ALL
SELECT 'manifest',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,total_rows,max_publication_date,CAST(CURRENT_TIMESTAMP() AS STRING)
FROM meta;
