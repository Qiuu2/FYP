# Finish: attach remote and push. Idempotent - safe to run repeatedly.
# NOTE: ErrorActionPreference deliberately NOT "Stop": git writes normal
# informational output to stderr, which Stop would treat as fatal.

$ErrorActionPreference = "Continue"
Set-Location "C:\FYP\data_repo"
$REPO = "https://github.com/Qiuu2/FYP.git"

Write-Host ""
Write-Host "[1/4] Verifying commit exists..." -ForegroundColor Cyan
$head = git rev-parse --short HEAD 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  STOP: no commit found. Run push.ps1 first." -ForegroundColor Red
    exit 1
}
Write-Host "  OK - HEAD is $head"

Write-Host ""
Write-Host "[2/4] Checking branch..." -ForegroundColor Cyan
$branch = (git rev-parse --abbrev-ref HEAD 2>&1).Trim()
if ($branch -ne "main") {
    Write-Host "  renaming $branch -> main"
    git branch -M main
} else {
    Write-Host "  OK - already on main"
}

Write-Host ""
Write-Host "[3/4] Attaching remote..." -ForegroundColor Cyan
# 2>&1 plus exit-code check: get-url writes to stderr when origin is absent.
$existing = (git remote get-url origin 2>&1)
if ($LASTEXITCODE -ne 0) {
    git remote add origin $REPO
    Write-Host "  added origin -> $REPO"
} elseif ($existing.Trim() -ne $REPO) {
    git remote set-url origin $REPO
    Write-Host "  updated origin -> $REPO"
} else {
    Write-Host "  OK - origin already correct"
}

Write-Host ""
Write-Host "[4/4] Pushing to GitHub..." -ForegroundColor Cyan
Write-Host "  Target is PUBLIC: $REPO" -ForegroundColor Yellow
git push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "DONE: https://github.com/Qiuu2/FYP" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Push failed. Most likely cause and fix:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  (a) Remote already has commits (you ticked Add a README):" -ForegroundColor Yellow
    Write-Host "      git pull --rebase origin main" -ForegroundColor White
    Write-Host "      git push -u origin main" -ForegroundColor White
    Write-Host ""
    Write-Host "  (b) Authentication: GitHub no longer accepts passwords." -ForegroundColor Yellow
    Write-Host "      Settings > Developer settings > Personal access tokens" -ForegroundColor White
    Write-Host "      > Tokens (classic) > Generate new token, tick repo" -ForegroundColor White
    Write-Host "      Username: Qiuu2   Password: paste the token" -ForegroundColor White
}
