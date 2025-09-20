[CmdletBinding()]
param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [int]$ApiPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$DryRun,
    [switch]$SkipApi,
    [switch]$SkipWorker,
    [switch]$SkipFrontend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Ensure-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$InstallHint = ''
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        $message = "Required command '$Name' was not found on PATH."
        if ($InstallHint) {
            $message += " $InstallHint"
        }
        throw $message
    }
}

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

    $display = $Command -join ' '
    Write-Host "Starting $Name :: $display" -ForegroundColor Cyan

    if ($DryRun) {
        Write-Host "[DRY-RUN] $Name command only" -ForegroundColor Yellow
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

    return Start-Job -Name $Name -ScriptBlock $scriptBlock -ArgumentList $WorkingDirectory, $Command, $LogPath
}

$repoRoot = (Resolve-Path $Repo).ProviderPath
$frontendRoot = Join-Path $repoRoot 'frontend'
$logRoot = Join-Path $repoRoot 'output/logs/dev'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$python = Get-PythonPath -Root $repoRoot
if (-not $SkipFrontend) {
    Ensure-Command -Name 'pnpm' -InstallHint 'Install Node.js and pnpm (see README.md).'    
    if (-not (Test-Path (Join-Path $frontendRoot 'node_modules'))) {
        Write-Warning 'frontend/node_modules not found. Run "pnpm install" inside the frontend directory before starting the dev stack.'
    }
}

$jobs = @()

if ($SkipApi) {
    Write-Host 'Skipping API startup.' -ForegroundColor Yellow
} else {
    $backendCmd = @($python, '-m', 'uvicorn', 'apps.api.main:app', '--reload', '--host', '127.0.0.1', '--port', $ApiPort.ToString())
    $jobs += Start-DevJob -Name 'api' -WorkingDirectory $repoRoot -Command $backendCmd -LogPath (Join-Path $logRoot 'api.log')
}

if ($SkipWorker) {
    Write-Host 'Skipping worker startup.' -ForegroundColor Yellow
} else {
    $workerCmd = @($python, '-m', 'apps.workers.worker')
    $jobs += Start-DevJob -Name 'worker' -WorkingDirectory $repoRoot -Command $workerCmd -LogPath (Join-Path $logRoot 'worker.log')
}

if ($SkipFrontend) {
    Write-Host 'Skipping frontend startup.' -ForegroundColor Yellow
} else {
    $frontendCmd = @('pnpm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', $FrontendPort.ToString())
    $jobs += Start-DevJob -Name 'frontend' -WorkingDirectory $frontendRoot -Command $frontendCmd -LogPath (Join-Path $logRoot 'frontend.log')
}

if ($DryRun) {
    Write-Host 'Dry run complete. Commands listed above.' -ForegroundColor Green
    return
}

$activeJobs = $jobs | Where-Object { $_ -ne $null }
if (-not $activeJobs) {
    Write-Warning 'No processes were started. Use -Skip* flags to control components.'
    return
}

Write-Host "Dev stack starting..." -ForegroundColor Cyan
Write-Host "Logs: $logRoot" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop all processes." -ForegroundColor Yellow

try {
    while ($true) {
        $finished = Wait-Job -Job $activeJobs -Any -Timeout 2
        if ($finished) {
            Write-Warning "Job '$($finished.Name)' exited with state $($finished.State)."
            break
        }
    }
}
finally {
    foreach ($job in $activeJobs) {
        if ($job.State -eq 'Running') {
            Stop-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
        Receive-Job -Job $job -Keep -ErrorAction SilentlyContinue | Out-Null
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    Write-Host 'Dev stack stopped.' -ForegroundColor Cyan
}
