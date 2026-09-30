"""Vários terminais num gateway só: `/leitores/{leitor}/hikvision/...`."""
import pytest
from pydantic import ValidationError

from app.config import LeitorConfig, Settings, settings
from app.hikvision_client import HikvisionClient


@pytest.fixture
def dois_leitores(monkeypatch):
    monkeypatch.setattr(
        settings,
        "leitores",
        {
            "bancada": LeitorConfig(host="10.5.50.155", port=80, scheme="http", password="a"),
            "lavanderia": LeitorConfig(host="10.5.50.161", password="b"),
        },
    )


@pytest.fixture
def status_eco(monkeypatch):
    """`status()` devolve a base_url do cliente, sem falar com terminal."""

    async def _status(self):
        return {"online": True, "base_url": self._base_url}

    monkeypatch.setattr(HikvisionClient, "status", _status)


def test_cada_leitor_fala_com_o_seu_terminal(client, auth_header, dois_leitores, status_eco):
    r1 = client.get("/leitores/bancada/hikvision/status", headers=auth_header)
    r2 = client.get("/leitores/lavanderia/hikvision/status", headers=auth_header)
    assert r1.json()["base_url"] == "http://10.5.50.155:80"
    assert r2.json()["base_url"] == "https://10.5.50.161:443"


def test_rota_antiga_segue_no_terminal_padrao(client, auth_header, dois_leitores, status_eco):
    r = client.get("/hikvision/status", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["base_url"] == settings.hikvision_base_url


def test_leitor_desconhecido_404(client, auth_header, dois_leitores):
    r = client.get("/leitores/garagem/hikvision/status", headers=auth_header)
    assert r.status_code == 404
    assert "garagem" in r.json()["detail"]


def test_leitor_sem_token_401_antes_do_404(client, dois_leitores):
    """Sem token não dá pra descobrir quais leitores existem."""
    assert client.get("/leitores/garagem/hikvision/status").status_code == 401
    assert client.delete("/leitores/bancada/hikvision/face/abc").status_code == 401


def test_cadastro_no_leitor_usa_as_credenciais_dele(
    client, auth_header, dois_leitores, fake_jpeg_b64, monkeypatch
):
    vistos = []

    async def _cadastrar(self, person_id, foto_bytes, name=None):
        vistos.append((self._base_url, person_id))
        return True, "ok"

    monkeypatch.setattr(HikvisionClient, "cadastrar_face", _cadastrar)
    r = client.post(
        "/leitores/lavanderia/hikvision/cadastrar-face",
        headers=auth_header,
        json={"person_id": "abc-123", "foto_base64": fake_jpeg_b64},
    )
    assert r.status_code == 200 and r.json()["success"] is True
    assert vistos == [("https://10.5.50.161:443", "abc-123")]


def test_health_lista_os_leitores(client, dois_leitores):
    assert client.get("/health").json()["leitores"] == ["bancada", "lavanderia"]


def test_leitores_vem_do_env_em_json(monkeypatch):
    monkeypatch.setenv(
        "LEITORES",
        '{"lavanderia": {"host": "10.5.50.161", "port": 80, "scheme": "http", "password": "x"}}',
    )
    s = Settings(_env_file=None)
    assert s.leitores["lavanderia"].base_url == "http://10.5.50.161:80"
    assert s.leitores["lavanderia"].user == "admin"


def test_nome_de_leitor_invalido_recusado():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, leitores={"Lavanderia 1": {"host": "x"}})
