$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$routerDir = Join-Path $root "router_service"
$ragDir = Join-Path $root "rag_service"
$workdayDir = Join-Path $root "workday_tools"
$frontendDir = Join-Path $root "frontend"
$defaultQuotaProject = "prj-dev-ai-vertex-bryz"
$defaultCaBundle = Join-Path $root "certs\combined-ca-bundle.pem"
$ports = @(8000, 8001, 8011, 8002, 5001, 5173)

$ragPython = Join-Path $ragDir ".venv\Scripts\python.exe"
$routerPython = $ragPython
$workdayPython = Join-Path $workdayDir ".venv\Scripts\python.exe"

function Start-ServiceWindow($title, $command) {
    $bytes = [System.Text.Encoding]::Unicode.GetBytes($command)
    $encoded = [Convert]::ToBase64String($bytes)
    Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encoded -WindowStyle Normal -ErrorAction Stop | Out-Null
    Write-Host "Started $title window"
}

function Stop-Ports($ports) {
    foreach ($port in $ports) {
        try {
            $pids = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($pid in $pids) {
                if ($pid -and $pid -ne 0) {
                    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {
            # Ignore failures; ports may not be bound.
        }
    }
}

Write-Host ("Stopping existing services on ports {0}..." -f ($ports -join ", "))
Stop-Ports $ports

Write-Host "ADC check skipped. If needed, run: gcloud auth application-default login --project $defaultQuotaProject"

Write-Host "Starting Router backend (port 8000)..."
$routerCommand = @'
Set-Location "{0}"
$env:PYTHONPATH = "{0}"
$env:REQUESTS_CA_BUNDLE = "{1}"
$env:SSL_CERT_FILE = "{1}"
$env:GRPC_DEFAULT_SSL_ROOTS_FILE_PATH = "{1}"
$env:RAG_RELAX_SSL = "true"
if (-not $env:GOOGLE_CLOUD_QUOTA_PROJECT) {{ $env:GOOGLE_CLOUD_QUOTA_PROJECT = "{2}" }}
& "{3}" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
'@ -f $routerDir, $defaultCaBundle, $defaultQuotaProject, $routerPython
Start-ServiceWindow "Router Backend" $routerCommand

Write-Host "Starting RAG backend (port 8011)..."
$ragCommand = @'
Set-Location "{0}"
$env:PYTHONPATH = "{0}"
$env:REQUESTS_CA_BUNDLE = "{1}"
$env:SSL_CERT_FILE = "{1}"
$env:GRPC_DEFAULT_SSL_ROOTS_FILE_PATH = "{1}"
$env:RAG_RELAX_SSL = "true"
if (-not $env:GOOGLE_CLOUD_QUOTA_PROJECT) {{ $env:GOOGLE_CLOUD_QUOTA_PROJECT = "{2}" }}
& "{3}" -m uvicorn app.main:app --host 0.0.0.0 --port 8011 --reload
'@ -f $ragDir, $defaultCaBundle, $defaultQuotaProject, $ragPython
Start-ServiceWindow "RAG Backend" $ragCommand

Write-Host "Starting Workday tools backend (port 5001)..."
# Clear cached tokens/flags so OAuth prompts on first request
Get-ChildItem $workdayDir -Filter ".token_cache.*" -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue
Get-ChildItem $workdayDir -Filter ".evl_sent.flag" -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue
# Start from repo root so package imports work; set headless env so OAuth pops a browser; use Python 3.12 venv
$workdayCommand = @'
Set-Location "{0}"
$env:PYTHONPATH = "{0}"
$env:ASKHR_CHROMEDRIVER_PATH = "{1}\drivers\chromedriver.exe"
$env:PATH = "{1}\drivers;{1};" + $env:PATH
& "{2}" -m uvicorn workday_tools.server:app --host 0.0.0.0 --port 5001
'@ -f $root, $workdayDir, $workdayPython
Start-ServiceWindow "Workday Tools Backend" $workdayCommand

Write-Host "Starting frontend dev server (vite)..."
$frontendCommand = @'
Set-Location "{0}"
npm run dev
'@ -f $frontendDir
Start-ServiceWindow "Frontend" $frontendCommand

Write-Host "All services launched in separate windows."
