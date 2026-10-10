"""Gestion des horodatages.

Règle du laboratoire : tous les horodatages internes sont des ``datetime``
*conscients du fuseau* exprimés en UTC. Les horodatages naïfs importés sont
interprétés dans le fuseau déclaré par la source (UTC par défaut) et cette
hypothèse est tracée dans les paramètres de collecte.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo


class TimestampError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: Any, assume_tz: tzinfo | str | None = None) -> datetime:
    """Convertit ``value`` (datetime, ISO 8601, epoch s/ms) en datetime UTC."""
    if isinstance(assume_tz, str):
        assume_tz = ZoneInfo(assume_tz)
    assume_tz = assume_tz or timezone.utc

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:  # millisecondes
            seconds /= 1000.0
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise TimestampError("horodatage vide")
        if text.replace(".", "", 1).isdigit():
            return to_utc(float(text), assume_tz)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise TimestampError(f"horodatage illisible : {value!r}") from exc
    else:
        raise TimestampError(f"type d'horodatage non pris en charge : {type(value).__name__}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt.astimezone(timezone.utc)


def check_plausible(dt: datetime, now: datetime | None = None,
                    max_future: timedelta = timedelta(minutes=5),
                    min_year: int = 2000) -> list[str]:
    """Renvoie la liste des problèmes de plausibilité (vide si aucun)."""
    now = now or utcnow()
    problems = []
    if dt.year < min_year:
        problems.append(f"horodatage antérieur à {min_year} (horloge non synchronisée ?)")
    if dt - now > max_future:
        problems.append("horodatage dans le futur")
    return problems
