#Requires -Version 5.1
<#
.SYNOPSIS
    SkillMate all-in-one launcher with ngrok public URL.

.DESCRIPTION
    Starts (in order): ngrok -> Backend -> Frontend -> Proxy
    Gets the ngrok HTTPS URL first, updates backend/.env, then starts
    all services so they boot with the correct public URL already in config.

.NOTES
    Prerequisites (must be installed and in PATH):
      - python  3.11+
      - node    18+
      - ngrok   (authenticated: run "ngrok authtoken <token>" once)

    Ports used:
      8000  FastAPI backend
      3000  Next.js frontend
      8080  Proxy (the one exposed via ngrok)
#>

$ErrorActionPreference = "Stop"

$ROOT      = $PSScriptRoot
$BE_DIR    = "$ROOT\backend"
$FE_DIR    = "$ROOT\frontend"
$PROXY_DIR = "$ROOT\proxy"
$ENV_FILE  = "$BE_DIR\.env"

$PROXY_PORT = 8080
$BE_PORT    = 8000
$FE_PORT    = 3000

$allProcs = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

# ---------- helpers ----------------------------------------------------------

function Write-Step([string]$msg) {
    Write-Host "`n$msg" -ForegroundColor Cyan
}

function Write-Ok([string]$msg) {
    Write-Host "  OK  $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "  !!  $msg" -ForegroundColor Yellow
}

function Write-Fail([string]$msg) {
    Write-Host "  XX  $msg" -ForegroundColor Red
}

# Opens a new cmd window; returns the Process object.
function Start-Window {
    param(
        [string]$Title,
        [string]$WorkDir,
        [string]$Command
    )
    $bat = "$env:TEMP\sm_$($Title -replace '[^A-Za-z0-9]','_').bat"
    $content = "@echo off`r`ntitle SkillMate :: $Title`r`ncd /d `"$WorkDir`"`r`n$Command`r`npause"
    [System.IO.File]::WriteAllText($bat, $content, [System.Text.UTF8Encoding]::new($false))
    $p = Start-Process cmd -ArgumentList "/k `"$bat`"" -PassThru -WindowStyle Normal
    $allProcs.Add($p)
    return $p
}

function Stop-All {
    Write-Host "`nStopping all SkillMate services..." -ForegroundColor Yellow
    foreach ($p in $allProcs) {
        if ($p -and -not $p.HasExited) {
            try { & taskkill /F /T /PID $p.Id 2>$null } catch {}
        }
    }
}

function Wait-Port {
    param([int]$Port, [int]$MaxSeconds = 60, [string]$Name = "service")
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $MaxSeconds) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("127.0.0.1", $Port)
            $tcp.Close()
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    Write-Warn "$Name on port $Port did not become ready in ${MaxSeconds}s"
    return $false
}

# ---------- preflight --------------------------------------------------------

Write-Step "Checking prerequisites..."

@("python","node","ngrok") | ForEach-Object {
    if (-not (Get-Command $_ -ErrorAction SilentlyContinue)) {
        Write-Fail "$_ not found in PATH. Please install it first."
        exit 1
    }
}
Write-Ok "python / node / ngrok found"

if (-not (Test-Path "$FE_DIR\node_modules")) {
    Write-Warn "node_modules not found - running npm install in frontend..."
    Push-Location $FE_DIR
    npm install --silent
    Pop-Location
}
Write-Ok "Frontend dependencies ready"

# ---------- Python venv setup ------------------------------------------------

Write-Step "Setting up Python environments..."

if (-not (Test-Path "$BE_DIR\venv\Scripts\python.exe")) {
    Write-Host "  Creating BE venv (first run - may take a minute)..."
    python -m venv "$BE_DIR\venv"
    & "$BE_DIR\venv\Scripts\pip.exe" install -r "$BE_DIR\requirements.txt" -q --progress-bar off
    Write-Ok "BE venv ready"
} else {
    Write-Ok "BE venv already exists"
}

if (-not (Test-Path "$PROXY_DIR\venv\Scripts\python.exe")) {
    Write-Host "  Creating proxy venv..."
    python -m venv "$PROXY_DIR\venv"
    & "$PROXY_DIR\venv\Scripts\pip.exe" install -r "$PROXY_DIR\requirements.txt" -q --progress-bar off
    Write-Ok "Proxy venv ready"
} else {
    Write-Ok "Proxy venv already exists"
}

# ---------- Step 1: ngrok first - get the public URL -------------------------

Write-Step "Starting ngrok on port $PROXY_PORT..."

$ngrokProc = Start-Process ngrok `
    -ArgumentList "http $PROXY_PORT --request-header-add=`"ngrok-skip-browser-warning:true`"" `
    -PassThru -WindowStyle Minimized
$allProcs.Add($ngrokProc)

# Poll ngrok local API for the tunnel URL (retry up to 15 s)
$ngrokUrl = $null
$attempts = 0
while ($attempts -lt 30 -and -not $ngrokUrl) {
    Start-Sleep -Milliseconds 500
    $attempts++
    try {
        $data     = Invoke-RestMethod "http://localhost:4040/api/tunnels" -ErrorAction Stop
        $ngrokUrl = ($data.tunnels | Where-Object { $_.proto -eq "https" }).public_url
    } catch {}
}

if (-not $ngrokUrl) {
    Write-Fail "Could not get ngrok URL after 15 seconds."
    Write-Host "  Make sure ngrok is authenticated: ngrok authtoken <your-token>" -ForegroundColor Yellow
    Write-Host "  Get a free token at: https://dashboard.ngrok.com/get-started/your-authtoken" -ForegroundColor Yellow
    Stop-All
    exit 1
}
Write-Ok "ngrok URL: $ngrokUrl"

# ---------- Step 2: update .env with the live ngrok URL ----------------------

Write-Step "Updating $ENV_FILE..."

$envContent = Get-Content $ENV_FILE -Raw

$envContent = [regex]::Replace($envContent, '(?m)^APP_URL=.*',            "APP_URL=$ngrokUrl")
$envContent = [regex]::Replace($envContent, '(?m)^CORS_ORIGINS=.*',
    "CORS_ORIGINS=[`"http://localhost:$FE_PORT`",`"$ngrokUrl`"]")

# UTF-8 without BOM - python-dotenv can choke on the BOM that PS5 Set-Content adds
[System.IO.File]::WriteAllText($ENV_FILE, $envContent, [System.Text.UTF8Encoding]::new($false))
Write-Ok ".env updated"

# ---------- Step 3: launch services ------------------------------------------

Write-Step "Starting Backend (FastAPI)..."
Start-Window -Title "Backend" `
    -WorkDir $BE_DIR `
    -Command "call venv\Scripts\activate.bat && uvicorn main:app --reload --port $BE_PORT"
if (Wait-Port -Port $BE_PORT -MaxSeconds 60 -Name "Backend") { Write-Ok "Backend up" }

Write-Step "Starting Frontend (Next.js)..."
Start-Window -Title "Frontend" `
    -WorkDir $FE_DIR `
    -Command "npm run dev"
if (Wait-Port -Port $FE_PORT -MaxSeconds 90 -Name "Frontend") { Write-Ok "Frontend up" }

Write-Step "Starting Proxy..."
Start-Window -Title "Proxy" `
    -WorkDir $PROXY_DIR `
    -Command "call venv\Scripts\activate.bat && uvicorn main:app --host 0.0.0.0 --port $PROXY_PORT"
if (Wait-Port -Port $PROXY_PORT -MaxSeconds 30 -Name "Proxy") { Write-Ok "Proxy up" }

# ---------- summary ----------------------------------------------------------

Write-Host ""
Write-Host "+--------------------------------------------------------------+" -ForegroundColor Magenta
Write-Host "|          SkillMate is live on the internet                   |" -ForegroundColor Magenta
Write-Host "+--------------------------------------------------------------+" -ForegroundColor Magenta
Write-Host "  App (FE)  : $ngrokUrl" -ForegroundColor White
Write-Host "  API (BE)  : $ngrokUrl/api" -ForegroundColor White
Write-Host "+--------------------------------------------------------------+" -ForegroundColor Magenta
Write-Host "  Local  FE=:$FE_PORT  BE=:$BE_PORT  Proxy=:$PROXY_PORT" -ForegroundColor DarkGray
Write-Host "+--------------------------------------------------------------+" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Press Ctrl+C in THIS window to stop all services." -ForegroundColor Cyan

# ---------- wait and clean up ------------------------------------------------

try {
    while ($true) { Start-Sleep -Seconds 5 }
} finally {
    Stop-All
}

