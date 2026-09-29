"""Config via env vars. Pydantic-settings valida na importação."""
import secrets
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Auth ---
    gateway_token: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description="Token compartilhado com o FaceGate (header Authorization: Bearer)",
    )

    # --- Terminal ---
    hikvision_host: str = "10.5.50.161"
    hikvision_port: int = 443
    # Esquema HTTP usado pra falar com o terminal. Muitos terminais Hikvision
    # (DS-K1T3xx/6xx) atendem ISAPI em http:80 de fábrica, não https:443 — se
    # o terminal só responde em http, `https` dá erro de conexão. Deixe
    # `https` como default (fábrica costuma expor os dois) e troque pra `http`
    # quando o terminal só atende em texto claro. Ver `hikvision_base_url`.
    hikvision_scheme: str = "https"
    hikvision_user: str = "admin"
    hikvision_password: str = ""
    hikvision_fdid: str = "1"
    hikvision_face_lib_type: str = "blackFD"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    @property
    def hikvision_base_url(self) -> str:
        return f"{self.hikvision_scheme}://{self.hikvision_host}:{self.hikvision_port}"


settings = Settings()
