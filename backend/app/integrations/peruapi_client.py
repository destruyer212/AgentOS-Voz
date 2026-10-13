"""Consulta real de DNI/RUC via peruapi.com (panel: https://peruapi.com/panel)
-- para poner el nombre completo (RENIEC) o la razon social (SUNAT)
REALES en la boleta/factura, en vez de lo que el cliente alcanza a decir
por telefono.

Reemplaza a la integracion anterior con api.apiperu.pe (su plan vencio,
dejo de devolver datos -- ver historial de este archivo como
apiperu_client.py) sin cambiar nada del lado de agents/runtime.py: mismas
firmas publicas (lookup_dni/lookup_ruc), mismo contrato de "None si no se
pudo consultar, nunca una excepcion".

Contrato real, confirmado en vivo con la key real (no solo por su
documentacion):

    GET https://peruapi.com/api/dni/{dni}?api_token=<token>
    GET https://peruapi.com/api/ruc/{ruc}?api_token=<token>

Respuesta exitosa: {"code": "200", "mensaje": "OK", ...campos...} -- los
campos van en el nivel raiz del JSON, no anidados bajo "data" (a
diferencia de apiperu.pe). Respuesta fallida: {"code": "<codigo>",
"mensaje": "..."} (ej. token invalido -> 401). PERO un DNI/RUC de largo
invalido (ej. 7 digitos) ni siquiera matchea la ruta REST: el servidor
devuelve la pagina 404 HTML generica del sitio, no JSON -- por eso el
parseo nunca asume que el body es JSON valido. En la practica esto no
deberia pasar: lookup_dni/lookup_ruc solo se llaman con un numero ya
validado como de 8 u 11 digitos exactos (ver agents/runtime.py,
_extract_id_number)."""

import logging

import httpx

from app.infrastructure.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://peruapi.com"
_TIMEOUT_SECONDS = 6.0


async def _get(path: str) -> dict | None:
    if not settings.peruapi_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{_BASE_URL}{path}",
                params={"api_token": settings.peruapi_token},
                headers={"Accept": "application/json"},
            )
        payload = response.json()
    except Exception:
        # Incluye el caso real de un largo invalido: la ruta ni matchea y
        # el servidor devuelve la pagina 404 HTML del sitio -- .json()
        # tira ahi, no da un dict con "code".
        logger.warning("peruapi.com: fallo la consulta a %s", path, exc_info=True)
        return None

    if not isinstance(payload, dict) or payload.get("code") != "200":
        message = payload.get("mensaje") if isinstance(payload, dict) else None
        logger.info("peruapi.com: consulta a %s sin éxito -- %s", path, message)
        return None
    return payload


async def lookup_dni(dni: str) -> str | None:
    """Nombre completo real (RENIEC) para un DNI de 8 dígitos, formateado
    "NOMBRES APELLIDO_PATERNO APELLIDO_MATERNO" -- listo para la boleta.
    None si no se pudo consultar (API sin configurar, caída, DNI no
    encontrado, etc.)."""
    data = await _get(f"/api/dni/{dni}")
    if not data:
        return None
    nombres = str(data.get("nombres") or "").strip()
    apellido_paterno = str(data.get("apellido_paterno") or "").strip()
    apellido_materno = str(data.get("apellido_materno") or "").strip()
    nombre_completo = " ".join(part for part in (nombres, apellido_paterno, apellido_materno) if part)
    return nombre_completo or None


async def lookup_ruc(ruc: str) -> str | None:
    """Razón social real (SUNAT) para un RUC de 11 dígitos -- listo para la
    factura. None si no se pudo consultar."""
    data = await _get(f"/api/ruc/{ruc}")
    if not data:
        return None
    razon_social = str(data.get("razon_social") or "").strip()
    return razon_social or None
