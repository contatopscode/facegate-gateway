"""Cliente ISAPI standalone para terminais Hikvision.

Baseado no `isapi_base.py` do FaceGate, mas sem dependência do SQLAlchemy
ou do app.core. Esse módulo fala direto com o terminal via ISAPI.

**Endpoints que o DS-K1T672MX firm 3.18 SUPORTA:**
- `/ISAPI/Event/notification/httpHosts` (webhook) — funciona
- `/ISAPI/Streaming/channels/101` (camera) — funciona
- `/ISAPI/System/deviceInfo` — funciona
- `/ISAPI/System/capabilities` — funciona
- `/ISAPI/Intelligent/FDLib` (FDSetUp config) — funciona (com bug do 2 ids)

**Endpoints que NÃO SUPORTA (404/405):**
- `/ISAPI/Intelligent/FDLib/FDSetUp` — 404
- `/ISAPI/Intelligent/FDLib/FDSetUp/FaceDataRecord` — 405
- `/ISAPI/ContentMgmt/InputProxy/channels/1/face` — 404
- `/ISAPI/AccessControl/UserInfo/Search` — 404
- `/ISAPI/AccessControl/RemoteControl/door/{n}` — 404
"""
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Limite da Hikvision pra foto: ~200KB
_MAX_FOTO_BYTES = 5 * 1024 * 1024

DEFAULT_TIMEOUT = httpx.Timeout(20.0, read=20.0)


class HikvisionClient:
    """Wrapper ISAPI minimal. Stateless — instancia por request."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        fdid: str = "1",
        face_lib_type: str = "blackFD",
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.DigestAuth(username, password)
        self._fdid = fdid
        self._face_lib_type = face_lib_type
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, str]:
        try:
            # verify=False: terminais Hik/Intelbras vêm com cert self-signed de fábrica.
            # Hardware em rede privada — MITM não é vetor realista.
            # (mesma decisão do FaceGate backend: isapi_base.py)
            async with httpx.AsyncClient(
                auth=self._auth, timeout=self._timeout, verify=False
            ) as client:
                resp = await client.request(method, self._url(path), **kwargs)
                return resp.status_code, resp.text
        except httpx.HTTPError as exc:
            logger.error("%s %s falhou: %s: %s", method, path, type(exc).__name__, exc)
            raise

    # ---------- Endpoints úteis ----------

    async def cadastrar_face(
        self, person_id: str, foto_bytes: bytes, name: str | None = None
    ) -> tuple[bool, str]:
        """Tenta cadastrar face. Retorna (sucesso, mensagem).

        Em firmwares 3.x limitados (DS-K1T672MX), pode dar 404 no FDSetUp
        e 405 no FaceDataRecord. A gente trata como falha e o caller decide
        se vale tentar UI manual como fallback.
        """
        if len(foto_bytes) > _MAX_FOTO_BYTES:
            return False, f"Foto excede {_MAX_FOTO_BYTES} bytes ({len(foto_bytes)})."

        # Passo 1: FDSetUp (cria/atualiza personID)
        try:
            fdsetup_body = {
                "faceLibType": self._face_lib_type,
                "FDID": self._fdid,
                "faceURL": "",
                "personID": person_id,
            }
            if name:
                fdsetup_body["name"] = name

            sc, body = await self._request(
                "POST",
                "/ISAPI/Intelligent/FDLib/FDSetUp?format=json",
                json=fdsetup_body,
                headers={"Content-Type": "application/json"},
            )
            if sc not in (200, 201):
                # 404/405 = firmware limitado
                if sc in (404, 405):
                    return False, f"Firmware não suporta FDSetUp (HTTP {sc})"
                logger.warning("FDSetUp user=%s: HTTP %s — %s", person_id, sc, body[:200])
                return False, f"FDSetUp falhou: HTTP {sc}"
            logger.info("FDSetUp user=%s: OK", person_id)
        except httpx.HTTPError as exc:
            return False, f"FDSetUp erro: {type(exc).__name__}: {exc}"

        # Passo 2: PUT da foto (multipart)
        try:
            metadata = {"FaceDataRecord": {"personID": person_id}}
            if name:
                metadata["FaceDataRecord"]["name"] = name

            sc, body = await self._request(
                "PUT",
                "/ISAPI/Intelligent/FDLib/FDSetUp/FaceDataRecord?format=json",
                files={"faceImage": ("face.jpg", foto_bytes, "image/jpeg")},
                data={
                    "FDID": self._fdid,
                    "faceLibType": self._face_lib_type,
                    "FaceDataRecord": json.dumps(metadata),
                },
            )
            if sc not in (200, 201):
                if sc in (404, 405):
                    return False, f"Firmware não suporta upload de foto (HTTP {sc})"
                logger.warning("PUT foto user=%s: HTTP %s — %s", person_id, sc, body[:200])
                return False, f"PUT foto falhou: HTTP {sc}"
            logger.info("PUT foto user=%s: OK", person_id)
            return True, "ok"
        except httpx.HTTPError as exc:
            return False, f"PUT foto erro: {type(exc).__name__}: {exc}"

    async def remover_face(self, person_id: str) -> tuple[bool, str]:
        try:
            sc, body = await self._request(
                "DELETE",
                "/ISAPI/Intelligent/FDLib/FDSetUp/FaceDataRecord",
                params={
                    "FDID": self._fdid,
                    "faceLibType": self._face_lib_type,
                    "personID": person_id,
                    "format": "json",
                },
            )
            if sc in (200, 204, 404):  # 404 = já não existia, idempotente
                return True, "ok"
            return False, f"DELETE falhou: HTTP {sc}"
        except httpx.HTTPError as exc:
            return False, f"DELETE erro: {type(exc).__name__}: {exc}"

    async def status(self) -> dict:
        """Sonda `deviceInfo`. Retorna dict com modelo, firmware, online status."""
        try:
            sc, body = await self._request(
                "GET", "/ISAPI/System/deviceInfo?format=json"
            )
            if sc == 200:
                data = json.loads(body)
                info = data.get("DeviceInfo", {})
                return {
                    "online": True,
                    "modelo": info.get("model", ""),
                    "firmware": info.get("firmwareVersion", ""),
                    "serial": info.get("serialNumber", ""),
                    "mac": info.get("macAddress", ""),
                }
            return {"online": False, "erro": f"deviceInfo HTTP {sc}"}
        except httpx.HTTPError as exc:
            return {"online": False, "erro": f"{type(exc).__name__}: {exc}"}

    async def listar_fdids(self) -> list[dict]:
        """Lista as Face Database IDs configuradas. Útil pra diagnóstico."""
        try:
            sc, body = await self._request("GET", "/ISAPI/Intelligent/FDLib?format=json")
            if sc != 200:
                return []
            data = json.loads(body)
            libs = data.get("FDLib", [])
            if isinstance(libs, dict):
                libs = [libs]
            return [
                {
                    "FDID": lib.get("FDID"),
                    "faceLibType": lib.get("faceLibType"),
                    "name": lib.get("name", ""),
                }
                for lib in libs
            ]
        except httpx.HTTPError:
            return []
