"""Cliente ISAPI standalone para terminais Hikvision.

Baseado no `isapi_base.py` do FaceGate, mas sem dependência do SQLAlchemy
ou do app.core. Esse módulo fala direto com o terminal via ISAPI.

**Sequência de cadastro VALIDADA no DS-K1T672MX firm 3.18 (loja real, 2026-09-30):**
  1. POST /ISAPI/AccessControl/UserInfo/Record?format=json    (cria o usuário/employeeNo)
  2. POST /ISAPI/Intelligent/FDLib/FaceDataRecord?format=json (multipart: parte JSON
     {faceLibType, FDID, FPID=employeeNo} + parte img) — amarra a face ao usuário.
Remoção: PUT /ISAPI/AccessControl/UserInfo/Delete?format=json (apaga usuário + face).

**Endpoints que ESTE firmware NÃO suporta (404/405) — não usar:**
- `/ISAPI/Intelligent/FDLib/FDSetUp` e `/FDSetUp/FaceDataRecord` — 404/405
- `/ISAPI/ContentMgmt/InputProxy/channels/1/face` — 404
- `/ISAPI/AccessControl/UserInfo/Search` — 404
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

    @staticmethod
    def _parse_status(body: str) -> tuple[bool, str, str]:
        """Interpreta a resposta JSON da ISAPI. Retorna (ok, statusString, subStatusCode)."""
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return False, body[:200], ""
        status_string = str(data.get("statusString", ""))
        sub = str(data.get("subStatusCode", ""))
        ok = data.get("statusCode") == 1 or status_string.upper() == "OK"
        return ok, status_string, sub

    async def cadastrar_face(
        self, person_id: str, foto_bytes: bytes, name: str | None = None
    ) -> tuple[bool, str]:
        """Cadastra usuário + face no terminal. Retorna (sucesso, mensagem).

        Sequência validada no DS-K1T672MX fw 3.18 (loja real, 2026-09-30):
          1. POST UserInfo/Record  — cria o usuário de controle de acesso (employeeNo).
          2. POST FaceDataRecord   — envia a foto e amarra ao employeeNo (FPID).
        `person_id` (UUID do FaceGate) é usado como employeeNo/FPID, mantendo o
        mapeamento com os eventos de acesso que voltam pelo webhook.
        """
        if len(foto_bytes) > _MAX_FOTO_BYTES:
            return False, f"Foto excede {_MAX_FOTO_BYTES} bytes ({len(foto_bytes)})."

        employee_no = person_id
        nome = name or person_id

        # Passo 1: cria o usuário de controle de acesso.
        user_body = {
            "UserInfo": {
                "employeeNo": employee_no,
                "name": nome,
                "userType": "normal",
                "Valid": {
                    "enable": True,
                    "beginTime": "2024-01-01T00:00:00",
                    "endTime": "2037-12-31T23:59:59",
                },
                "doorRight": "1",
                "RightPlan": [{"doorNo": 1, "planTemplateNo": "1"}],
            }
        }
        try:
            sc, body = await self._request(
                "POST",
                "/ISAPI/AccessControl/UserInfo/Record?format=json",
                json=user_body,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            return False, f"UserInfo/Record erro: {type(exc).__name__}: {exc}"

        ok, status_string, sub = self._parse_status(body)
        # employeeNoAlreadyExist é idempotente — seguimos pra (re)enviar a face.
        if not ok and sub != "employeeNoAlreadyExist":
            logger.warning("UserInfo/Record user=%s: HTTP %s — %s", person_id, sc, body[:200])
            return False, f"UserInfo/Record falhou (HTTP {sc}): {status_string or sub}"
        logger.info("UserInfo/Record user=%s: %s", person_id, status_string or sub or "OK")

        # Passo 2: envia a face e amarra ao employeeNo via FaceDataRecord (multipart).
        face_meta = {
            "faceLibType": self._face_lib_type,
            "FDID": self._fdid,
            "FPID": employee_no,
        }
        try:
            sc, body = await self._request(
                "POST",
                "/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json",
                files={
                    "FaceDataRecord": (None, json.dumps(face_meta), "application/json"),
                    "img": ("face.jpg", foto_bytes, "image/jpeg"),
                },
            )
        except httpx.HTTPError as exc:
            return False, f"FaceDataRecord erro: {type(exc).__name__}: {exc}"

        ok, status_string, sub = self._parse_status(body)
        if not ok:
            logger.warning("FaceDataRecord user=%s: HTTP %s — %s", person_id, sc, body[:200])
            return False, f"FaceDataRecord falhou (HTTP {sc}): {status_string or sub}"
        logger.info("FaceDataRecord user=%s: OK", person_id)
        return True, "ok"

    async def remover_face(self, person_id: str) -> tuple[bool, str]:
        """Remove o usuário (e a face junto) via UserInfo/Delete. Idempotente."""
        try:
            sc, body = await self._request(
                "PUT",
                "/ISAPI/AccessControl/UserInfo/Delete?format=json",
                json={"UserInfoDelCond": {"EmployeeNoList": [{"employeeNo": person_id}]}},
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            return False, f"UserInfo/Delete erro: {type(exc).__name__}: {exc}"

        ok, status_string, sub = self._parse_status(body)
        if ok or sc == 404:  # 404 = já não existia, idempotente
            return True, "ok"
        return False, f"UserInfo/Delete falhou (HTTP {sc}): {status_string or sub}"

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
