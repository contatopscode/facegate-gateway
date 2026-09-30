<#
.SYNOPSIS
  Instala o FaceGate Gateway numa máquina Windows como serviço, junto com o
  conector do Cloudflare Tunnel.

.DESCRIPTION
  Idempotente: pode rodar de novo para atualizar o código ou reinstalar os serviços.
  - Instala Python 3.12, Git, NSSM e cloudflared via winget (se faltarem).
  - Clona/atualiza o repositório em $InstallDir (branch ou SHA fixo) e cria o venv.
  - Trava a pasta: só SYSTEM e Administrators escrevem, porque o serviço roda como SYSTEM.
  - Cria o .env a partir do .env.example (se não existir) e abre no Notepad.
  - Registra o serviço "FaceGateGateway" (NSSM): sobe no boot e reinicia se cair.
    O gateway escuta só em 127.0.0.1 — quem expõe é o túnel, não a LAN.
  - Registra o serviço do cloudflared com o token de conector do túnel nomeado.

  Rode num PowerShell "Executar como administrador":
    Set-ExecutionPolicy -Scope Process Bypass
    .\install.ps1                      # pede o token do túnel sem ecoar
    .\install.ps1 -Ref <sha>           # instala exatamente o commit revisado

.PARAMETER Ref
  Branch ou SHA a instalar. Default: main. Prefira o SHA revisado.

.PARAMETER TunnelToken
  Token do conector do Cloudflare Tunnel. Evite passar na linha de comando
  (fica no histórico do PowerShell): deixe vazio para digitar sem eco, ou use a
  variável de ambiente FACEGATE_TUNNEL_TOKEN. Enter vazio pula o túnel.
#>
param(
    [string]$InstallDir = "C:\FaceGate\gateway",
    [string]$Ref = "main",
    [int]$Port = 8000,
    [string]$TunnelToken = ""
)

$ErrorActionPreference = "Stop"
$ServiceName = "FaceGateGateway"
$RepoUrl = "https://github.com/contatopscode/facegate-gateway.git"
$G = @("-c", "safe.directory=$($InstallDir -replace "\\", "/")", "-C", $InstallDir)

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Rode este script num PowerShell aberto como administrador."
    }
}

# $ErrorActionPreference não pega exit code de comando nativo no PS 5.1.
function Assert-Exit([string]$What) {
    if ($LASTEXITCODE -ne 0) { throw "$What falhou (exit $LASTEXITCODE)." }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Install-Winget([string]$WingetId) {
    Write-Host "==> Instalando $WingetId" -ForegroundColor Cyan
    winget install --id $WingetId -e --silent --scope machine --accept-package-agreements --accept-source-agreements
    Assert-Exit "winget install $WingetId"
    Refresh-Path
}

function Ensure-Tool([string]$Command, [string]$WingetId) {
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
    Install-Winget $WingetId
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "$Command não ficou disponível depois do winget. Feche e abra o PowerShell e rode de novo."
    }
}

# O Windows traz um alias python.exe da Microsoft Store que o Get-Command encontra,
# mas que não é um Python de verdade. Pergunta ao launcher `py` pelo 3.12 real.
function Get-RealPython {
    try {
        $exe = (& py -3.12 -c "import sys;print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe)) { return $exe.Trim() }
    } catch { }
    return $null
}

Assert-Admin

Ensure-Tool "git" "Git.Git"
Ensure-Tool "nssm" "NSSM.NSSM"
Ensure-Tool "cloudflared" "Cloudflare.cloudflared"

$PyBase = Get-RealPython
if (-not $PyBase) {
    Install-Winget "Python.Python.3.12"
    $PyBase = Get-RealPython
    if (-not $PyBase) { throw "Python 3.12 não encontrado pelo launcher 'py' depois do winget." }
}
Write-Host "==> Python: $PyBase" -ForegroundColor Cyan

# --- Código ---
if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Host "==> Atualizando $InstallDir para $Ref" -ForegroundColor Cyan
    git @G fetch origin
    Assert-Exit "git fetch"
} else {
    Write-Host "==> Clonando em $InstallDir" -ForegroundColor Cyan
    if ((Test-Path $InstallDir) -and (Get-ChildItem -Force $InstallDir | Select-Object -First 1)) {
        throw "$InstallDir já existe e não é um clone do gateway. Confira quem criou e remova antes."
    }
    # Trava a pasta pai antes do clone, para ninguém criar $InstallDir com a própria ACL.
    $Parent = Split-Path $InstallDir
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    icacls $Parent /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" /Q | Out-Null
    Assert-Exit "icacls $Parent"
    git clone $RepoUrl $InstallDir
    Assert-Exit "git clone"
}
# Aceita branch (origin/<ref>) ou SHA.
git @G rev-parse --verify --quiet "origin/$Ref" | Out-Null
$Target = if ($LASTEXITCODE -eq 0) { "origin/$Ref" } else { $Ref }
git @G checkout --detach $Target
Assert-Exit "git checkout $Target"
Write-Host "==> Código em $(git @G rev-parse --short HEAD)" -ForegroundColor Cyan

# --- Permissões: o serviço roda como SYSTEM, então ninguém além de SYSTEM e
#     Administrators pode escrever no código, no venv ou no .env. ---
icacls $InstallDir /setowner "Administrators" /T /Q | Out-Null
Assert-Exit "icacls /setowner $InstallDir"
icacls $InstallDir /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" /T /Q | Out-Null
Assert-Exit "icacls $InstallDir"

# --- venv + dependências ---
$Py = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    & $PyBase -m venv (Join-Path $InstallDir ".venv")
    Assert-Exit "python -m venv"
}
& $Py -m pip install --upgrade pip --quiet
Assert-Exit "pip upgrade"
& $Py -m pip install -r (Join-Path $InstallDir "requirements.txt") --quiet
Assert-Exit "pip install -r requirements.txt"

# --- .env (nunca sobrescreve um existente) ---
$EnvFile = Join-Path $InstallDir ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $InstallDir ".env.example") $EnvFile
    Write-Host "==> Preencha o .env (GATEWAY_TOKEN, leitores, senhas), salve e feche o Notepad." -ForegroundColor Yellow
    Start-Process notepad.exe $EnvFile -Wait
}

# --- Serviço do gateway (NSSM) ---
$LogDir = Join-Path $InstallDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if (Get-Service $ServiceName -ErrorAction SilentlyContinue) {
    nssm stop $ServiceName | Out-Null
    nssm remove $ServiceName confirm | Out-Null
    Assert-Exit "nssm remove"
}
nssm install $ServiceName $Py "-m" "uvicorn" "app.main:app" "--host" "127.0.0.1" "--port" "$Port" | Out-Null
Assert-Exit "nssm install"
$settings = @(
    @("AppDirectory", $InstallDir),
    @("DisplayName", "FaceGate Gateway"),
    @("Start", "SERVICE_AUTO_START"),
    @("AppExit", "Default", "Restart"),
    @("AppRestartDelay", "5000"),
    @("AppStdout", (Join-Path $LogDir "gateway.log")),
    @("AppStderr", (Join-Path $LogDir "gateway.log")),
    @("AppRotateFiles", "1"),
    @("AppRotateBytes", "10485760")
)
foreach ($s in $settings) {
    nssm set $ServiceName @s | Out-Null
    Assert-Exit "nssm set $($s[0])"
}
nssm start $ServiceName | Out-Null
Assert-Exit "nssm start"

# --- Serviço do cloudflared (túnel nomeado) ---
if (-not $TunnelToken) { $TunnelToken = $env:FACEGATE_TUNNEL_TOKEN }
if (-not $TunnelToken) {
    $sec = Read-Host "Token do conector do túnel (Enter para pular)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { $TunnelToken = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
if ($TunnelToken) {
    Write-Host "==> Instalando o serviço do cloudflared" -ForegroundColor Cyan
    if (Get-Service "cloudflared" -ErrorAction SilentlyContinue) {
        cloudflared service uninstall | Out-Null
    }
    cloudflared service install $TunnelToken
    Assert-Exit "cloudflared service install"
} else {
    Write-Host "==> Sem token: o túnel não foi instalado." -ForegroundColor Yellow
}
$TunnelToken = $null

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
