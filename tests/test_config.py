"""Testes da montagem da base_url do terminal (esquema/porta configuráveis)."""
import pytest
from pydantic import ValidationError

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


# --- PSCODE-FG-FSW-2026-015: fail-fast no token placeholder ---


def test_gateway_token_rejeita_placeholder_do_env_example():
    """O placeholder do .env.example NÃO pode subir. Foi a causa raiz do
    incidente PSCODE-FG-FSW-2026-015 (gateway na .188 aceitava o token
    placeholder vindo direto do template, sem o operador ter editado)."""
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(gateway_token="troque-por-um-token-aleatorio-32-chars")


def test_gateway_token_rejeita_changeme_e_variants():
    """Outros placeholders comuns em templates também devem falhar."""
    for placeholder in ("changeme", "changeme-please", "example", "your-token-here"):
        with pytest.raises(ValidationError):
            Settings(gateway_token=placeholder)


def test_gateway_token_rejeita_vazio():
    with pytest.raises(ValidationError, match="vazio"):
        Settings(gateway_token="")


def test_gateway_token_rejeita_spaces_only():
    with pytest.raises(ValidationError, match="vazio"):
        Settings(gateway_token="   ")


def test_gateway_token_rejeita_curto():
    """Tokens menores que 24 chars são quase certo placeholder ou erro."""
    with pytest.raises(ValidationError, match="curto"):
        Settings(gateway_token="abc")


def test_gateway_token_aceita_token_real():
    """Tokens válidos (formato que python -c 'secrets.token_urlsafe(32)' gera)
    passam pelo validator e são preservados sem strip se não houver whitespace."""
    real = "p2TaK2-ulpIQ28uEwvRNdVEGWE6J-qjWTMeapEk0n9o"
    s = Settings(gateway_token=real)
    assert s.gateway_token == real


def test_gateway_token_remove_whitespace():
    """Token com whitespace nas pontas é limpo (facilita copia/cola)."""
    real = "p2TaK2-ulpIQ28uEwvRNdVEGWE6J-qjWTMeapEk0n9o"
    s = Settings(gateway_token=f"  {real}\n")
    assert s.gateway_token == real
