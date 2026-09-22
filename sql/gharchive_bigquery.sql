-- GH Archive（BigQuery 公共数据集 githubarchive）—— TAI 规模/网络维
-- ⚠成本纪律：按月分表查询（githubarchive.month.YYYYMM），选列，绝不 SELECT *；
--   全期扫描前先用单月估算扫描量，控制在每月 1TiB 免费额度内。
-- 口径：当前驻港/驻新账户队列（名单来自 GitHub 模块产出）的历史公共事件。
-- 用法：先在本地把队列账户 login 上传为你项目里的表 `yourproj.fyp.cohort_logins(login STRING, city STRING)`

-- 查询：队列账户逐季度公共事件数（PushEvent 为主的活跃度口径）
SELECT
  c.city,
  FORMAT_DATE('%YQ%Q', DATE(e.created_at)) AS quarter,
  COUNT(*) AS events,
  COUNT(DISTINCT e.actor.login) AS active_users
FROM `githubarchive.month.201501` AS e   -- ←逐月替换/用通配 `githubarchive.month.20*` 前先估算扫描量
JOIN `yourproj.fyp.cohort_logins` c ON e.actor.login = c.login
WHERE e.type IN ('PushEvent','PullRequestEvent','IssuesEvent')
GROUP BY c.city, quarter ORDER BY quarter;
