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
        return f"https://{self.hikvision_host}:{self.hikvision_port}"


settings = Settings()
