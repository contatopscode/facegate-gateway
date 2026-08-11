"""FaceGate Gateway — entrada FastAPI."""
import base64
import logging
import sys

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_token
from app.config import settings
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


def _client() -> HikvisionClient:
    """Instancia um cliente por request. Stateless, sem pool."""
    return HikvisionClient(
        base_url=settings.hikvision_base_url,
        username=settings.hikvision_user,
        password=settings.hikvision_password,
        fdid=settings.hikvision_fdid,
        face_lib_type=settings.hikvision_face_lib_type,
    )


# ---------- Endpoints públicos (sem auth) ----------


@app.get("/health")
async def health() -> dict:
    """Health check — usado pelo Docker HEALTHCHECK e pelo FaceGate pra detectar gateway offline."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "hikvision_host": settings.hikvision_host,
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


@app.post(
    "/hikvision/cadastrar-face",
    response_model=CadastrarFaceResponse,
    dependencies=[Depends(require_token)],
)
async def cadastrar_face(body: CadastrarFaceRequest) -> CadastrarFaceResponse:
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

    client = _client()
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


@app.delete(
    "/hikvision/face/{person_id}",
    dependencies=[Depends(require_token)],
)
async def remover_face(person_id: str) -> dict:
    """Remove a face de um personID do terminal."""
    client = _client()
    ok, msg = await client.remover_face(person_id=person_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=msg
        )
    return {"success": True, "detail": "ok"}


@app.get(
    "/hikvision/status",
    dependencies=[Depends(require_token)],
)
async def status_terminal() -> dict:
    """Sonda `deviceInfo` do terminal. Útil pra diagnóstico."""
    client = _client()
    return await client.status()


@app.get(
    "/hikvision/fdids",
    dependencies=[Depends(require_token)],
)
async def listar_fdids() -> dict:
    """Lista as Face Database IDs configuradas no terminal."""
    client = _client()
    libs = await client.listar_fdids()
    return {"fdids": libs, "count": len(libs)}


# ---------- Error handler padronizado ----------


@app.exception_handler(Exception)
async def _unhandled_exception(_, exc: Exception) -> JSONResponse:
    logger.exception("Erro não tratado: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )
