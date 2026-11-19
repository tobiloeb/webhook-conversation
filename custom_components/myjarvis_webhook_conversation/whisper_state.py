"""Whisper-Zustand pro conversation_id (hassmic-Sensor → TTS-Flag)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

WHISPER_SENSOR_SUFFIX = "_last_request_whispered"  # hassmic/ESPHome-Sensor

# Gültigkeitsdauer (Sekunden) für Whisper-Informationen — zentrale Konstante
# für beide Prüfungen:
#   1. Frische des hassmic-Sensors beim Record (last_changed <= TTL).
#   2. Ablauf der Store-Einträge (peek/consume liefern danach False).
# Antworten, die länger als WHISPER_TTL_SECONDS dauern, werden normal gesprochen.
WHISPER_TTL_SECONDS = 30.0

# Backstop gegen unbegrenztes Wachstum: älteste Einträge werden verworfen.
_WHISPER_STORE_MAX_ENTRIES = 500


class WhisperStateStore:
    """Merkt pro conversation_id, ob der Nutzer geflüstert hat.

    Einträge laufen nach ``WHISPER_TTL_SECONDS`` ab (Default False).
    """

    def __init__(self) -> None:
        self._states: dict[str, tuple[bool, float]] = {}

    def _is_fresh(self, stored_at: float) -> bool:
        return (time.monotonic() - stored_at) <= WHISPER_TTL_SECONDS

    def record(self, conversation_id: str, whispered: bool) -> None:
        """Speichert das Whisper-Ergebnis für eine conversation_id."""
        self._states[conversation_id] = (whispered, time.monotonic())
        while len(self._states) > _WHISPER_STORE_MAX_ENTRIES:
            self._states.pop(next(iter(self._states)))

    def peek(self, conversation_id: str) -> bool:
        """Liest das Flag ohne es zu entfernen (side-effect-frei).

        Abgelaufene Einträge werden als False geliefert und verworfen.
        """
        entry = self._states.get(conversation_id)
        if entry is None:
            return False
        whispered, stored_at = entry
        if not self._is_fresh(stored_at):
            self._states.pop(conversation_id, None)
            return False
        return whispered

    def consume(self, conversation_id: str) -> bool:
        """Liefert und entfernt das gespeicherte Flag (Default False).

        Genau einmal pro Request aufrufen (in ``async_get_tts_audio``),
        nicht in Properties, die HA mehrfach auswertet.
        """
        entry = self._states.pop(conversation_id, None)
        if entry is None:
            return False
        whispered, stored_at = entry
        return whispered if self._is_fresh(stored_at) else False


def find_whisper_sensor(hass: HomeAssistant, satellite_id: str) -> str | None:
    """Findet den hassmic-Whisper-Sensor des Satelliten-Geräts.

    ``satellite_id`` ist die Entity-ID des Assist-Satelliten (nicht die
    device_id). Die device_id wird über die Entity-Registry aufgelöst; nur
    dann wird nach einem Sensor mit passendem Suffix *auf diesem Gerät*
    gesucht. Kann die device_id nicht aufgelöst werden, wird ``None``
    geliefert (fail-closed: kein globaler Suffix-Fallback, der bei
    Mehr-Echos den falschen Sensor treffen könnte).
    """
    from homeassistant.helpers import entity_registry as er

    er_reg = er.async_get(hass)
    sat_entry = er_reg.async_get(satellite_id)
    device_id = sat_entry.device_id if sat_entry else None

    if device_id is None:
        _LOGGER.warning(
            "Whisper-Sensor-Suche: satellite_id %s ist nicht in der "
            "Entity-Registry (keine device_id) → Whisper wird nicht genutzt",
            satellite_id,
        )
        return None

    for ent in er_reg.entities.values():
        if ent.device_id != device_id:
            continue
        if (ent.unique_id and ent.unique_id.endswith(WHISPER_SENSOR_SUFFIX)) or (
            ent.entity_id.endswith(WHISPER_SENSOR_SUFFIX)
        ):
            return ent.entity_id
    return None