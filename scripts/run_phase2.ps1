<#
run_phase2.ps1 —— Windows PowerShell 版采集入口（对应 run_phase2.sh）
用法（在 C:\FYP\data_repo\scripts 目录下）：
    .\run_phase2.ps1 plan
    .\run_phase2.ps1 papers
    .\run_phase2.ps1 shares
    .\run_phase2.ps1 patentsview

密钥从 ..\.keys.env 读取（该文件已被 .gitignore 排除）。
本文件必须以 UTF-8 with BOM 保存，否则中文会乱码且变量名会被吞。
若 PowerShell 拒绝执行脚本，先跑一次：
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>
param([Parameter(Mandatory = $true)][string]$Module)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path (Split-Path -Parent $scriptDir) ".keys.env"

if (-not (Test-Path $envFile)) {
    Write-Host "找不到 $envFile" -ForegroundColor Red
    Write-Host "请先复制 .keys.env.example 为 .keys.env 并填入真值。"
    exit 1
}

$loaded = New-Object System.Collections.ArrayList
foreach ($line in (Get-Content -LiteralPath $envFile -Encoding UTF8)) {
    $t = $line.Trim()
    if ($t -eq "" -or $t.StartsWith("#")) { continue }
    $i = $t.IndexOf("=")
    if ($i -lt 1) { continue }
    $k = $t.Substring(0, $i).Trim()
    $v = $t.Substring($i + 1).Trim().Trim('"').Trim("'")
    if ($v -ne "") {
        Set-Item -Path "env:$k" -Value $v
        [void]$loaded.Add($k)
    }
}
Write-Host ("已载入: " + ($loaded -join ", ")) -ForegroundColor Green

$need = @{
    "papers"      = @("OPENALEX_MAILTO", "COLLECTOR_NAME")
    "shares"      = @("OPENALEX_MAILTO", "COLLECTOR_NAME")
    "patentsview" = @("PATENTSVIEW_KEY", "COLLECTOR_NAME")
    "github"      = @("GITHUB_TOKEN", "COLLECTOR_NAME")
    "clinicaltrials" = @("COLLECTOR_NAME")
    "clinicaltrials_q" = @("COLLECTOR_NAME")
    "institutions"   = @("COLLECTOR_NAME")
}
if ($need.ContainsKey($Module)) {
    $missing = @()
    foreach ($k in $need[$Module]) {
        if (-not [Environment]::GetEnvironmentVariable($k)) { $missing += $k }
    }
    if ($missing.Count -gt 0) {
        Write-Host ("缺少变量: " + ($missing -join ", ") + " -- 模块 " + $Module + " 需要，请填进 .keys.env") -ForegroundColor Red
        exit 1
    }
}

Write-Host ("执行人 COLLECTOR_NAME = " + $env:COLLECTOR_NAME + "  (会写进 manifest 的 collected_by)") -ForegroundColor Yellow

Push-Location $scriptDir
try {
    python collect_all.py $Module
}
finally {
    Pop-Location
}
