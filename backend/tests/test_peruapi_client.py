"""Consulta real de DNI/RUC via peruapi.com (ver
app/integrations/peruapi_client.py). El contrato de la API (host real
`peruapi.com`, auth por query param `api_token`, campos en el nivel raiz
del JSON con "code"/"mensaje" en vez de success/data) se confirmo en vivo
con curl antes de escribir esto -- estos tests mockean esa respuesta ya
confirmada, no inventan una nueva. Lo que de verdad importa cubrir: el
armado del nombre completo/razon social a partir del JSON real, que
CUALQUIER falla (sin token, code != "200", excepcion de red, o la pagina
404 HTML que devuelve un largo de DNI/RUC invalido en vez de JSON)
devuelve None sin propagar nada -- esto se llama en medio de una llamada
real, nunca debe poder trabarla."""

import httpx
import pytest

from app.infrastructure.config import settings
from app.integrations import peruapi_client


class _FakeResponse:
    def __init__(self, payload=None, *, raises=None):
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises:
            raise self._raises
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params, headers):
        if self._exc:
            raise self._exc
        return self._response


@pytest.fixture(autouse=True)
def _fake_token(monkeypatch):
    # La mayoria de estos tests necesitan un token "configurado" para
    # llegar a la logica real -- ver test_lookup_dni_without_token_returns_none
    # para el caso sin token.
    monkeypatch.setattr(settings, "peruapi_token", "fake-token-for-tests")
    yield


def _mock_get(monkeypatch, *, response=None, exc=None):
    def factory(*args, **kwargs):
        return _FakeAsyncClient(response=response, exc=exc)

    monkeypatch.setattr(peruapi_client.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_lookup_dni_without_token_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "peruapi_token", None)
    assert await peruapi_client.lookup_dni("71599210") is None


@pytest.mark.asyncio
async def test_lookup_dni_success_joins_nombres_and_apellidos(monkeypatch):
    _mock_get(
        monkeypatch,
        response=_FakeResponse(
            {
                "dni": "71599210",
                "dv": "3",
                "cliente": "CASTILLO VELASQUEZ DAYANNA ARACELI",
                "apellido_paterno": "CASTILLO",
                "apellido_materno": "VELASQUEZ",
                "nombres": "DAYANNA ARACELI",
                "mensaje": "OK",
                "code": "200",
            }
        ),
    )
    assert await peruapi_client.lookup_dni("71599210") == "DAYANNA ARACELI CASTILLO VELASQUEZ"


@pytest.mark.asyncio
async def test_lookup_ruc_success_returns_razon_social(monkeypatch):
    _mock_get(
        monkeypatch,
        response=_FakeResponse(
            {
                "ruc": "20563398761",
                "razon_social": "EL OLIVAR GRILL E.I.R.L.",
                "estado": "BAJA DE OFICIO",
                "mensaje": "OK",
                "code": "200",
            }
        ),
    )
    assert await peruapi_client.lookup_ruc("20563398761") == "EL OLIVAR GRILL E.I.R.L."


@pytest.mark.asyncio
async def test_lookup_ruc_not_found_returns_none(monkeypatch):
    _mock_get(monkeypatch, response=_FakeResponse({"mensaje": "No encontrado", "code": "404"}))
    assert await peruapi_client.lookup_ruc("99999999999") is None


@pytest.mark.asyncio
async def test_lookup_dni_bad_token_returns_none(monkeypatch):
    _mock_get(
        monkeypatch,
        response=_FakeResponse({"mensaje": "Token inválido, inactivo o cuenta suspendida.", "code": "401"}),
    )
    assert await peruapi_client.lookup_dni("71599210") is None


@pytest.mark.asyncio
async def test_lookup_dni_malformed_length_returns_html_not_json(monkeypatch):
    # Caso real confirmado en vivo: un largo invalido en el path ni
    # siquiera matchea la ruta REST -- el servidor devuelve la pagina 404
    # HTML generica del sitio, y .json() tira ValueError ahi en vez de dar
    # un dict con "code".
    _mock_get(monkeypatch, response=_FakeResponse(raises=ValueError("Expecting value: line 1 column 1")))
    assert await peruapi_client.lookup_dni("1234567") is None


@pytest.mark.asyncio
async def test_lookup_dni_network_error_returns_none_not_raises(monkeypatch):
    _mock_get(monkeypatch, exc=httpx.ConnectTimeout("boom"))
    assert await peruapi_client.lookup_dni("71599210") is None


@pytest.mark.asyncio
async def test_lookup_ruc_network_error_returns_none_not_raises(monkeypatch):
    _mock_get(monkeypatch, exc=httpx.ConnectTimeout("boom"))
    assert await peruapi_client.lookup_ruc("20563398761") is None


@pytest.mark.asyncio
async def test_lookup_dni_missing_name_fields_returns_none(monkeypatch):
    _mock_get(monkeypatch, response=_FakeResponse({"dni": "00000000", "mensaje": "OK", "code": "200"}))
    assert await peruapi_client.lookup_dni("00000000") is None
