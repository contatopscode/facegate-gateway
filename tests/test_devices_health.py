"""Testes do endpoint /api/devices/_health (PSCODE-FG-FSW-2026-015).

Sem auth (igual /health). Diagnóstico remoto — bate do notebook em
`https://gw-predio.pscode.ia.br/api/devices/_health` e vê status
agregado de cada leitor sem precisar entrar na máquina Windows.
"""
import json


def test_devices_health_sem_auth_200(client):
    """Endpoint público (sem token), igual /health."""
    r = client.get("/api/devices/_health")
    assert r.status_code == 200
    body = r.json()
    assert body["gateway"] == "ok"
    assert "version" in body
    assert "padrao" in body
    assert "leitores" in body
    # payload inteiro deve ser JSON serializável
    json.dumps(body)


def test_devices_health_nao_expoe_credenciais(client):
    """NUNCA expor user/password/token pela internet, mesmo com bug no cliente."""
    r = client.get("/api/devices/_health")
    assert r.status_code == 200
    body_str = r.text
    forbidden = ("password", "admin", "test-pass")
    for word in forbidden:
        assert word not in body_str, (
            f"/api/devices/_health NÃO deve expor '{word}' (response: {body_str})"
        )


def test_devices_health_padrao_tem_host(client):
    """Resposta do leitor padrão inclui o host (pra Paulo saber qual IP caiu)."""
    r = client.get("/api/devices/_health")
    body = r.json()
    assert "host" in body["padrao"]
    # host configurado pelo conftest: "fake-hikvision" (não responde de verdade)
    assert body["padrao"]["host"] == "fake-hikvision"
    # como fake-hikvision não resolve, esperamos online=False com erro
    assert body["padrao"]["online"] is False


def test_devices_health_leitores_dict_vazio(client):
    """Se LEITORES= vazio (default de conftest), `leitores` no payload é dict vazio."""
    r = client.get("/api/devices/_health")
    body = r.json()
    assert body["leitores"] == {}