"""Fonctions géographiques simples (aucun service externe)."""

from __future__ import annotations

import math


EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def offset_latlon(lat: float, lon: float, north_km: float, east_km: float) -> tuple[float, float]:
    dlat = north_km / 110.574
    dlon = east_km / (111.320 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


# Rayon maximal plausible d'une cellule (km) — valeurs prudentes.
MAX_CELL_RADIUS_KM = {"GSM": 35.0, "UMTS": 20.0, "LTE": 30.0, "NR": 15.0, "UNKNOWN": 35.0}
