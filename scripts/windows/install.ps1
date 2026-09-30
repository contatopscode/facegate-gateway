<#
.SYNOPSIS
  Instala o FaceGate Gateway numa máquina Windows como serviço, junto com o
  conector do Cloudflare Tunnel.

.DESCRIPTION
  Idempotente: pode rodar de novo para atualizar o código ou reinstalar os serviços.
  - Instala Python 3.12, Git, NSSM e cloudflared via winget (se faltarem).
  - Clona/atualiza o repositório em $InstallDir e cria o venv.
  - Cria o .env a partir do .env.example (se não existir) e abre no Notepad.
  - Registra o serviço "FaceGateGateway" (NSSM): sobe no boot e reinicia se cair.
    O gateway escuta só em 127.0.0.1 — quem expõe é o túnel, não a LAN.
  - Registra o serviço do cloudflared com o token de conector do túnel nomeado.

  Rode num PowerShell "Executar como administrador":
    Set-ExecutionPolicy -Scope Process Bypass
    .\install.ps1 -TunnelToken "<token do conector>"

.PARAMETER TunnelToken
  Token do conector do Cloudflare Tunnel (o DevOps envia por canal seguro).
  Sem ele, só o gateway é instalado.
#>
param(
    [string]$InstallDir = "C:\FaceGate\gateway",
    [string]$Branch = "main",
    [int]$Port = 8000,
    [string]$TunnelToken = ""
)

$ErrorActionPreference = "Stop"
$ServiceName = "FaceGateGateway"
$RepoUrl = "https://github.com/contatopscode/facegate-gateway.git"

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Rode este script num PowerShell aberto como administrador."
    }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure-Tool([string]$Command, [string]$WingetId) {
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
    Write-Host "==> Instalando $WingetId" -ForegroundColor Cyan
    winget install --id $WingetId -e --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "$Command não ficou disponível depois do winget. Feche e abra o PowerShell e rode de novo."
    }
}

Assert-Admin

Ensure-Tool "git" "Git.Git"
Ensure-Tool "python" "Python.Python.3.12"
Ensure-Tool "nssm" "NSSM.NSSM"
Ensure-Tool "cloudflared" "Cloudflare.cloudflared"

# --- Código ---
if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Host "==> Atualizando $InstallDir ($Branch)" -ForegroundColor Cyan
    git -C $InstallDir fetch origin $Branch
    git -C $InstallDir checkout $Branch
    git -C $InstallDir reset --hard "origin/$Branch"
} else {
    Write-Host "==> Clonando em $InstallDir" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null
    git clone --branch $Branch $RepoUrl $InstallDir
}

# --- venv + dependências ---
$Py = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { python -m venv (Join-Path $InstallDir ".venv") }
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install -r (Join-Path $InstallDir "requirements.txt") --quiet

# --- .env (nunca sobrescreve um existente) ---
$EnvFile = Join-Path $InstallDir ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $InstallDir ".env.example") $EnvFile
    # Só o SYSTEM (conta do serviço) e administradores leem o .env.
    icacls $EnvFile /inheritance:r /grant:r "SYSTEM:(R)" "Administrators:(F)" | Out-Null
    Write-Host "==> Preencha o .env (GATEWAY_TOKEN, leitores, senhas), salve e feche o Notepad." -ForegroundColor Yellow
    Start-Process notepad.exe $EnvFile -Wait
}

# --- Serviço do gateway (NSSM) ---
$LogDir = Join-Path $InstallDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if (Get-Service $ServiceName -ErrorAction SilentlyContinue) {
    nssm stop $ServiceName | Out-Null
    nssm remove $ServiceName confirm | Out-Null
}
nssm install $ServiceName $Py "-m" "uvicorn" "app.main:app" "--host" "127.0.0.1" "--port" "$Port" | Out-Null
nssm set $ServiceName AppDirectory $InstallDir | Out-Null
nssm set $ServiceName DisplayName "FaceGate Gateway" | Out-Null
nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
nssm set $ServiceName AppExit Default Restart | Out-Null
nssm set $ServiceName AppRestartDelay 5000 | Out-Null
nssm set $ServiceName AppStdout (Join-Path $LogDir "gateway.log") | Out-Null
nssm set $ServiceName AppStderr (Join-Path $LogDir "gateway.log") | Out-Null
nssm set $ServiceName AppRotateFiles 1 | Out-Null
nssm set $ServiceName AppRotateBytes 10485760 | Out-Null
nssm start $ServiceName | Out-Null

# --- Serviço do cloudflared (túnel nomeado) ---
if ($TunnelToken) {
    Write-Host "==> Instalando o serviço do cloudflared" -ForegroundColor Cyan
    if (Get-Service "cloudflared" -ErrorAction SilentlyContinue) {
        cloudflared service uninstall | Out-Null
    }
    cloudflared service install $TunnelToken
} else {
    Write-Host "==> Sem -TunnelToken: o túnel não foi instalado." -ForegroundColor Yellow
}

# --- Verificação ---
Start-Sleep -Seconds 5
try {
    $r = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 10
    Write-Host "==> Gateway OK: $($r | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Host "==> O gateway não respondeu em /health. Veja $LogDir\gateway.log" -ForegroundColor Red
    exit 1
}
Get-Service $ServiceName, cloudflared -ErrorAction SilentlyContinue |
    Format-Table Name, Status, StartType -AutoSize
