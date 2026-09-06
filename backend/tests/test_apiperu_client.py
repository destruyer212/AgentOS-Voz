"""Consulta real de DNI/RUC via api.apiperu.pe (ver
app/integrations/apiperu_client.py). El contrato de la API (host real
`api.apiperu.pe`, no `apiperu.pe/api` como muestra su propio blog; forma
de la respuesta success/data) se confirmo en vivo con curl antes de
escribir esto -- estos tests mockean esa respuesta ya confirmada, no
inventan una nueva. Lo que de verdad importa cubrir: el armado del nombre
completo/razon social a partir del JSON real, y que CUALQUIER falla (sin
token, success=false, excepcion de red) devuelve None sin propagar nada --
esto se llama en medio de una llamada real, nunca debe poder trabarla."""

import httpx
import pytest

from app.infrastructure.config import settings
from app.integrations import apiperu_client


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json, headers):
        if self._exc:
            raise self._exc
        return self._response


@pytest.fixture(autouse=True)
def _fake_token(monkeypatch):
    # La mayoria de estos tests necesitan un token "configurado" para
    # llegar a la logica real -- ver test_lookup_dni_without_token_returns_none
    # para el caso sin token.
    monkeypatch.setattr(settings, "apiperu_token", "fake-token-for-tests")
    yield


def _mock_post(monkeypatch, *, payload=None, exc=None):
    def factory(*args, **kwargs):
        return _FakeAsyncClient(response=_FakeResponse(payload) if payload is not None else None, exc=exc)

    monkeypatch.setattr(apiperu_client.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_lookup_dni_without_token_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "apiperu_token", None)
    assert await apiperu_client.lookup_dni("71599210") is None


@pytest.mark.asyncio
async def test_lookup_dni_success_joins_nombres_and_apellidos(monkeypatch):
    _mock_post(
        monkeypatch,
        payload={
            "success": True,
            "message": "exito",
            "data": {
                "numero": "71599210",
                "nombre_completo": "CASTILLO VELASQUEZ, DAYANNA ARACELI",
                "nombres": "DAYANNA ARACELI",
                "apellido_paterno": "CASTILLO",
                "apellido_materno": "VELASQUEZ",
            },
        },
    )
    assert await apiperu_client.lookup_dni("71599210") == "DAYANNA ARACELI CASTILLO VELASQUEZ"


@pytest.mark.asyncio
async def test_lookup_ruc_success_returns_razon_social(monkeypatch):
    _mock_post(
        monkeypatch,
        payload={
            "success": True,
            "message": "exito",
            "data": {"ruc": "20563398761", "nombre_o_razon_social": "EL OLIVAR GRILL E.I.R.L.", "estado": "ACTIVO"},
        },
    )
    assert await apiperu_client.lookup_ruc("20563398761") == "EL OLIVAR GRILL E.I.R.L."


@pytest.mark.asyncio
async def test_lookup_ruc_not_found_returns_none(monkeypatch):
    _mock_post(monkeypatch, payload={"success": False, "message": "RUC no valido", "data": None})
    assert await apiperu_client.lookup_ruc("99999999999") is None


@pytest.mark.asyncio
async def test_lookup_dni_bad_token_returns_none(monkeypatch):
    _mock_post(monkeypatch, payload={"success": False, "message": "Token inválido o expirado"})
    assert await apiperu_client.lookup_dni("71599210") is None


@pytest.mark.asyncio
async def test_lookup_dni_network_error_returns_none_not_raises(monkeypatch):
    _mock_post(monkeypatch, exc=httpx.ConnectTimeout("boom"))
    assert await apiperu_client.lookup_dni("71599210") is None


@pytest.mark.asyncio
async def test_lookup_ruc_network_error_returns_none_not_raises(monkeypatch):
    _mock_post(monkeypatch, exc=httpx.ConnectTimeout("boom"))
    assert await apiperu_client.lookup_ruc("20563398761") is None


@pytest.mark.asyncio
async def test_lookup_dni_missing_name_fields_returns_none(monkeypatch):
    _mock_post(monkeypatch, payload={"success": True, "message": "exito", "data": {"numero": "00000000"}})
    assert await apiperu_client.lookup_dni("00000000") is None
