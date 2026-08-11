"""Fixtures: cliente de teste + mock server (Hikvision fake) in-process."""
import base64

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def _override_settings(monkeypatch):
    """Garante token previsível pra testes e desabilita chamadas reais."""
    monkeypatch.setattr(settings, "gateway_token", "test-token-1234")
    monkeypatch.setattr(settings, "hikvision_host", "fake-hikvision")
    monkeypatch.setattr(settings, "hikvision_password", "test-pass")
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_header() -> dict:
    return {"Authorization": "Bearer test-token-1234"}


@pytest.fixture
def fake_jpeg_b64() -> str:
    """Mínimo JPEG válido (1x1 pixel, ~125 bytes)."""
    jpeg_bytes = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605"
        "080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e272022"
        "2c231c1c2837292c30313434341f27393d38323c2e333432ffc2000b08000100010101"
        "1100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc4"
        "00b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f0000010501010101010100000000000000000102030405060708090a0b"
        "ffda0008010100003f00d2cf20ffd9"
    )
    return base64.b64encode(jpeg_bytes).decode()
