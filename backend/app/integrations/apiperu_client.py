"""Consulta real de DNI/RUC via api.apiperu.pe -- para poner en la
boleta/factura el nombre completo (RENIEC) o la razón social (SUNAT)
REALES, en vez de lo que el cliente alcanza a decir por teléfono (que
puede venir mal deletreado, informal, o de plano vacío para la razón
social de una factura -- ver agents/runtime.py, need_dni/need_ruc).

Contrato real (confirmado en vivo contra la API, no solo por su
documentación -- el host real es `api.apiperu.pe`, NO `apiperu.pe/api`
como muestran sus propios ejemplos de blog):

    POST https://api.apiperu.pe/dni   {"dni": "12345678"}
    POST https://api.apiperu.pe/ruc   {"ruc": "12345678901"}
    Header: Authorization: Bearer <token>

Respuesta exitosa: {"success": true, "message": "exito", "data": {...}}
Respuesta fallida:  {"success": false, "message": "...", "data": null}
(token inválido, documento mal formado, no encontrado, etc. -- todas usan
HTTP 200 con success=false, no códigos de error HTTP).

Nunca debe poder trabar ni caerse una llamada real: cualquier error (token
no configurado, timeout, red caída, respuesta rara) devuelve None y quien
llama sigue con su propio fallback (mismo espíritu que wsp_notifications.py,
aunque aquí SÍ se espera el resultado -- hace falta para armar el
comprobante, no es un aviso en paralelo)."""

import logging

import httpx

from app.infrastructure.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.apiperu.pe"
_TIMEOUT_SECONDS = 6.0


async def _post(path: str, body: dict) -> dict | None:
    if not settings.apiperu_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{_BASE_URL}{path}",
                json=body,
                headers={
                    "Authorization": f"Bearer {settings.apiperu_token}",
                    "Accept": "application/json",
                },
            )
        payload = response.json()
    except Exception:
        logger.warning("apiperu.pe: fallo la consulta a %s", path, exc_info=True)
        return None

    if not isinstance(payload, dict) or not payload.get("success"):
        message = payload.get("message") if isinstance(payload, dict) else None
        logger.info("apiperu.pe: consulta a %s sin éxito -- %s", path, message)
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


async def lookup_dni(dni: str) -> str | None:
    """Nombre completo real (RENIEC) para un DNI de 8 dígitos, formateado
    "NOMBRES APELLIDO_PATERNO APELLIDO_MATERNO" -- listo para la boleta.
    None si no se pudo consultar (API sin configurar, caída, DNI no
    encontrado, etc.)."""
    data = await _post("/dni", {"dni": dni})
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
    data = await _post("/ruc", {"ruc": ruc})
    if not data:
        return None
    razon_social = str(data.get("nombre_o_razon_social") or "").strip()
    return razon_social or None
