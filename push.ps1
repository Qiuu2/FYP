# FYP data_repo -> github.com/Qiuu2/FYP
# ASCII only. Handles CJK filenames correctly.

$ErrorActionPreference = "Stop"
Set-Location "C:\FYP\data_repo"
$REPO = "https://github.com/Qiuu2/FYP.git"

Write-Host ""
Write-Host "[1/6] Checking location..." -ForegroundColor Cyan
if (-not (Test-Path "scripts\index_build.py")) {
    Write-Host "  STOP: wrong directory." -ForegroundColor Red
    exit 1
}
Write-Host "  OK"

Write-Host ""
Write-Host "[2/6] Checking .gitignore..." -ForegroundColor Cyan
$gi = Get-Content .gitignore -Raw -ErrorAction SilentlyContinue
if ($gi -notmatch "openalex_author_inst_years") {
    Write-Host "  STOP: .gitignore is the old 4-line version." -ForegroundColor Red
    exit 1
}
Write-Host "  OK (new version active)"

Write-Host ""
Write-Host "[3/6] git init..." -ForegroundColor Cyan
if (Test-Path ".git") { Write-Host "  already a repo, skipping" }
else { git init | Out-Null; Write-Host "  OK" }
git branch -M main

# CJK filenames: stop git from octal-escaping and quoting them,
# and read git output as UTF-8.
git config core.quotepath false
$prevEnc = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "[4/6] SAFETY CHECK - staging and scanning..." -ForegroundColor Cyan
git add -A
$staged = @(git diff --cached --name-only)

# Block only ACTUAL data files under raw/. manifests/*.json and *.tsv are
# provenance records (1-2 KB, no researcher data) and MUST be committed.
$danger = $staged | Where-Object {
    $_ -match "(^|/)\.keys.env$"                  -or
    $_ -match "^raw/openalex_author_inst_years"    -or
    $_ -match "^raw/openalex_author_quarters"      -or
    $_ -match "^raw/openalex_works_master"         -or
    $_ -match "^raw/_ckpt_"                        -or
    $_ -match "^raw/_archive/"                     -or
    $_ -match "(^|/)__pycache__/"
}

if ($danger) {
    Write-Host "  STOP: these must not be committed:" -ForegroundColor Red
    $danger | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    git reset | Out-Null
    [Console]::OutputEncoding = $prevEnc
    Write-Host "  Staging area rolled back. Nothing was committed." -ForegroundColor Red
    exit 1
}

# Second gate: refuse any single file over 5 MB, whatever its name.
# -LiteralPath so CJK / bracket chars in filenames are not treated as wildcards.
$big = @()
foreach ($f in $staged) {
    $item = Get-Item -LiteralPath $f -ErrorAction SilentlyContinue
    if ($item -and $item.Length -gt 5MB) {
        $big += ("{0}  ({1} MB)" -f $f, [math]::Round($item.Length/1MB,1))
    }
}
if ($big.Count -gt 0) {
    Write-Host "  STOP: file(s) over 5 MB staged:" -ForegroundColor Red
    $big | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    git reset | Out-Null
    [Console]::OutputEncoding = $prevEnc
    Write-Host "  Staging area rolled back. Nothing was committed." -ForegroundColor Red
    exit 1
}
Write-Host "  OK - no secrets, no large data files, no cache"

Write-Host ""
Write-Host "[5/6] Files to commit: $($staged.Count)" -ForegroundColor Cyan
$staged | Group-Object { ($_ -split "/")[0] } | Sort-Object Name | ForEach-Object {
    Write-Host ("    {0,-18} {1,4}" -f $_.Name, $_.Count)
}
$total = 0
foreach ($f in $staged) {
    $item = Get-Item -LiteralPath $f -ErrorAction SilentlyContinue
    if ($item) { $total += $item.Length }
}
Write-Host ("    TOTAL              {0} MB" -f ([math]::Round($total/1MB,2)))
Write-Host ""
Write-Host "  Target: $REPO  (PUBLIC)" -ForegroundColor Yellow
Write-Host "  Press Enter to commit and push, Ctrl+C to abort" -ForegroundColor Yellow
Read-Host

Write-Host ""
Write-Host "[6/6] Commit and push..." -ForegroundColor Cyan

$msg = "Initial commit: TAI/IDI data repository" + [char]10 + [char]10 +
       "GECC4130 FYP - Talent Base Index / Industry Development Index" + [char]10 +
       "for Hong Kong strategic industries, Singapore benchmark (2015-2024)." + [char]10 + [char]10 +
       "scripts/    collection, cleaning, index build, QA" + [char]10 +
       "clean/      quarterly indicator series (with provenance json)" + [char]10 +
       "config/     boundary rules, assignee classification, geo review" + [char]10 +
       "docs/       scope decisions, validity checks, method chapter draft" + [char]10 +
       "manifests/  packet manifests (source URL + fetch time + SHA-256)" + [char]10 +
       "tasks/      task assignment and return-of-work log" + [char]10 + [char]10 +
       "Excluded: API credentials, researcher-level raw data (see .gitignore)"

git -c user.name="TaricQiu" -c user.email="taricqiu@gmail.com" commit -m $msg

$existing = git remote get-url origin 2>$null
if ($existing) {
    if ($existing -ne $REPO) { git remote set-url origin $REPO }
} else {
    git remote add origin $REPO
}

git push -u origin main

[Console]::OutputEncoding = $prevEnc

Write-Host ""
Write-Host "DONE: https://github.com/Qiuu2/FYP" -ForegroundColor Green
Write-Host ""
Write-Host "If push was rejected (remote already has commits):" -ForegroundColor Yellow
Write-Host "  git pull --rebase origin main" -ForegroundColor Yellow
Write-Host "  git push -u origin main" -ForegroundColor Yellow
