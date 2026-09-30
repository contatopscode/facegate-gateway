"""Config via env vars. Pydantic-settings valida na importação."""
import re
import secrets

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_NOME_LEITOR = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class LeitorConfig(BaseModel):
    """Um terminal da LAN. Defaults iguais aos das vars `HIKVISION_*`."""

    host: str
    port: int = 443
    scheme: str = "https"
    user: str = "admin"
    password: str = ""
    fdid: str = "1"
    face_lib_type: str = "blackFD"

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


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

    # --- Vários terminais na mesma LAN ---
    # JSON `{"<nome>": {"host": ..., "port": ..., "scheme": ..., "user": ...,
    # "password": ...}}`. Cada um responde em `/leitores/<nome>/hikvision/...`;
    # no FaceGate, o device usa `gateway_url = https://<túnel>/leitores/<nome>`.
    # As rotas `/hikvision/...` (sem nome) seguem falando com o `HIKVISION_*`.
    leitores: dict[str, LeitorConfig] = Field(default_factory=dict)

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    @field_validator("leitores")
    @classmethod
    def _nomes_validos(cls, v: dict[str, LeitorConfig]) -> dict[str, LeitorConfig]:
        for nome in v:
            if not _NOME_LEITOR.match(nome):
                raise ValueError(
                    f"nome de leitor inválido: {nome!r} (use a-z, 0-9 e '-')"
                )
        return v

    @property
    def hikvision_base_url(self) -> str:
        return f"{self.hikvision_scheme}://{self.hikvision_host}:{self.hikvision_port}"

    @property
    def leitor_padrao(self) -> LeitorConfig:
        """O terminal das vars `HIKVISION_*` (rotas `/hikvision/...`)."""
        return LeitorConfig(
            host=self.hikvision_host,
            port=self.hikvision_port,
            scheme=self.hikvision_scheme,
            user=self.hikvision_user,
            password=self.hikvision_password,
            fdid=self.hikvision_fdid,
            face_lib_type=self.hikvision_face_lib_type,
        )


settings = Settings()
