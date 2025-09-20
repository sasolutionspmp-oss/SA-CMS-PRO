[CmdletBinding()]
param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [int]$ApiPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-PythonPath {
    param([string]$Root)
    $windowsPath = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path $windowsPath) {
        return $windowsPath
    }
    $unixPath = Join-Path $Root '.venv/bin/python'
    if (Test-Path $unixPath) {
        return $unixPath
    }
    throw "Python interpreter not found in .venv. Run install/bootstrap.ps1 first."
}

function Start-DevJob {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string[]]$Command,
        [string]$LogPath
    )

    if ($DryRun) {
        Write-Host "[DRY-RUN] $Name :: $($Command -join ' ')" -ForegroundColor Yellow
        return $null
    }

    $scriptBlock = {
        param($wd, $cmd, $log)
        Set-Location $wd
        $logDir = Split-Path -Parent $log
        if ($logDir) {
            New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        }
        try {
            & $cmd[0] @($cmd[1..($cmd.Length - 1)]) 2>&1 | Tee-Object -FilePath $log -Append
        }
        catch {
            Write-Error $_
            throw
        }
    }

    Start-Job -Name $Name -ScriptBlock $scriptBlock -ArgumentList $WorkingDirectory, $Command, $LogPath
}

$repoRoot = (Resolve-Path $Repo).ProviderPath
$logRoot = Join-Path $repoRoot 'output/logs/dev'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$python = Get-PythonPath -Root $repoRoot
$backendCmd = @($python, '-m', 'uvicorn', 'apps.api.main:app', '--reload', '--host', '127.0.0.1', '--port', $ApiPort.ToString())
$workerCmd = @($python, '-m', 'apps.workers.worker')
$frontendCmd = @('pnpm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', $FrontendPort.ToString())

$jobs = @()
$jobs += Start-DevJob -Name 'api' -WorkingDirectory $repoRoot -Command $backendCmd -LogPath (Join-Path $logRoot 'api.log')
$jobs += Start-DevJob -Name 'worker' -WorkingDirectory $repoRoot -Command $workerCmd -LogPath (Join-Path $logRoot 'worker.log')
$jobs += Start-DevJob -Name 'frontend' -WorkingDirectory (Join-Path $repoRoot 'frontend') -Command $frontendCmd -LogPath (Join-Path $logRoot 'frontend.log')

if ($DryRun) {
    Write-Host 'Dry run complete. Commands listed above.' -ForegroundColor Green
    return
}

Write-Host "Dev stack starting..." -ForegroundColor Cyan
Write-Host "Logs: $logRoot" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop all processes." -ForegroundColor Yellow

try {
    while ($true) {
        $finished = Wait-Job -Job ($jobs | Where-Object { $_ -ne $null }) -Any
        if ($finished) {
            Write-Warning "Job '$($finished.Name)' exited with state $($finished.State)."
            break
        }
    }
}
finally {
    foreach ($job in $jobs) {
        if ($null -eq $job) { continue }
        if ($job.State -eq 'Running') {
            Stop-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
        Receive-Job -Job $job -Keep -ErrorAction SilentlyContinue | Out-Null
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    Write-Host 'Dev stack stopped.' -ForegroundColor Cyan
}
