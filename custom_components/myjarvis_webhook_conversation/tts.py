"""TTS platform for webhook conversation integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
from homeassistant.components.tts import (
    ATTR_VOICE,
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_SUPPORTED_LANGUAGES,
    CONF_TIMEOUT,
    CONF_VOICE,
    CONF_VOICES,
    DEFAULT_TIMEOUT,
    DOMAIN,
)
from .entity import WebhookConversationBaseEntity
from .models import WebhookTTSRequestPayload

_LOGGER = logging.getLogger(__name__)

ATTR_WHISPER = "whisper"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entity for webhook conversation."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "tts":
            continue

        async_add_entities(
            [WebhookConversationTextToSpeechEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class WebhookConversationTextToSpeechEntity(
    WebhookConversationBaseEntity, TextToSpeechEntity
):
    """MyJarvis TTS entity."""

    _attr_has_entity_name = False
    _attr_name: str
    _voices: list[Voice] | None = None

    def __init__(self, config_entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize TTS entity."""
        super().__init__(config_entry, subentry)
        self._attr_name: str = (
            (self.device_info.get("name") or subentry.title)
            if self.device_info
            else subentry.title
        )

        supported_languages: list[str] = subentry.data[CONF_SUPPORTED_LANGUAGES]
        self._attr_supported_languages = supported_languages
        self._attr_default_language = supported_languages[0]

        # Neue Subentries speichern genau eine voice_id; alte Konfigurationen
        # mit Freitext-Liste (CONF_VOICES) werden weiterhin unterstützt.
        voice_id: str | None = subentry.data.get(CONF_VOICE)
        if voice_id is None and (legacy := subentry.data.get(CONF_VOICES)):
            voice_id = legacy[0] if isinstance(legacy, list) else str(legacy)

        self._voice_id = voice_id
        # "whisper" ist immer supported, damit tts.speak/Automationen und
        # Satelliten-tts_options den Key setzen können (sonst lehnt
        # process_options ihn als invalid ab).
        self._attr_supported_options = [ATTR_VOICE, ATTR_WHISPER]
        if voice_id:
            self._voices = [Voice(voice_id, voice_id)]

    @callback
    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        """Return a list of supported voices for a language."""
        return self._voices

    def _whisper_from_session(self) -> bool:
        """Verbraucht das Whisper-Flag aus dem conversation_id-Store (Default False).

        Genau einmal pro TTS-Aufruf aufrufen (in ``async_get_tts_audio``) —
        ``consume`` poppt den Eintrag. Abgelaufene Einträge
        (> WHISPER_TTL_SECONDS) liefern False. Fail-closed: Kein Session-
        Kontext, kein Store oder unbekannte conversation_id → False.
        """
        from homeassistant.helpers.chat_session import current_session

        session = current_session.get()
        if session is None:
            return False
        store = self.hass.data.get(DOMAIN, {}).get("whisper_state")
        if store is None:
            return False
        return bool(store.consume(session.conversation_id))

    @property
    def default_options(self) -> Mapping[str, Any]:
        """Return a mapping with the default options.

        Bewusst als normale ``@property`` (nicht ``cached_property``) und
        ohne Nebenwirkungen: HA wertet ``default_options`` in
        ``process_options`` aus (bereits in ``prepare_text_to_speech``, also
        VOR der Conversation — dort ist der Whisper-Store noch leer). Der
        Whisper-Wert darf daher NICHT hier ermittelt werden, sondern erst in
        ``async_get_tts_audio``. Explizite ``tts.speak``-Optionen (inkl.
        ``whisper``) fließen über die gehashten Optionen korrekt in den
        HA-Cache-Key ein.
        """
        opts: dict[str, Any] = {}
        if self._voices:
            opts[ATTR_VOICE] = self._voices[0]
        return opts

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Load TTS audio from webhook."""

        timeout = self._config_entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        session = async_get_clientsession(self.hass)
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        headers = self._get_auth_headers()

        payload: WebhookTTSRequestPayload = {
            "text": message,
            "language": language,
        }

        # Whisper strikt fail-closed: Explizite tts.speak-Option gewinnt immer
        # gegenüber dem Store (Key IMMER prüfen — bool("false") ist True, daher
        # nur echte Bools akzeptieren). Ohne explizite Option wird das Flag
        # genau einmal aus dem Store verbraucht (Pipeline-Pfad) — gelesen wird
        # unter ``session.conversation_id`` (identisch mit ``chat_log.conversation_id``,
        # unter dem ``conversation.py`` speichert; Kopplung siehe dort).
        # Alles Unklare → False: Whisper ist nur ein optionales Feature.
        if ATTR_WHISPER in options:
            whisper = options[ATTR_WHISPER] is True
        else:
            whisper = self._whisper_from_session()
        payload["whisper"] = whisper

        if whisper:
            # M1 (Review): Im Pipeline-Pfad kann der HA-TTS-Cache normale und
            # geflüsterte Ausgabe bei identischem Antworttext kollidieren lassen
            # (Cache-Key wird vor der Conversation berechnet). Beobachten bis
            # "Weg A" (tts_options pro Run) steht.
            _LOGGER.info(
                "Whisper-Ausgabe angefordert (explizite Option=%s)",
                ATTR_WHISPER in options,
            )

        # Die Stimmen-ID wird direkt an das Backend gesendet; dieses mapped
        # sie harte auf Vendor, Modell und Provider-Stimme.
        if self._voice_id:
            payload["voice_id"] = self._voice_id

        async with session.post(
            self._webhook_url,
            json=payload,
            headers=headers,
            timeout=client_timeout,
        ) as response:
            if response.status != 200:
                raise HomeAssistantError(
                    f"Error contacting TTS webhook: HTTP {response.status} - {response.reason}"
                )

            response_bytes = await response.read()
            content_type: str | None = response.headers.get("Content-Type")
            if not content_type or "/" not in content_type:
                raise HomeAssistantError(
                    f"Invalid Content-Type in TTS webhook response: {content_type}"
                )
            audio_format = content_type.split("/")[-1]
            if audio_format not in ["wav", "mp3"]:
                raise HomeAssistantError(
                    f"Unsupported audio format in TTS webhook response: {audio_format}"
                )

        return audio_format, response_bytes
