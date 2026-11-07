[CmdletBinding()]
param(
    [string]$ProjectId = "",
    [double]$MaxGb = 50,
    [switch]$ExecutePatents,
    [switch]$SkipPapers,
    [switch]$SkipPatents
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Failures = [System.Collections.Generic.List[string]]::new()

if ($SkipPapers -and $SkipPatents) {
    throw 'Nothing to run: both -SkipPapers and -SkipPatents were selected.'
}
if ($ExecutePatents -and $SkipPatents) {
    throw 'Remove -SkipPatents when using -ExecutePatents.'
}
if ($MaxGb -le 0) { throw '-MaxGb must be positive.' }

$SystemPython = Get-Command python -ErrorAction SilentlyContinue
$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue

$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    $VenvPath = Join-Path $Root '.venv'
    $CreatedVenv = $false
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        if ($SystemPython) {
            & $SystemPython.Source -m venv $VenvPath 2>&1 |
                Tee-Object -FilePath (Join-Path $LogDir "${Stamp}_venv.log")
            $CreatedVenv = Test-Path $VenvPython
        }
        if (-not $CreatedVenv -and $PythonLauncher) {
            & $PythonLauncher.Source -3 -m venv $VenvPath 2>&1 |
                Tee-Object -FilePath (Join-Path $LogDir "${Stamp}_venv.log")
            $CreatedVenv = Test-Path $VenvPython
        }
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if (-not $CreatedVenv) {
        throw 'Python 3.10 or newer is required. Install Python, or ensure the py launcher is available, then reopen PowerShell.'
    }
}
if (-not (Test-Path $VenvPython)) { throw 'The local Python environment was not created.' }

$env:PYTHONUTF8 = '1'
$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $VenvPython -m pip install -r (Join-Path $Root 'requirements.txt') 2>&1 |
        Tee-Object -FilePath (Join-Path $LogDir "${Stamp}_install.log")
    $InstallExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($InstallExitCode -ne 0) { throw 'Dependency installation failed; see logs.' }

function Invoke-LoggedPython {
    param(
        [Parameter(Mandatory=$true)][string]$Label,
        [Parameter(Mandatory=$true)][string[]]$Arguments
    )
    $LogPath = Join-Path $LogDir ("${Stamp}_" + $Label + '.log')
    Write-Host "`n--- $Label ---"
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $VenvPython @Arguments 2>&1 | Tee-Object -FilePath $LogPath
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0) {
        $Failures.Add("$Label (exit $ExitCode)")
        Write-Warning "$Label stopped with exit code $ExitCode. Its cache is retained for retry."
    }
}

if (-not $SkipPapers) {
    $PreviousOpenAlexKey = $env:OPENALEX_API_KEY
    if (-not $env:OPENALEX_API_KEY) {
        $SecureKey = Read-Host 'OpenAlex API key (hidden; not saved in the package)' -AsSecureString
        $KeyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
        try {
            $env:OPENALEX_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyPtr)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyPtr)
        }
    }
    if (-not $env:OPENALEX_API_KEY) {
        $Failures.Add('Paper collection skipped: no OpenAlex API key')
    }
    else {
        Invoke-LoggedPython -Label 'papers' -Arguments @(
            (Join-Path $Root 'papers.py'), 'all', '--all-catalogs', '--max-requests', '10000'
        )
    }
    if ($PreviousOpenAlexKey) { $env:OPENALEX_API_KEY = $PreviousOpenAlexKey }
    else { Remove-Item Env:OPENALEX_API_KEY -ErrorAction SilentlyContinue }
}

if (-not $SkipPatents) {
    if (-not $ProjectId) { $ProjectId = Read-Host 'Google Cloud project ID' }
    if (-not $ProjectId) {
        $Failures.Add('Patent query skipped: no Google Cloud project ID')
    }
    else {
        $PatentArgs = @((Join-Path $Root 'patents.py'), '--project', $ProjectId, '--max-gb', "$MaxGb")
        if ($ExecutePatents) { $PatentArgs += '--execute' }
        Invoke-LoggedPython -Label 'patents' -Arguments $PatentArgs
    }
}

Invoke-LoggedPython -Label 'summary' -Arguments @((Join-Path $Root 'collection_summary.py'))

Write-Host "`nLogs: $LogDir"
Write-Host 'Paper result folder: results\papers'
Write-Host 'Patent result folder: results\patents'
if ($Failures.Count -gt 0) {
    Write-Warning ('Some tasks need retry: ' + ($Failures -join '; '))
    exit 1
}
Write-Host 'Commands finished. Check catalog_status.csv, conference_coverage.csv, review_queue.csv, and new_assignees_to_classify.csv before treating the data as complete.'
exit 0
