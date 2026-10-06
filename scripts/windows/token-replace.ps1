<#
.SYNOPSIS
  Substitui GATEWAY_TOKEN no .env e adiciona/atualiza leitor(es) ao JSON
  LEITORES sem precisar abrir Bloco de Notas. Idempotente.

.DESCRIPTION
  Rode num PowerShell "Executar como administrador" no servidor onde o
  FaceGate Gateway esta instalado (C:\FaceGate\gateway por padrao).

  Uso tipico:
    # 1) Trocar o token placeholder pelo token real do backend
    .\token-replace.ps1 -Token "p2TaK2-ulpIQ28uEwvRNdVEGWE6J-qjWTMeapEk0n9o"

    # 2) Trocar token E adicionar leitor novo:
    $pw = Read-Host "Senha do admin do leitor .161" -AsSecureString
    .\token-replace.ps1 `
        -Token "p2TaK2-ulpIQ28uEwvRNdVEGWE6J-qjWTMeapEk0n9o" `
        -Leitor prelo-predio `
        -Host 10.5.50.161 `
        -Port 80 `
        -Scheme http `
        -Password $pw

    # 3) Simular antes de aplicar (-WhatIf):
    .\token-replace.ps1 -Token "novo-token-aqui" -WhatIf

    # 4) Gerar token novo e gravar (rotacao de segredo):
    .\token-replace.ps1 -Rollout   # gera e grava; backend vai precisar atualizar tambem

  Como funciona:
  - Le o .env existente (preserva comentarios e ordem das linhas).
  - Substitui so a linha GATEWAY_TOKEN se mudar; caso contrario, reporta.
  - Adiciona/atualiza o leitor no JSON LEITORES (sem duplicar chave).
  - Grava em UTF-8 sem BOM (python -c consegue ler; Notepad tambem abre).
  - Reinicia o servico FaceGateGateway pra recarregar settings (senao o
    token continua com placeholder em memoria).
  - Confere /health local pra garantir que subiu.

.PARAMETER Token
  Novo valor de GATEWAY_TOKEN. Opcional se -Rollout for usado.

.PARAMETER Rollout
  Gera um token novo (token_urlsafe(32) via Python) ao inves de usar -Token.
  Use quando quiser rotacionar o segredo (o backend FaceGate tera que ser
  atualizado tambem com o mesmo valor).

.PARAMETER Leitor
  Nome do leitor (a-z, 0-9, '-') pra adicionar/atualizar no JSON LEITORES.

.PARAMETER Host
  IP/hostname do leitor. Obrigatorio se -Leitor for passado.

.PARAMETER Port
  Porta ISAPI do leitor. Default 80.

.PARAMETER Scheme
  http ou https. Default http (muitos DS-K1T3xx/6xx so atendem em texto claro).

.PARAMETER User
  Usuario do leitor. Default 'admin'.

.PARAMETER Password
  Senha do leitor (SecureString, nao vai pro historico do PowerShell).

.PARAMETER InstallDir
  Diretorio de instalacao do gateway. Default C:\FaceGate\gateway.

.PARAMETER NoRestart
  Nao reinicia o servico FaceGateGateway. Use se for aplicar varios
  ajustes em sequencia e quiser reiniciar so uma vez no final.

.PARAMETER WhatIf
  Mostra o que mudaria sem gravar nem reiniciar nada.

.EXAMPLE
  .\token-replace.ps1 -Token "novo-token-real-de-32-chars-minimo"

.EXAMPLE
  .\token-replace.ps1 -Rollout

.EXAMPLE
  .\token-replace.ps1 -Token "novo-token" -Leitor bancada -Host 10.0.0.20 -Port 80 -Scheme http -Password (Read-Host -AsSecureString)

.NOTES
  Idempotente. Pode rodar varias vezes sem duplicar linha. Preserva
  comentarios do .env.

  Adicionado no PSCODE-FG-FSW-2026-015. Ate entao a unica forma de trocar
  o token era abrir o Bloco de Notas, editar, salvar e reiniciar o servico
  manualmente -- passos faceis de pular, e o resultado e um gateway rodando
  com placeholder publico (qualquer um com acesso ao tunel fala com ele).
#>
param(
    [Parameter(Mandatory=$false)][string]$Token,
    [Parameter(Mandatory=$false)][switch]$Rollout,
    [Parameter(Mandatory=$false)][string]$Leitor,
    [Parameter(Mandatory=$false)][string]$Host,
    [Parameter(Mandatory=$false)][int]$Port = 80,
    [Parameter(Mandatory=$false)][ValidateSet('http','https')][string]$Scheme = 'http',
    [Parameter(Mandatory=$false)][string]$User = 'admin',
    [Parameter(Mandatory=$false)][SecureString]$Password,
    [string]$InstallDir = 'C:\FaceGate\gateway',
    [switch]$NoRestart,
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$EnvFile = Join-Path $InstallDir '.env'
$Py = Join-Path $InstallDir '.venv\Scripts\python.exe'

# --- Validacoes de entrada -------------------------------------------------

if (-not $Token -and -not $Rollout) {
    throw "Passe -Token <valor> ou -Rollout pra gerar um novo."
}
if ($Token -and $Rollout) {
    throw "-Token e -Rollout sao mutuamente exclusivos."
}
if ($Leitor) {
    if (-not $Host) { throw "-Host e obrigatorio quando -Leitor e passado." }
    if (-not $Password) { throw "-Password e obrigatorio quando -Leitor e passado." }
    if ($Leitor -notmatch '^[a-z0-9][a-z0-9\-]*$') {
        throw "Nome de leitor '$Leitor' invalido. Use a-z, 0-9 e '-'."
    }
}

# --- Gera token se for -Rollout -------------------------------------------

if ($Rollout) {
    if (-not (Test-Path $Py)) { throw "Python nao encontrado em $Py. Rode install.ps1 primeiro." }
    $Token = & $Py -c "import secrets; print(secrets.token_urlsafe(32))"
    Write-Host "Token gerado: $Token" -ForegroundColor Green
    Write-Host "ATENCAO: anote este valor - o backend FaceGate tambem precisa dele." -ForegroundColor Yellow
}

# --- Converte SecureString em plain (escopo local) ------------------------

function Get-PlainPassword([SecureString]$sec) {
    if (-not $sec) { return '' }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null }
}

# --- Aplica mudancas no .env (idempotente) --------------------------------

function Save-EnvFile([hashtable]$Changes, [bool]$WhatIf, [string]$EnvFile) {
    $lines = if (Test-Path $EnvFile) {
        Get-Content $EnvFile -Encoding UTF8
    } else {
        if ($WhatIf) {
            Write-Host "[WHATIF] .env nao existe em $EnvFile - seria criado." -ForegroundColor Magenta
        } else {
            Write-Host ".env nao existe em $EnvFile - criando vazio." -ForegroundColor Yellow
        }
        @()
    }
    $out = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    foreach ($line in $lines) {
        if ($line -match '^\s*#') { $out.Add($line); continue }
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)=(.*)$') {
            $key = $Matches[1]
            $currentValue = $Matches[2]
            if ($Changes.ContainsKey($key)) {
                $newValue = $Changes[$key]
                if ($currentValue -ne $newValue) {
                    if (-not $WhatIf) { $out.Add("$key=$newValue") }
                    Write-Host "  $key : ALTERADO" -ForegroundColor Yellow
                    Write-Host "    de: $currentValue" -ForegroundColor DarkGray
                    Write-Host "    pra: $newValue" -ForegroundColor DarkGray
                } else {
                    Write-Host "  $key : ja era o valor desejado (sem mudanca)" -ForegroundColor Green
                    $out.Add($line)
                }
                $seen[$key] = $true
            } else {
                $out.Add($line)
            }
        } else {
            $out.Add($line)
        }
    }
    foreach ($k in $Changes.Keys) {
        if (-not $seen.ContainsKey($k)) {
            if (-not $WhatIf) { $out.Add("$k=$($Changes[$k])") }
            Write-Host "  $k : NOVO -> $($Changes[$k])" -ForegroundColor Cyan
        }
    }
    if ($WhatIf) {
        Write-Host "[WHATIF] Nao gravei $EnvFile. Rode sem -WhatIf pra aplicar." -ForegroundColor Magenta
        return
    }
    # Garante que o diretorio existe (install.ps1 ja cria, mas por seguranca)
    $parentDir = Split-Path $EnvFile -Parent
    if (-not (Test-Path $parentDir)) {
        New-Item -ItemType Directory -Force -Path $parentDir | Out-Null
    }
    # UTF-8 sem BOM (python -c consegue ler; Notepad tambem abre)
    [System.IO.File]::WriteAllText(
        $EnvFile,
        ($out -join "`n"),
        (New-Object System.Text.UTF8Encoding $false)
    )
    Write-Host ".env gravado em $EnvFile" -ForegroundColor Green
}

# --- Monta hashtable de mudancas ------------------------------------------

$Changes = @{}
if ($Token) {
    $Changes['GATEWAY_TOKEN'] = $Token
}
if ($Leitor) {
    $plain = Get-PlainPassword $Password
    $leitorObj = [ordered]@{
        host     = $Host
        port     = $Port
        scheme   = $Scheme
        user     = $User
        password = $plain
    }
    # Le LEITORES atual (se houver) e adiciona/substitui a chave do leitor.
    $leitoresAtuais = [ordered]@{}
    if (Test-Path $EnvFile) {
        $linhas = Get-Content $EnvFile -Encoding UTF8
        foreach ($linha in $linhas) {
            if ($linha -match '^\s*LEITORES=(.+)$') {
                $json = $Matches[1]
                try {
                    $obj = $json | ConvertFrom-Json -ErrorAction Stop
                    foreach ($prop in $obj.PSObject.Properties) {
                        $leitoresAtuais[$prop.Name] = $prop.Value
                    }
                } catch {
                    Write-Host "AVISO: LEITORES existente nao era JSON valido, sera reescrito: $_" -ForegroundColor Yellow
                }
            }
        }
    }
    $leitoresAtuais[$Leitor] = $leitorObj
    $Changes['LEITORES'] = $leitoresAtuais | ConvertTo-Json -Compress
    # Zera a referencia plain (mitigacao simples contra despejo em memoria).
    $plain = $null
}

# --- Aplica mudancas ------------------------------------------------------

Save-EnvFile -Changes $Changes -WhatIf [bool]$WhatIf -EnvFile $EnvFile

# --- Confere o .env final (linhas relevantes) -----------------------------

if (-not $WhatIf) {
    Write-Host "`n=== .env apos edicao (apenas GATEWAY_TOKEN/LEITORES) ===" -ForegroundColor Cyan
    if (Test-Path $EnvFile) {
        Select-String -Path $EnvFile -Pattern '^(GATEWAY_TOKEN|LEITORES)=' | ForEach-Object { $_.Line }
    }
}

# --- Reinicia o servico ----------------------------------------------------

if ($WhatIf) {
    Write-Host "[WHATIF] nao reiniciei o servico." -ForegroundColor Magenta
    return
}

if ($NoRestart) {
    Write-Host "-NoRestart: lembre de reiniciar com 'nssm restart FaceGateGateway' antes de usar." -ForegroundColor Yellow
    return
}

$svc = Get-Service FaceGateGateway -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "Servico FaceGateGateway nao existe. Pule o restart (o gateway nao esta instalado como servico)." -ForegroundColor Yellow
    return
}

Write-Host "Reiniciando FaceGateGateway..." -ForegroundColor Cyan
nssm restart FaceGateGateway | Out-Null
Start-Sleep -Seconds 3
$svc.Refresh()
if ($svc.Status -eq 'Running') {
    Write-Host "Servico FaceGateGateway RUNNING." -ForegroundColor Green
    try {
        $h = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 5
        Write-Host "/health: $($h | ConvertTo-Json -Compress)" -ForegroundColor Green
    } catch {
        Write-Host "/health falhou: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Veja $($InstallDir)\logs\gateway.log" -ForegroundColor Red
    }
} else {
    Write-Host "Servico NAO subiu. Veja $($InstallDir)\logs\gateway.log" -ForegroundColor Red
    exit 1
}