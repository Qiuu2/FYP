# ═══════════════════════════════════════════════════════════════
# FYP data_repo 建仓 + 推送 GitHub（一次性执行）
# 生成：2026-09-22
#
# 执行前提：
#   1. 已安装 git（git --version 能跑）
#   2. 已安装 GitHub CLI（gh --version）并登录过（gh auth login）
#      —— 若没装 gh，见文末「不用 gh 的做法」
#
# 用法：在 PowerShell 里
#   cd C:\FYP\data_repo
#   .\建仓脚本_一次性.ps1
# ═══════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
Set-Location "C:\FYP\data_repo"

Write-Host "`n[1/7] 确认位置正确..." -ForegroundColor Cyan
if (-not (Test-Path "scripts\index_build.py")) {
    Write-Host "⛔ 当前目录不对，没找到 scripts\index_build.py" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ C:\FYP\data_repo"

# ── 2. 安全闸门：确认 .gitignore 已更新 ────────────────────
Write-Host "`n[2/7] 检查 .gitignore..." -ForegroundColor Cyan
$gi = Get-Content .gitignore -Raw -ErrorAction SilentlyContinue
if ($gi -notmatch "openalex_author_inst_years") {
    Write-Host "⛔ .gitignore 还是旧版（没排除大文件）。" -ForegroundColor Red
    Write-Host "   请先把我发的新 .gitignore 覆盖进 C:\FYP\data_repo\.gitignore" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ .gitignore 已是新版"

# ── 3. 初始化 ──────────────────────────────────────────────
Write-Host "`n[3/7] git init..." -ForegroundColor Cyan
if (Test-Path ".git") {
    Write-Host "  ! 已经是 git 仓库，跳过 init"
} else {
    git init
    git branch -M main
}

# ── 4. 安全闸门：确认密钥不在待提交列表里 ──────────────────
Write-Host "`n[4/7] 安全检查：确认密钥不会被提交..." -ForegroundColor Cyan
git add -A
$staged = git diff --cached --name-only

$danger = $staged | Where-Object {
    $_ -match "\.keys\.env$" -or
    $_ -match "openalex_author_inst_years" -or
    $_ -match "openalex_author_quarters" -or
    $_ -match "openalex_works_master" -or
    $_ -match "__pycache__"
}

if ($danger) {
    Write-Host "⛔ 以下文件不该被提交，但出现在暂存区：" -ForegroundColor Red
    $danger | ForEach-Object { Write-Host "     $_" -ForegroundColor Red }
    Write-Host "`n   已回滚暂存区。请检查 .gitignore 后重跑。" -ForegroundColor Red
    git reset
    exit 1
}
Write-Host "  ✓ 无密钥、无大文件、无缓存"

# ── 5. 列出将要提交的内容 ──────────────────────────────────
Write-Host "`n[5/7] 将要提交 $($staged.Count) 个文件：" -ForegroundColor Cyan
$staged | Group-Object { ($_ -split "/")[0] } | Sort-Object Name | ForEach-Object {
    Write-Host ("     {0,-16} {1,4} 个" -f $_.Name, $_.Count)
}

$totalMB = [math]::Round(((git diff --cached --name-only | ForEach-Object {
    if (Test-Path $_) { (Get-Item $_).Length } else { 0 }
} | Measure-Object -Sum).Sum / 1MB), 2)
Write-Host "`n     合计约 $totalMB MB"

Write-Host "`n  按 Enter 继续提交，Ctrl+C 取消" -ForegroundColor Yellow
Read-Host

# ── 6. 首次提交 ────────────────────────────────────────────
Write-Host "`n[6/7] 提交..." -ForegroundColor Cyan
git -c user.name="TaricQiu" -c user.email="taricqiu@gmail.com" commit -m @"
初始提交：TAI/IDI 数据仓库

GECC4130 FYP「香港新兴产业人才基础画像：TAI/IDI 双指数诊断与新加坡对比（2015-2024）」

包含：
- scripts/  采集、清洗、指数构建、质检脚本
- clean/    季度指标库（含 .prov.json 溯源）
- config/   边界规则、申请人归类、geo 判定表
- docs/     口径决定、效度检验、方法章改稿
- manifests/ 包裹清单（来源 URL + 抓取时间 + SHA-256）
- tasks/    任务派发与回传留档

已排除：API 密钥、研究者个人层面底稿（见 .gitignore）
"@

# ── 7. 建远端并推送 ────────────────────────────────────────
Write-Host "`n[7/7] 创建 GitHub 仓库并推送..." -ForegroundColor Cyan
Write-Host "  仓库将建为 PUBLIC（按组长决定）" -ForegroundColor Yellow

gh repo create FYP-TAI-IDI --public --source=. --remote=origin --push `
   --description "GECC4130 FYP: Talent Base Index (TAI) / Industry Development Index (IDI) for Hong Kong's strategic industries, benchmarked against Singapore (2015-2024)"

Write-Host "`n✅ 完成。仓库地址：" -ForegroundColor Green
gh repo view --json url -q .url

# ═══════════════════════════════════════════════════════════════
# 不用 gh 的做法：
#   1. 去 github.com 手动 New repository，名字 FYP-TAI-IDI，选 Public，
#      不要勾 "Add a README"（我们已经有了）
#   2. 然后跑：
#      git remote add origin https://github.com/<你的用户名>/FYP-TAI-IDI.git
#      git push -u origin main
# ═══════════════════════════════════════════════════════════════
