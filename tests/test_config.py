"""Testes da montagem da base_url do terminal (esquema/porta configuráveis)."""
from app.config import Settings


def test_base_url_default_https():
    s = Settings(hikvision_host="10.0.0.9", hikvision_port=443)
    assert s.hikvision_base_url == "https://10.0.0.9:443"


def test_base_url_http_para_terminal_texto_claro():
    """Terminal que só atende em http:80 (comum em DS-K1T3xx/6xx de fábrica)."""
    s = Settings(
        hikvision_host="192.168.15.122",
        hikvision_port=80,
        hikvision_scheme="http",
    )
    assert s.hikvision_base_url == "http://192.168.15.122:80"
