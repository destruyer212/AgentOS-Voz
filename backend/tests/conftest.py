"""Aisla la suite de tests de la base de datos real (agentos.db).

Bug real, descubierto en vivo: sin esto, `pytest tests/` corria contra el
MISMO sqlite que usan las llamadas telefonicas reales -- cada corrida de la
suite confirmaba pedidos de verdad (varios tests hacen un pedido completo
hasta "closed") y descontaba stock real. Tras correr la suite varias veces
en esta misma sesion, "Hamburguesa Clasica" llego a 0 unidades disponibles
-- rompiendo DOS cosas a la vez: los tests (fallaban con "Stock insuficiente")
Y una llamada real que quisiera pedir esa hamburguesa.

DATABASE_URL se fija ANTES de que cualquier modulo de `app` se importe --
conftest.py se carga antes que los archivos de test dentro del mismo
directorio, asi que `Settings()` (que lee el env al arrancar) ya ve el valor
de test. Si el proceso de pytest se lanzo con DATABASE_URL ya seteado
explicitamente (ej. un pipeline de CI que apunta a otra cosa), se respeta
ese valor y no se pisa.
"""

import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_agentos.db")

import pytest


@pytest.fixture(scope="session", autouse=True)
def _fresh_test_database():
    """Borra el sqlite de test al arrancar la sesion de pytest (no en cada
    test individual -- los fixtures por-test siguen recreando tablas/seed
    sobre este archivo limpio). Sin este borrado, el stock de test tambien
    se iria agotando corrida tras corrida, con el tiempo -- mismo problema
    que el de arriba, solo que mas lento."""
    db_path = Path("test_agentos.db")
    db_path.unlink(missing_ok=True)
    yield
