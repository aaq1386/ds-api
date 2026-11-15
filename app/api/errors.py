import logging
from fastapi import Request
from fastapi.responses import JSONResponse

from app.providers.deepseek import (
    AuthenticationError, RateLimitError, NetworkError, APIError,
)
from app.security.secrets import redact


logger = logging.getLogger("api")


async def deepseek_error_handler(request: Request, exc: Exception):
    status = 500
    code = "deepseek_error"
    if isinstance(exc, AuthenticationError):
        status, code = 401, "auth_error"
    elif isinstance(exc, RateLimitError):
        status, code = 429, "rate_limit"
    elif isinstance(exc, NetworkError):
        status, code = 502, "network_error"
    elif isinstance(exc, APIError):
        status, code = 502, "api_error"
    logger.warning("deepseek error: %s", redact(str(exc)))
    return JSONResponse(status_code=status, content={"error": code, "detail": redact(str(exc))})


def register_error_handlers(app) -> None:
    app.add_exception_handler(AuthenticationError, deepseek_error_handler)
    app.add_exception_handler(RateLimitError, deepseek_error_handler)
    app.add_exception_handler(NetworkError, deepseek_error_handler)
    app.add_exception_handler(APIError, deepseek_error_handler)
