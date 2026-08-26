"""Configuracion unica de Telnyx: crea la Call Control Application con el
webhook apuntando a tu URL publica, y le asigna el primer numero comprado
de la cuenta.

Uso (con el backend instalado, .env con TELNYX_API_KEY configurado):

    cd backend
    ./.venv/Scripts/python.exe scripts/setup_telnyx.py https://tu-url-publica.example.com

Corre esto de nuevo si cambia tu URL publica (ej. cada vez que reinicias
un tunel ngrok gratuito, que cambia de URL en cada arranque).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.infrastructure.config import settings  # noqa: E402

BASE_URL = "https://api.telnyx.com/v2"
APP_NAME = "AgentOS Voz"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.telnyx_api_key}",
        "Content-Type": "application/json",
    }


def main(public_base_url: str) -> None:
    if not settings.telnyx_api_key:
        print("Falta TELNYX_API_KEY en backend/.env")
        sys.exit(1)

    webhook_url = f"{public_base_url.rstrip('/')}/api/v1/telephony/telnyx/webhook"

    with httpx.Client(timeout=15) as client:
        existing = client.get(f"{BASE_URL}/call_control_applications", headers=_headers())
        existing.raise_for_status()
        apps = [a for a in existing.json()["data"] if a["application_name"] == APP_NAME]

        if apps:
            connection_id = apps[0]["id"]
            client.patch(
                f"{BASE_URL}/call_control_applications/{connection_id}",
                headers=_headers(),
                json={"webhook_event_url": webhook_url},
            ).raise_for_status()
            print(f"Call Control Application existente actualizada: {connection_id}")
        else:
            created = client.post(
                f"{BASE_URL}/call_control_applications",
                headers=_headers(),
                json={
                    "application_name": APP_NAME,
                    "webhook_event_url": webhook_url,
                    "webhook_api_version": "2",
                },
            )
            created.raise_for_status()
            connection_id = created.json()["data"]["id"]
            print(f"Call Control Application creada: {connection_id}")

        numbers_resp = client.get(f"{BASE_URL}/phone_numbers", headers=_headers())
        numbers_resp.raise_for_status()
        numbers = numbers_resp.json()["data"]

        if not numbers:
            print("No hay numeros comprados en la cuenta todavia.")
            return

        phone_number_id = numbers[0]["id"]
        phone_number = numbers[0]["phone_number"]

        client.patch(
            f"{BASE_URL}/phone_numbers/{phone_number_id}",
            headers=_headers(),
            json={"connection_id": connection_id},
        ).raise_for_status()

        print(f"Numero {phone_number} asignado a la connection {connection_id}.")
        print(f"Webhook configurado en: {webhook_url}")
        print("\nListo. Llama a ese numero para hablar con el agente.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python scripts/setup_telnyx.py https://tu-url-publica")
        sys.exit(1)
    main(sys.argv[1])
