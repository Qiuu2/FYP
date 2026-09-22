# Commit and push the current working-tree changes.
# Idempotent. ASCII only. Handles CJK filenames.
# NOTE: ErrorActionPreference is Continue on purpose - git writes normal
# informational output to stderr, which Stop would treat as fatal.

$ErrorActionPreference = "Continue"
Set-Location "C:\FYP\data_repo"

git config core.quotepath false
$prevEnc = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "[1/4] Changes to commit:" -ForegroundColor Cyan
git add -A
$staged = @(git diff --cached --name-only)
if ($staged.Count -eq 0) {
    Write-Host "  nothing to commit - working tree clean"
    [Console]::OutputEncoding = $prevEnc
    exit 0
}
$staged | ForEach-Object { Write-Host "    $_" }

Write-Host ""
Write-Host "[2/4] SAFETY CHECK..." -ForegroundColor Cyan
$danger = $staged | Where-Object {
    $_ -match "(^|/)\.keys\.env$"               -or
    $_ -match "^raw/openalex_author_inst_years" -or
    $_ -match "^raw/openalex_author_quarters"   -or
    $_ -match "^raw/openalex_works_master"      -or
    $_ -match "^raw/_ckpt_"                     -or
    $_ -match "^raw/_archive/"                  -or
    $_ -match "(^|/)__pycache__/"
}
if ($danger) {
    Write-Host "  STOP: these must not be committed:" -ForegroundColor Red
    $danger | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    git reset | Out-Null
    [Console]::OutputEncoding = $prevEnc
    exit 1
}
$big = @()
foreach ($f in $staged) {
    $item = Get-Item -LiteralPath $f -ErrorAction SilentlyContinue
    if ($item -and $item.Length -gt 5MB) {
        $big += ("{0}  ({1} MB)" -f $f, [math]::Round($item.Length/1MB,1))
    }
}
if ($big.Count -gt 0) {
    Write-Host "  STOP: file(s) over 5 MB:" -ForegroundColor Red
    $big | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    git reset | Out-Null
    [Console]::OutputEncoding = $prevEnc
    exit 1
}
Write-Host "  OK"

Write-Host ""
Write-Host "[3/4] Commit..." -ForegroundColor Cyan
$msg = "W3: log Jia's J1 return, add W3 task sheet, retire J6" + [char]10 + [char]10 +
       "- raw/forward_panel/jobs_snapshot_2026-09-22.csv + manifest" + [char]10 +
       "- tasks/: W3 task sheet, updated ledger, return-of-work archive" + [char]10 +
       "- J6 retired: Google Patents shows inventor names only, no addresses;" + [char]10 +
       "  source data has family_id but no publication numbers" + [char]10 +
       "- Open question: 09-22 snapshot SHA-256 identical to 09-15"
git -c user.name="TaricQiu" -c user.email="taricqiu@gmail.com" commit -m $msg

Write-Host ""
Write-Host "[4/4] Push..." -ForegroundColor Cyan
git push

[Console]::OutputEncoding = $prevEnc

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "DONE: https://github.com/Qiuu2/FYP" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Push failed. If remote is ahead:" -ForegroundColor Yellow
    Write-Host "  git pull --rebase origin main" -ForegroundColor White
    Write-Host "  git push" -ForegroundColor White
}
