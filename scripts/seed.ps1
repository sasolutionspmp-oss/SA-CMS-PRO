[CmdletBinding()]
param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [string]$ApiBase = 'http://127.0.0.1:8000',
    [string]$ProjectId = 'SA-001',
    [string]$ZipPath,
    [switch]$SkipIngest,
    [switch]$SkipSeed,
    [switch]$WaitForApi,
    [int]$ApiWaitSeconds = 30,
    [string]$Username = 'demo_owner',
    [string]$Password = 'DemoOwner123$'
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

function Wait-ForApi {
    param(
        [string]$BaseUri,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Method Get -Uri "$BaseUri/health" -TimeoutSec 5 -ErrorAction Stop
            if ($health) {
                Write-Host "API responded with status '$($health.status)'" -ForegroundColor Green
                return $true
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

$repoRoot = (Resolve-Path $Repo).ProviderPath
$zipDefault = Join-Path $repoRoot 'tests/data/sample_project.zip'
if (-not $ZipPath) {
    $ZipPath = $zipDefault
}
$resolvedZip = (Resolve-Path $ZipPath -ErrorAction Stop).ProviderPath
$python = Get-PythonPath -Root $repoRoot

$logRoot = Join-Path $repoRoot 'output/logs/seed'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$seedLog = Join-Path $logRoot 'seed.log'

if (-not $SkipSeed) {
    Write-Host 'Seeding baseline organizations and demo users...' -ForegroundColor Cyan
    & $python '-m' 'apps.api.seed' 2>&1 | Tee-Object -FilePath $seedLog
    if ($LASTEXITCODE -ne 0) {
        throw "apps.api.seed exited with code $LASTEXITCODE. Review $seedLog (consider removing existing SQLite database)."
    }
    Write-Host "Seed complete. Log: $seedLog" -ForegroundColor Green
} else {
    Write-Host 'Skipping seed execution (--SkipSeed specified).' -ForegroundColor Yellow
}

if ($SkipIngest) {
    return
}

if ($WaitForApi) {
    Write-Host "Waiting for API at $ApiBase to become ready..." -ForegroundColor Cyan
    if (-not (Wait-ForApi -BaseUri $ApiBase -TimeoutSeconds $ApiWaitSeconds)) {
        throw "API did not become ready within $ApiWaitSeconds seconds. Start the dev stack (scripts/dev.ps1) or adjust -ApiWaitSeconds."
    }
}

Write-Host "Attempting to launch intake run via $ApiBase" -ForegroundColor Cyan

$loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json -Compress
try {
    $loginResponse = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/auth/login" -Body $loginBody -ContentType 'application/json'
}
catch {
    Write-Warning "Login request failed: $_"
    Write-Warning 'Ensure the API is running (scripts/dev.ps1) before launching ingest.'
    return
}

$token = $loginResponse.access_token
if (-not $token) {
    Write-Warning 'No access token returned from login; aborting ingest launch.'
    return
}

$launchBody = @{ project_id = $ProjectId; zip_path = $resolvedZip } | ConvertTo-Json -Compress
try {
    $launchResponse = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/intake/launch" -Body $launchBody -ContentType 'application/json' -Headers @{ Authorization = "Bearer $token" }
    $runId = $launchResponse.run_id
    if ($runId) {
        Write-Host "Intake run $runId launched for project $ProjectId." -ForegroundColor Green
    } else {
        Write-Host 'Launch request completed without run_id in response.' -ForegroundColor Yellow
    }
}
catch {
    Write-Warning "Failed to launch intake run: $_"
    return
}

if ($runId) {
    try {
        $statusUri = "$ApiBase/api/intake/status?run_id=$runId"
        $statusResponse = Invoke-RestMethod -Method Get -Uri $statusUri -Headers @{ Authorization = "Bearer $token" }
        Write-Host "Run status: $($statusResponse.status) | Parsed: $($statusResponse.parsed) | Pending: $($statusResponse.pending)" -ForegroundColor Cyan
    }
    catch {
        Write-Warning "Unable to fetch intake status: $_"
    }
}
