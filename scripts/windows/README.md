# Scripts Windows do FaceGate Gateway

Scripts PowerShell pra instalar e manter o gateway numa máquina Windows.
Rode **como Administrador** (PowerShell → Executar como administrador).

## install.ps1 — instala tudo de uma vez

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1                      # pede o token do tunel sem ecoar
.\install.ps1 -Ref abc1234         # instala exatamente o commit revisado
.\install.ps1 -InstallDir D:\Apps\FaceGate\gateway
```

Faz: winget (git, nssm, cloudflared, Python 3.12) → clona/atualiza o repo →
cria `.venv` → cria `.env` a partir do `.env.example` (abre no Notepad) →
instala o serviço `FaceGateGateway` via NSSM → instala o cloudflared → confere `/health`.

## token-replace.ps1 — troca token/leitor sem abrir Bloco de Notas

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\token-replace.ps1 -Token "p2TaK2-ulpIQ28uEwvRNdVEGWE6J-qjWTMeapEk0n9o"
```

Substitui `GATEWAY_TOKEN` no `.env`, opcionalmente adiciona/atualiza um leitor
no JSON `LEITORES`, e reinicia o serviço pra recarregar as settings
(o `auth.py` carrega o token no boot, sem hot-reload).

Idempotente: rodar várias vezes não duplica linha nem sobrescreve
comentários do `.env`.

### Trocar token E adicionar leitor novo (mesma chamada)

```powershell
$pw = Read-Host "Senha do admin do leitor .161" -AsSecureString
.\token-replace.ps1 `
    -Token "p2TaK2-ulpIQ28uEwvRNdVEGWE6J-qjWTMeapEk0n9o" `
    -Leitor prelo-predio `
    -Host 10.5.50.161 `
    -Port 80 `
    -Scheme http `
    -Password $pw
```

### Gerar token novo (rotacao)

```powershell
.\token-replace.ps1 -Rollout
```

Gera um token novo (`secrets.token_urlsafe(32)`) e grava. O backend
FaceGate vai precisar ser atualizado com o mesmo valor.

### Simular antes de aplicar

```powershell
.\token-replace.ps1 -Token "novo-token-aqui" -WhatIf
```

Mostra o que mudaria sem gravar nem reiniciar nada. Use para revisar
antes de aplicar em produção.

### Trocar sem reiniciar (aplica varias mudancas, reinicia 1x no fim)

```powershell
.\token-replace.ps1 -Token "..." -NoRestart
.\token-replace.ps1 -Leitor bancada -Host 10.0.0.20 -Port 80 -Scheme http -Password (Read-Host -AsSecureString) -NoRestart
nssm restart FaceGateGateway
```

## Por que este script existe

PSCODE-FG-FSW-2026-015 (2026-10-06): o gateway na máquina `.188`
subiu com `GATEWAY_TOKEN=troque-por-um-token-aleatorio-32-chars` (o
placeholder do `.env.example`) porque o instalador só **abre o .env no
Notepad** — não substitui o placeholder. Resultado: qualquer pessoa
que lesse o README conseguia falar com o gateway pelo túnel.

Mitigações aplicadas (em ordem):

1. **`install.ps1`**: ainda abre o Notepad, mas este script existe pra
   um técnico remoto (AnyDesk / RDP) trocar o token sem GUI.
2. **`token-replace.ps1 -Rollout`**: gera token novo, evita typo de
   copia-cola.
3. **PR `feat(robustness): fail-fast no startup se GATEWAY_TOKEN
   placeholder/vazio`**: o gateway agora **não sobe** se o token for
   placeholder, vazio, ou < 24 chars. Se alguém esquecer de editar o
   `.env`, o serviço fica em `STOPPED` com mensagem clara no log.

Se você rodar `token-replace.ps1` num gateway com a versão antiga do
gateway (pré-fail-fast), o gateway aceita o novo token normalmente —
o script e o validator são compatíveis com versões anteriores.