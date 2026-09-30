"""Testes do HikvisionClient — captura as chamadas ISAPI sem terminal real.

Prova que a sequência de cadastro bate com a validada no DS-K1T672MX fw 3.18:
  1. POST /ISAPI/AccessControl/UserInfo/Record
  2. POST /ISAPI/Intelligent/FDLib/FaceDataRecord  (multipart FPID + img)
Remoção: PUT /ISAPI/AccessControl/UserInfo/Delete
"""
import json

import pytest

from app.hikvision_client import HikvisionClient

_OK = '{"statusCode":1,"statusString":"OK","subStatusCode":"ok"}'


def _make_client(recorder, responder):
    client = HikvisionClient(
        base_url="http://fake-hik:80",
        username="admin",
        password="x",
    )

    async def _fake_request(method, path, **kwargs):
        recorder.append({"method": method, "path": path, "kwargs": kwargs})
        return responder(method, path, **kwargs)

    client._request = _fake_request  # type: ignore[assignment]
    return client


@pytest.mark.asyncio
async def test_cadastrar_face_usa_sequencia_validada():
    calls: list[dict] = []
    client = _make_client(calls, lambda *a, **k: (200, _OK))

    ok, msg = await client.cadastrar_face("uuid-abc", b"\xff\xd8jpeg", name="Fulano")

    assert ok is True and msg == "ok"
    assert len(calls) == 2
    # Passo 1: cria o usuário
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/ISAPI/AccessControl/UserInfo/Record?format=json"
    user = calls[0]["kwargs"]["json"]["UserInfo"]
    assert user["employeeNo"] == "uuid-abc"
    assert user["name"] == "Fulano"
    assert user["RightPlan"][0]["doorNo"] == 1
    # Passo 2: envia a face amarrada ao employeeNo
    assert calls[1]["method"] == "POST"
    assert calls[1]["path"] == "/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json"
    files = calls[1]["kwargs"]["files"]
    assert "img" in files
    meta = json.loads(files["FaceDataRecord"][1])
    assert meta == {"faceLibType": "blackFD", "FDID": "1", "FPID": "uuid-abc"}


@pytest.mark.asyncio
async def test_cadastrar_face_idempotente_quando_user_ja_existe():
    calls: list[dict] = []
    already = '{"statusCode":6,"statusString":"Invalid Operation","subStatusCode":"employeeNoAlreadyExist"}'

    def responder(method, path, **kwargs):
        if "UserInfo/Record" in path:
            return (400, already)
        return (200, _OK)

    client = _make_client(calls, responder)
    ok, msg = await client.cadastrar_face("uuid-abc", b"\xff\xd8jpeg")

    # user já existente não aborta: segue e (re)envia a face
    assert ok is True and msg == "ok"
    assert calls[-1]["path"] == "/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json"


@pytest.mark.asyncio
async def test_cadastrar_face_falha_de_verdade_aborta():
    calls: list[dict] = []
    erro = '{"statusCode":4,"statusString":"Invalid Content","subStatusCode":"badParameters"}'
    client = _make_client(calls, lambda *a, **k: (400, erro))

    ok, msg = await client.cadastrar_face("uuid-abc", b"\xff\xd8jpeg")

    assert ok is False
    assert "UserInfo/Record" in msg
    assert len(calls) == 1  # não tenta a face se o user falhou


@pytest.mark.asyncio
async def test_remover_face_usa_userinfo_delete():
    calls: list[dict] = []
    client = _make_client(calls, lambda *a, **k: (200, _OK))

    ok, msg = await client.remover_face("uuid-abc")

    assert ok is True and msg == "ok"
    assert calls[0]["method"] == "PUT"
    assert calls[0]["path"] == "/ISAPI/AccessControl/UserInfo/Delete?format=json"
    cond = calls[0]["kwargs"]["json"]["UserInfoDelCond"]["EmployeeNoList"]
    assert cond == [{"employeeNo": "uuid-abc"}]


def test_to_employee_no_uuid_vira_hex_32():
    from app.hikvision_client import to_employee_no
    import uuid

    u = "3f2b8c1e-9a7d-4e21-b5c4-0d1e2f3a4b5c"
    emp = to_employee_no(u)
    assert emp == "3f2b8c1e9a7d4e21b5c40d1e2f3a4b5c"
    assert len(emp) == 32
    # o webhook do FaceGate lê de volta com uuid.UUID(...)
    assert str(uuid.UUID(emp)) == u


def test_to_employee_no_nao_uuid_passa_intacto():
    from app.hikvision_client import to_employee_no

    assert to_employee_no("900001") == "900001"
