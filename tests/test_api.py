"""Testes dos endpoints HTTP — usa TestClient sem precisar de Hik real."""
import pytest


def test_health_nao_requer_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_cadastrar_face_sem_auth_401(client, fake_jpeg_b64):
    r = client.post(
        "/hikvision/cadastrar-face",
        json={"person_id": "abc-123", "foto_base64": fake_jpeg_b64},
    )
    assert r.status_code == 401
    assert "Bearer" in r.headers.get("www-authenticate", "")


def test_cadastrar_face_com_auth_mas_sem_hik_real(client, auth_header, fake_jpeg_b64):
    """Sem mock server, vai dar erro de conexão. Esperamos 502 (gateway error)."""
    r = client.post(
        "/hikvision/cadastrar-face",
        headers=auth_header,
        json={"person_id": "abc-123", "foto_base64": fake_jpeg_b64, "name": "Test"},
    )
    # 502 = falou com a Hik mas falhou (não conseguiu conectar pq é fake)
    assert r.status_code in (502, 500)


def test_cadastrar_face_foto_invalida(client, auth_header):
    r = client.post(
        "/hikvision/cadastrar-face",
        headers=auth_header,
        json={"person_id": "abc-123", "foto_base64": "não-é-base64!"},
    )
    assert r.status_code == 400
    assert "foto_base64" in r.json()["detail"]


def test_status_terminal_sem_auth_401(client):
    r = client.get("/hikvision/status")
    assert r.status_code == 401


def test_remover_face_sem_auth_401(client):
    r = client.delete("/hikvision/face/abc-123")
    assert r.status_code == 401


def test_token_errado_401(client, fake_jpeg_b64):
    r = client.post(
        "/hikvision/cadastrar-face",
        headers={"Authorization": "Bearer token-errado"},
        json={"person_id": "abc", "foto_base64": fake_jpeg_b64},
    )
    assert r.status_code == 401


def test_token_nao_ascii_401_nao_500(client):
    r = client.get("/hikvision/status", headers={"Authorization": "Bearer tökén".encode()})
    assert r.status_code == 401
