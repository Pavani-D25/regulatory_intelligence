<#
RegTrack India - one command to set up and start everything (Windows PowerShell 5.1+).

  .\start.ps1                       first run: sets everything up, asks where the data should come from, starts it all
  .\start.ps1 -Snapshot <file>      load a database snapshot from a teammate (.dump), then start
  .\start.ps1 -Files <file.zip>     also add the stored PDFs from a teammate's files zip ("Open original PDF")
  .\start.ps1 -Data seed|crawl|skip choose the data source without being asked
  .\start.ps1 -NoSchedule           do not start the 6-hour auto-sync
  .\start.ps1 -Stop                 stop the API, auto-sync and portal (the database keeps running)

Or double-click start.bat. Needs: Python 3.11+, Node.js 18+, and PostgreSQL 16 + pgvector: either installed on this
machine (PG_BIN / PG_DATA in .env, see README "Database without Docker") or Docker Desktop.
#>
[CmdletBinding()]
param(
    [string]$Snapshot = "",
    [string]$Files = "",
    [ValidateSet("", "seed", "crawl", "skip")][string]$Data = "",
    [switch]$NoSchedule,
    [switch]$NoBrowser,
    [switch]$Stop
)

# "Continue", not "Stop": in Windows PowerShell 5.1 any stderr line from a native program (docker, pip, npm) becomes
# an error record, so "Stop" would abort on harmless messages - e.g. `docker info` while Docker is still starting.
# Every step checks $LASTEXITCODE itself and calls Fail with a clear message.
$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "data\logs"

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "    $text" -ForegroundColor Green }
function Info($text) { Write-Host "    $text" }
function Fail($text) { Write-Host ""; Write-Host "  ! $text" -ForegroundColor Red; Write-Host ""; Read-Host "Press Enter to close" | Out-Null; exit 1 }

function Stop-RegTrack {
    # only our own programs: Python (API, auto-sync), Node (portal) and the PowerShell windows this script opened
    $procs = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -match "^python" -and $_.CommandLine -match "regtrack\.cli (api|schedule)") -or
        ($_.Name -match "^(powershell|pwsh)" -and $_.CommandLine -match "WindowTitle = 'RegTrack - (API|auto-sync|portal)'") -or
        ($_.Name -eq "node.exe" -and $_.CommandLine -match "vite" -and ("$($_.CommandLine)".Replace("/", "\") -match [regex]::Escape($Root)))
    }
    foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Info "stopped $($p.Name) $($p.ProcessId)" } catch {} }
    if (-not $procs) { Info "nothing was running" }
}

if ($Stop) { Step "Stopping RegTrack"; Stop-RegTrack; exit 0 }

Write-Host ""
Write-Host "  RegTrack India - setup and start" -ForegroundColor White
Write-Host "  $Root"

# ---------------------------------------------------------------- 1. tools
# database on this machine (PG_BIN set in .env) or in Docker
$LocalDb = (Test-Path ".env") -and (Select-String -Path ".env" -Pattern '^\s*PG_BIN\s*=\s*[^#\s]' -Quiet)
Step "Checking tools"
$sysPy = $null
foreach ($spec in @("py|-3", "python|")) {
    $cand = $spec.Split("|")   # program | first argument (may be empty)
    $pyArgs = @(); if ($cand[1]) { $pyArgs = @($cand[1]) }
    try {
        $v = & $cand[0] @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) {
            $parts = $v.Trim().Split(".")
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) { $sysPy = $cand[0]; $sysPyArgs = $pyArgs; Ok "Python $v"; break }
        }
    } catch {}
}
if (-not $sysPy -and -not (Test-Path $Py)) { Fail "Python 3.11 or newer is needed: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "Node.js 18 or newer is needed: https://nodejs.org/" }
Ok "Node.js found"
if ($LocalDb) {
    Ok "database: PostgreSQL on this machine (PG_BIN in .env)"
} else {
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "Docker Desktop is needed (or a local PostgreSQL, see README): https://www.docker.com/products/docker-desktop/" }
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Info "Docker Desktop is not running - starting it (this can take a minute)"
    try { docker desktop start *> $null } catch {}
    if ($LASTEXITCODE -ne 0) {
        $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (Test-Path $dd) { Start-Process $dd }
    }
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) { Start-Sleep -Seconds 3; docker info *> $null; if ($LASTEXITCODE -eq 0) { $ready = $true; break } }
    if (-not $ready) { Fail "Docker did not start. Open Docker Desktop, wait until it says 'Engine running', then run this again." }
}
Ok "Docker engine running"
}

# ---------------------------------------------------------------- 2. settings
Step "Settings (.env)"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Ok "created .env from .env.example"
    Info "AI features stay off until LLM_BASE_URL and EMBED_MODEL are set in .env (LM Studio address)."
} else { Ok ".env exists" }
if (-not (Test-Path "dashboard\.env")) { Copy-Item "dashboard\.env.example" "dashboard\.env"; Ok "created dashboard\.env" }

# ---------------------------------------------------------------- 3. Python environment
Step "Python environment"
$marker = Join-Path $Root ".venv\.installed"
if (-not (Test-Path $Py)) {
    Info "creating .venv"
    if (-not $sysPy) { Fail "Python 3.11 or newer is needed to create .venv" }
    & $sysPy @sysPyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "could not create the virtual environment" }
}
$need = (-not (Test-Path $marker)) -or ((Get-Item "pyproject.toml").LastWriteTime -gt (Get-Item $marker).LastWriteTime)
if ($need) {
    Info "installing Python packages (first time: a few minutes)"
    & $Py -m pip install --upgrade pip --quiet
    & $Py -m pip install -e ".[dev]" --quiet
    if ($LASTEXITCODE -ne 0) { Fail "pip install failed. Low disk space on C:? Set TMP/TEMP to a folder on another drive and retry." }
    Set-Content -Path $marker -Value (Get-Date -Format s)
    Ok "packages installed"
} else { Ok "packages up to date" }

# ---------------------------------------------------------------- 4. database
if ($LocalDb) {
    Step "Database (PostgreSQL 16 + pgvector on this machine)"
    & $Py -m regtrack.cli db start
    if ($LASTEXITCODE -ne 0) { Fail "the local database did not start (see data\pglog\postgres.log)" }
} else {
    Step "Database (PostgreSQL 16 + pgvector in Docker)"
    $exists = docker ps -a --filter "name=^regtrack-db$" --format "{{.Names}}"
    if ($exists) { docker start regtrack-db *> $null } else { docker compose up -d db; if ($LASTEXITCODE -ne 0) { Fail "could not start the database container" } }
    $healthy = $false
    for ($i = 0; $i -lt 40; $i++) {
        $h = docker inspect -f "{{.State.Health.Status}}" regtrack-db 2>$null
        if ($h -eq "healthy") { $healthy = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) { Fail "the database did not become ready (docker logs regtrack-db shows why)" }
}
Ok "database ready on localhost:5432"

if ($Snapshot) {
    if (-not (Test-Path $Snapshot)) { Fail "snapshot not found: $Snapshot" }
    Info "loading snapshot $Snapshot (replaces the local database)"
    & $Py -m regtrack.cli snapshot-import "$Snapshot" --yes
    if ($LASTEXITCODE -ne 0) { Fail "snapshot import failed" }
}
& $Py -m regtrack.cli migrate
if ($LASTEXITCODE -ne 0) { Fail "database migration failed" }
if ($Files) {
    if (-not (Test-Path $Files)) { Fail "files zip not found: $Files" }
    & $Py -m regtrack.cli snapshot-import "$Files"
}

# ---------------------------------------------------------------- 5. data
Step "Data"
$docs = & $Py -c "from regtrack.db import connect; print(connect().execute('select count(*) AS n from documents').fetchone()['n'])" 2>$null
if (-not $docs) { $docs = 0 } else { $docs = ("$docs").Trim() }
if ([int]$docs -gt 0) {
    Ok "$docs documents in the database"
} else {
    $seedDir = & $Py -c "from regtrack.config import get_settings; print(get_settings().seed_corpus_dir)"
    $choice = $Data
    if (-not $choice) {
        Write-Host ""
        Write-Host "    The database is empty. Where should the data come from?" -ForegroundColor Yellow
        Write-Host "      1  A snapshot file from a teammate (fastest: about a minute)"
        Write-Host "      2  The seed corpus folder $seedDir (about 45 minutes)"
        Write-Host "      3  Download live from MoRTH, ARAI, e-Gazette and India Code (about an hour)"
        Write-Host "      4  Skip for now"
        $ans = Read-Host "    Choose 1-4"
        switch ($ans) {
            "1" { $choice = "snapshot" }
            "2" { $choice = "seed" }
            "3" { $choice = "crawl" }
            default { $choice = "skip" }
        }
    }
    if ($choice -eq "snapshot") {
        $f = Read-Host "    Path to the .dump file"
        $f = $f.Trim('"')
        if (-not (Test-Path $f)) { Fail "not found: $f" }
        & $Py -m regtrack.cli snapshot-import "$f" --yes
        & $Py -m regtrack.cli migrate
    } elseif ($choice -eq "seed") {
        if (-not (Test-Path $seedDir)) { Fail "seed corpus folder not found: $seedDir (set SEED_CORPUS_DIR in .env)" }
        Info "importing the seed corpus (read-only) and processing it - leave this window open"
        & $Py -m regtrack.cli import-seed
        & $Py -m regtrack.cli run
    } elseif ($choice -eq "crawl") {
        Info "downloading from the four sources and processing - leave this window open"
        & $Py -m regtrack.cli crawl
    } else {
        Info "skipped - the portal will be empty until data is loaded"
    }
}

# ---------------------------------------------------------------- 6. portal packages
Step "Portal (React + Vite)"
if (-not (Test-Path "dashboard\node_modules") -or ((Get-Item "dashboard\package.json").LastWriteTime -gt (Get-Item "dashboard\node_modules").LastWriteTime)) {
    Info "installing portal packages (first time: a minute)"
    Push-Location dashboard
    npm install --no-fund --no-audit
    $rc = $LASTEXITCODE
    Pop-Location
    if ($rc -ne 0) { Fail "npm install failed" }
}
Ok "portal packages ready"

# ---------------------------------------------------------------- 7. start
Step "Starting"
Stop-RegTrack | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
function Launch($title, $command) {
    $cmd = "`$Host.UI.RawUI.WindowTitle = 'RegTrack - $title'; Set-Location '$Root'; $command"
    Start-Process powershell -ArgumentList "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd -WindowStyle Minimized | Out-Null
}
# each window also appends its output to data\logs\<name>.log, so a stalled sync can be traced afterwards
Launch "API" "& '$Py' -m regtrack.cli api *>> '$LogDir\api.log'"
# one auto-sync per country (a scheduler serves the country in REGTRACK_COUNTRY); their pipeline runs share one
# database advisory lock, so they never overlap
if (-not $NoSchedule) {
    foreach ($cc in @("IN", "TH", "MY")) { Launch "auto-sync $cc" "`$env:REGTRACK_COUNTRY='$cc'; & '$Py' -m regtrack.cli schedule *>> '$LogDir\scheduler_$cc.log'" }
}
Launch "portal" "Set-Location dashboard; npm run dev *>> '$LogDir\portal.log'"

$up = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try { Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 | Out-Null; $up = $true; break } catch {}
}
if ($up) { Ok "API      http://127.0.0.1:8000/docs" } else { Info "API is still starting - see the 'RegTrack - API' window" }
$portal = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try { Invoke-WebRequest -Uri "http://localhost:5173/" -UseBasicParsing -TimeoutSec 2 | Out-Null; $portal = $true; break } catch {}
}
if ($portal) { Ok "Portal   http://localhost:5173" } else { Info "Portal is still starting - see the 'RegTrack - portal' window" }
if (-not $NoSchedule) { Ok "Auto-sync every 6 hours (window 'RegTrack - auto-sync'; keep it open)" }

Write-Host ""
Write-Host "  RegTrack is running. Stop it with:  .\start.ps1 -Stop" -ForegroundColor Green
Write-Host ""
if (-not $NoBrowser -and $portal) { Start-Process "http://localhost:5173" }
