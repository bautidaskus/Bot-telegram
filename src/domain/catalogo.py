"""Catálogos iniciales del dominio."""

from __future__ import annotations

from typing import Final

CATEGORIAS_GASTO: Final[frozenset[str]] = frozenset(
    {
        "alimentos",
        "transporte",
        "ocio",
        "salud",
        "servicios",
        "alquiler",
        "ropa",
        "educacion",
        "regalos",
        "tecnologia",
        "otros",
    }
)

CATEGORIAS_INGRESO: Final[frozenset[str]] = frozenset(
    {"sueldo", "freelance", "regalo", "venta", "inversion", "otros"}
)

METODOS_PAGO: Final[frozenset[str]] = frozenset(
    {"efectivo", "debito", "credito", "transferencia", "mercadopago"}
)
