# FaceGate Gateway

Agente local que fica na **rede do cliente** (mesma rede dos terminais Hikvision/Intelbras)
e traduz as chamadas REST/HTTPS do **FaceGate backend** (na VPS) pra ISAPI dos equipamentos.

```
[FaceGate backend - VPS]                [Cliente - lavanderia]
+---------------------+                 +----------------------+
|                     |   HTTPS + token |   Gateway            |
|   Driver Gateway →  | ───────────────→|   (Python/FastAPI)   |
|                     |                 |          ↓           |
+---------------------+                 |   ISAPI Hikvision    |
                                        +----------------------+
```

**Por que precisa?** O DS-K1T672MX (e vários terminais "mini" da Hikvision) tem firmware
limitado que **não expõe** os endpoints ISAPI de gestão de face/user. A única forma
de cadastrar/gerenciar é via UI local. O gateway é a **ponte** entre o backend (que
não alcança a rede local) e o terminal (que aceita só ISAPI local).

## Endpoints (v0.1)

| Método | Path | Descrição |
|---|---|---|
| `GET`  | `/health` | Health check (sem auth) |
| `POST` | `/hikvision/cadastrar-face` | Cadastra face de um user (FDSetUp + PUT foto) |
| `DELETE` | `/hikvision/face/{person_id}` | Remove face do terminal |
| `GET`  | `/hikvision/status` | Sonda `deviceInfo` |
| `POST` | `/hikvision/abrir-porta` | Pulso no relé |

Todos (exceto `/health`) requerem header `Authorization: Bearer <GATEWAY_TOKEN>`.

## Setup rápido (Linux/Raspberry)

```bash
git clone https://github.com/contatopscode/facegate-gateway.git
cd facegate-gateway
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# editar .env com GATEWAY_TOKEN, IP do terminal Hikvision, user/senha
python -m app.main
```

## Setup (Windows)

```bat
git clone https://github.com/contatopscode/facegate-gateway.git
cd facegate-gateway
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
:: editar .env no Notepad
python -m app.main
```

## Docker (qualquer plataforma)

```bash
docker build -t facegate-gateway .
docker run -d --name facegate-gateway --restart=unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  facegate-gateway
```

## Cloudflare Tunnel (recomendado pra produção)

```bash
# Instalar cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
cloudflared tunnel --url http://localhost:8000
# Copiar a URL *.trycloudflare.com e colocar no .env do FaceGate:
#   GATEWAY_URL=https://facegate-gateway-abc.trycloudflare.com
```

Pra URL fixa (recomendado), criar tunnel nomeado com `cloudflared tunnel login` + `cloudflared tunnel create facegate-gateway`.

## Variáveis de ambiente

| Var | Default | Descrição |
|---|---|---|
| `GATEWAY_TOKEN` | (obrigatório) | Token compartilhado com o FaceGate (via header Bearer) |
| `HIKVISION_HOST` | (obrigatório) | IP do terminal (ex: `10.5.50.161`) |
| `HIKVISION_USER` | `admin` | Usuário ISAPI |
| `HIKVISION_PASSWORD` | (obrigatório) | Senha ISAPI |
| `HIKVISION_FDID` | `1` | Face Database ID (default `1`) |
| `HIKVISION_FACE_LIB_TYPE` | `blackFD` | Tipo da lib (`blackFD` = quem tem acesso) |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |

## Arquitetura

- **Stack:** Python 3.11+ / FastAPI / httpx / uvicorn
- **Storage:** stateless (config via env, fotos recebidas on-the-fly)
- **Log:** stdout em JSON (coletado por journalctl ou Docker logs)
- **Auto-restart:** systemd (Linux) / Docker restart policy / NSSM (Windows)

## Testes

```bash
pytest tests/ -v
```

Usa o **TinyFakeHik** (in-process) do FaceGate pra simular hardware real sem precisar de equipamento.

## Limitações conhecidas

- DS-K1T672MX firm 3.18: aceita face, mas `RemoteControl/door/{n}` retorna 404 (firmware limitado, sem abertura de porta via ISAPI)
- Hikvision aceita foto até ~200KB; o gateway valida antes do upload
- Não implementa pull de eventos (Sprint 7); por ora recebe só webhook da Hik → FaceGate

## Roadmap

- [x] v0.1: endpoints básicos + ISAPI + auth
- [x] v0.2: testes com TinyFakeHik
- [ ] v0.3: suporte a Intelbras (ISAPI comum)
- [ ] v0.4: pull de eventos (AcsEvent)
- [ ] v0.5: proxy RTSP pra streaming
