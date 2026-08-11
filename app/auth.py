"""Auth simples: header Authorization: Bearer <token>."""
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# auto_error=False pra retornar erro customizado (não 403 do FastAPI)
_bearer = HTTPBearer(auto_error=False)


async def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Valida o Bearer token. Compara com `settings.gateway_token` em tempo constante."""
    if credentials is None or not credentials.scheme:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Esperado: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not secrets.compare_digest(credentials.credentials, settings.gateway_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
