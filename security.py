"""
security.py -- acceso protegido para la API de Radiologist_OS.

Variables de entorno (Railway):
  API_TOKEN        Usar solo letras y numeros (ASCII), 32+ caracteres.
                   Si esta definida, TODAS las rutas exigen
                   "Authorization: Bearer <token>" (excepto /health y los
                   preflight OPTIONS). Si NO esta definida, no se exige nada
                   (modo de transicion: desplegar el codigo no cambia nada).
  ALLOWED_ORIGINS  Dominios del frontend separados por coma, por ejemplo
                   "https://mi-app.vercel.app". Si no esta definida: "*".
  APP_ENV          "production" desactiva /docs, /redoc y /openapi.json.

Orden de middlewares: la autenticacion va por dentro y CORS por fuera, para
que las respuestas 401 tambien lleven cabeceras CORS y el navegador pueda
mostrar el 401 en lugar de un error generico.
"""

import hmac
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("security")

PUBLIC_PATHS = {"/health"}


def docs_kwargs() -> dict:
    if os.environ.get("APP_ENV", "").lower() == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


def _token_ok(header_value: str, expected: str) -> bool:
    scheme, _, supplied = (header_value or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        return False
    return hmac.compare_digest(
        supplied.strip().encode("utf-8"), expected.encode("utf-8")
    )


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        expected = os.environ.get("API_TOKEN", "")
        if (
            not expected
            or request.method == "OPTIONS"
            or request.url.path in PUBLIC_PATHS
        ):
            return await call_next(request)
        if not _token_ok(request.headers.get("authorization", ""), expected):
            return JSONResponse({"detail": "No autorizado"}, status_code=401)
        return await call_next(request)


def install_security(app: FastAPI) -> None:
    if not os.environ.get("API_TOKEN"):
        log.warning("API_TOKEN no definido: la API NO exige autenticacion.")

    raw = os.environ.get("ALLOWED_ORIGINS", "")
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]

    # Se agrega primero (queda por dentro).
    app.add_middleware(TokenAuthMiddleware)
    # Se agrega despues (queda por fuera).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
