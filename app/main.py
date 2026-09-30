"""FaceGate Gateway — entrada FastAPI."""
import base64
import logging
import sys
from typing import Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_token
from app.config import LeitorConfig, settings
from app.hikvision_client import HikvisionClient

# --- Logging ---
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("gateway")

# --- FastAPI ---
app = FastAPI(
    title="FaceGate Gateway",
    version="0.1.0",
    description="Agente local — traduz REST do FaceGate pra ISAPI do terminal.",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


def _client_de(leitor: LeitorConfig) -> HikvisionClient:
    """Instancia um cliente por request. Stateless, sem pool."""
    return HikvisionClient(
        base_url=leitor.base_url,
        username=leitor.user,
        password=leitor.password,
        fdid=leitor.fdid,
        face_lib_type=leitor.face_lib_type,
    )


def _client_padrao() -> HikvisionClient:
    """Rotas `/hikvision/...`: o terminal das vars `HIKVISION_*`."""
    return _client_de(settings.leitor_padrao)


def _client_do_leitor(leitor: str) -> HikvisionClient:
    """Rotas `/leitores/{leitor}/hikvision/...`: um terminal de `LEITORES`."""
    config = settings.leitores.get(leitor)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Leitor {leitor!r} não configurado neste gateway.",
        )
    return _client_de(config)


# ---------- Endpoints públicos (sem auth) ----------


@app.get("/health")
async def health() -> dict:
    """Health check — usado pelo Docker HEALTHCHECK e pelo FaceGate pra detectar gateway offline."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "hikvision_host": settings.hikvision_host,
        "leitores": sorted(settings.leitores),
    }


# ---------- Schemas ----------


class CadastrarFaceRequest(BaseModel):
    person_id: str = Field(..., description="UUID do user (do FaceGate)")
    foto_base64: str = Field(..., description="Selfie em base64 (JPEG/PNG)")
    name: str | None = Field(default=None, description="Nome do user (opcional)")


class CadastrarFaceResponse(BaseModel):
    success: bool
    detail: str


# ---------- Endpoints autenticados ----------


def _rotas_hikvision(client_dep: Callable[..., HikvisionClient]) -> APIRouter:
    """As rotas do terminal, ligadas a um jeito de achar o cliente.

    Montadas duas vezes: em `/hikvision` (terminal das vars `HIKVISION_*`)
    e em `/leitores/{leitor}/hikvision` (um terminal de `LEITORES`).
    """
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.post("/cadastrar-face", response_model=CadastrarFaceResponse)
    async def cadastrar_face(
        body: CadastrarFaceRequest,
        client: HikvisionClient = Depends(client_dep),
    ) -> CadastrarFaceResponse:
        """Cadastra face de um user no terminal Hikvision.

        1. Recebe foto em base64
        2. Chama `FDSetUp` (cria personID)
        3. Chama `PUT /FaceDataRecord` (multipart com a foto)

        Em firmwares limitados (DS-K1T672MX 3.18), pode falhar com
        HTTP 404/405 — o caller (FaceGate) decide se vale tentar UI manual.
        """
        try:
            foto_bytes = base64.b64decode(body.foto_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"foto_base64 inválido: {exc}",
            )

        ok, msg = await client.cadastrar_face(
            person_id=body.person_id, foto_bytes=foto_bytes, name=body.name
        )
        if not ok:
            # Erro "esperado" (firmware limitado) → 422 (Unprocessable Entity)
            # Outros erros → 502 (Bad Gateway — falhou falando com a Hik)
            if "firmware" in msg.lower() or "404" in msg or "405" in msg:
                return CadastrarFaceResponse(success=False, detail=msg)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=msg,
            )
        return CadastrarFaceResponse(success=True, detail="ok")

    @router.delete("/face/{person_id}")
    async def remover_face(
        person_id: str, client: HikvisionClient = Depends(client_dep)
    ) -> dict:
        """Remove a face de um personID do terminal."""
        ok, msg = await client.remover_face(person_id=person_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=msg
            )
        return {"success": True, "detail": "ok"}

    @router.get("/status")
    async def status_terminal(client: HikvisionClient = Depends(client_dep)) -> dict:
        """Sonda `deviceInfo` do terminal. Útil pra diagnóstico."""
        return await client.status()

    @router.get("/fdids")
    async def listar_fdids(client: HikvisionClient = Depends(client_dep)) -> dict:
        """Lista as Face Database IDs configuradas no terminal."""
        libs = await client.listar_fdids()
        return {"fdids": libs, "count": len(libs)}

    return router


app.include_router(_rotas_hikvision(_client_padrao), prefix="/hikvision")
app.include_router(
    _rotas_hikvision(_client_do_leitor), prefix="/leitores/{leitor}/hikvision"
)


# ---------- Error handler padronizado ----------


@app.exception_handler(Exception)
async def _unhandled_exception(_, exc: Exception) -> JSONResponse:
    logger.exception("Erro não tratado: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )
