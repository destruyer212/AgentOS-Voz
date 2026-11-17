"""Genera llamadas sinteticas y pedidos consistentes para APF3.

Los productos y precios provienen del catalogo local del proyecto; clientes,
llamadas, pedidos y resultados son ficticios y no se guardan en la base de datos.
"""

from __future__ import annotations

import csv
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.infrastructure.olivar_menu import OLIVAR_PRODUCTS

SEED = 20261116
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "data" / "llamadas_sinteticas_250.csv"
FIELDS = [
    "call_id", "fecha_hora", "canal", "duracion_segundos", "intentos_aclaracion",
    "items_solicitados", "items_distintos", "unidades_totales", "tipo_entrega",
    "subtotal_soles", "delivery_soles", "total_soles", "resultado", "pedido_confirmado",
    "productos_pedido", "metodo_pago", "mensaje_cliente", "requiere_aclaracion",
    "plato_agotado", "alternativa_elegida", "minutos_preparacion",
]


def generate_calls(output: Path = DEFAULT_OUTPUT, count: int = 250) -> list[dict[str, str]]:
    rng = random.Random(SEED)
    menu = [
        {"code": code, "name": name, "price": float(price), "category": category}
        for code, name, _description, price, category in OLIVAR_PRODUCTS
        if float(price) > 0
    ]
    if len(menu) < 10:
        raise ValueError("El catalogo local no tiene suficientes productos con precio")

    rows = []
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    for number in range(1, count + 1):
        channel = rng.choices(["telefono", "whatsapp", "chat_web"], [0.52, 0.31, 0.17])[0]
        fulfillment = rng.choices(["delivery", "recojo"], [0.72, 0.28])[0]
        selected = rng.sample(menu, k=rng.choices([1, 2, 3], [0.48, 0.39, 0.13])[0])
        order_items = []
        for product in selected:
            qty = rng.choices([1, 2, 3], [0.78, 0.19, 0.03])[0]
            order_items.append((product, qty))
        subtotal = round(sum(p["price"] * q for p, q in order_items), 2)
        delivery_fee = round(rng.choice([5.0, 6.0, 7.0]), 2) if fulfillment == "delivery" else 0.0
        total = round(subtotal + delivery_fee, 2)
        clarifications = rng.choices([0, 1, 2, 3], [0.42, 0.37, 0.17, 0.04])[0]
        message, ambiguous = rng.choice([
            ("Quiero un cuarto de pollo para recoger", False),
            ("Me das pollo con papas, el de siempre", True),
            ("Quiero dos chaufa de pollo y una Inca Kola", False),
            ("Un plato sin cebolla por favor", True),
            ("Quiero el combo familiar para delivery", False),
            ("Quiero pollo, no recuerdo cual plato", True),
            ("Mandame el combo grande, cuanto cuesta", True),
            ("Quiero uno de esos con papas para mas tarde", True),
            ("Dame pollo a la brasa pero no se si entero o medio", True),
            ("Quiero pollo con papas, por favor", False),
            ("Agrega dos bebidas y un pollo para llevar", True),
            ("Una parrilla para dos a domicilio", False),
            ("Lo mismo que pedi la semana pasada", True),
            ("Un chaufa especial sin wantan, por favor", False),
            ("Quiero el familiar, el que trae de todo", True),
            ("Dos cuartos de pollo, ambos con papas", False),
            ("Dame el de pollo con ese acompañamiento", True),
            ("Una porcion de yucas y una limonada", False),
            ("Quiero algo de parrilla, recomiendame", True),
            ("Un pollo Ricky mas anticucho para recoger", False),
        ])
        needs_clarification = ambiguous ^ (rng.random() < 0.1)
        prep_minutes = max(8, int(8 + 3.8 * len(order_items) + 1.4 * sum(q for _, q in order_items)
                               + 2.5 * len({p['category'] for p, _ in order_items})
                               + rng.gauss(0, 3.0)))
        # A stable, plausible label rule with noise; only pre-outcome fields feed models.
        probability = 0.88 - 0.12 * clarifications - (0.08 if channel == "telefono" else 0)
        confirmed = rng.random() < max(0.35, min(0.95, probability))
        duration = max(35, int(rng.gauss(115 + 24 * len(order_items) + 19 * clarifications, 28)))
        moment = start + timedelta(minutes=number * 37 + rng.randint(0, 22))
        rows.append({
            "call_id": f"SYN-CALL-{number:04d}",
            "fecha_hora": moment.isoformat(timespec="minutes"),
            "canal": channel,
            "duracion_segundos": str(duration),
            "intentos_aclaracion": str(clarifications),
            "items_solicitados": str(sum(q for _, q in order_items)),
            "items_distintos": str(len(order_items)),
            "unidades_totales": str(sum(q for _, q in order_items)),
            "tipo_entrega": fulfillment,
            "subtotal_soles": f"{subtotal:.2f}",
            "delivery_soles": f"{delivery_fee:.2f}",
            "total_soles": f"{total:.2f}" if confirmed else "",
            "resultado": "pedido_confirmado" if confirmed else rng.choice(
                ["cliente_desiste", "sin_respuesta", "transferida_a_persona"]),
            "pedido_confirmado": "1" if confirmed else "0",
            "productos_pedido": " | ".join(
                f"{qty}x {product['name']} (S/ {product['price']:.2f} c/u)"
                for product, qty in order_items
            ),
            "metodo_pago": rng.choice(["efectivo", "yape", "plin", "tarjeta"]) if confirmed else "",
            "mensaje_cliente": message,
            "requiere_aclaracion": "1" if needs_clarification else "0",
            "plato_agotado": "Pollo a la Brasa" if number % 5 == 0 else "",
            "alternativa_elegida": "Pollo Ricky + Anticucho" if number % 5 == 0 else "",
            "minutos_preparacion": str(prep_minutes),
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=250)
    args = parser.parse_args()
    result = generate_calls(args.output, args.count)
    print(f"Generadas {len(result)} llamadas sinteticas: {args.output}")
    print(f"Pedidos confirmados: {sum(row['pedido_confirmado'] == '1' for row in result)}")
