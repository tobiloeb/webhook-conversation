"""Config flow for the MyJarvis webhook conversation integration."""

from __future__ import annotations

import logging
from typing import Any, cast
from urllib.parse import urlparse, urlunparse

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from homeassistant.util import language as language_util

from .const import (
    CONF_AUTH_TYPE,
    CONF_ENABLE_STREAMING,
    CONF_NAME,
    CONF_OUTPUT_FIELD,
    CONF_PASSWORD,
    CONF_PROFILE,
    CONF_SUPPORTED_LANGUAGES,
    CONF_TIMEOUT,
    CONF_USERNAME,
    CONF_VOICE,
    CONF_VOICES,
    CONF_WEBHOOK_URL,
    DEFAULT_AI_TASK_NAME,
    DEFAULT_AUTH_TYPE,
    DEFAULT_CONVERSATION_NAME,
    DEFAULT_ENABLE_STREAMING,
    DEFAULT_OUTPUT_FIELD,
    DEFAULT_PROFILE,
    DEFAULT_STT_NAME,
    DEFAULT_SUPPORTED_LANGUAGES,
    DEFAULT_TIMEOUT,
    DEFAULT_TTS_NAME,
    DOMAIN,
    MANUFACTURER,
    RECOMMENDED_AI_TASK_OPTIONS,
    RECOMMENDED_CONVERSATION_OPTIONS,
    RECOMMENDED_STT_OPTIONS,
    RECOMMENDED_TTS_OPTIONS,
    AuthType,
)

_LOGGER = logging.getLogger(__name__)


def _voices_endpoint_url(webhook_url: str) -> str:
    """Leitet die Voices-URL aus der konfigurierten TTS-Webhook-URL ab."""
    return _endpoint_url(webhook_url, "/api/tts", "/api/tts/voices")


def _profiles_endpoint_url(webhook_url: str) -> str:
    """Leitet die Profil-URL aus der konfigurierten Webhook-URL ab."""
    return _endpoint_url(webhook_url, "/api/agent/prompt", "/api/profiles")


def _endpoint_url(webhook_url: str, stripped_suffix: str, endpoint: str) -> str:
    """
    Leitet einen Sibling-Endpunkt aus einer Webhook-URL ab.

    Entfernt optional den bekannten Endpunkt-Pfad (z. B. ``/api/agent/prompt``)
    und hängt den Ziel-Endpunkt an. Query/Fragment werden verworfen, Pfade
    mit oder ohne trailing slash werden korrekt behandelt.
    """
    parsed = urlparse(webhook_url)
    base_path = parsed.path.rstrip("/")
    base_path = base_path.removesuffix(stripped_suffix)
    url = urlunparse(
        parsed._replace(path=f"{base_path}{endpoint}", query="", fragment="")
    )
    return url


async def _fetch_profile_options(
    hass: HomeAssistant,
    webhook_url: str,
    auth: aiohttp.BasicAuth | None = None,
) -> list[SelectOptionDict]:
    """Lädt den Profil-Katalog für das Dropdown aus dem Backend."""
    session = async_get_clientsession(hass)
    url = _profiles_endpoint_url(webhook_url)
    try:
        async with session.get(
            url, auth=auth, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                raise HomeAssistantError(
                    f"HTTP {resp.status} fetching profiles from {url}"
                )
            payload = cast(list[dict[str, Any]], await resp.json())
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise HomeAssistantError(f"Failed to fetch profiles from {url}: {exc}") from exc

    return [
        SelectOptionDict({"value": profile["id"], "label": profile["label"]})
        for profile in payload
    ]


async def _fetch_voice_options(
    hass: HomeAssistant,
    webhook_url: str,
    auth: aiohttp.BasicAuth | None = None,
) -> list[SelectOptionDict]:
    """Lädt den Stimmen-Katalog für das Dropdown aus dem Backend."""
    session = async_get_clientsession(hass)
    url = _voices_endpoint_url(webhook_url)
    try:
        async with session.get(
            url, auth=auth, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                raise HomeAssistantError(
                    f"HTTP {resp.status} fetching voices from {url}"
                )
            payload = cast(list[dict[str, Any]], await resp.json())
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise HomeAssistantError(f"Failed to fetch voices from {url}: {exc}") from exc

    try:
        return [
            SelectOptionDict({"value": voice["id"], "label": voice["label"]})
            for voice in payload
        ]
    except (TypeError, KeyError) as exc:
        raise HomeAssistantError(f"Invalid voices response from {url}: {exc}") from exc


def _auth_from_options(options: dict[str, Any]) -> aiohttp.BasicAuth | None:
    """Baut optionale Basic-Auth für Katalog-Abfragen aus den Flow-Daten."""
    if options.get(CONF_AUTH_TYPE) != AuthType.BASIC:
        return None
    username = str(options.get(CONF_USERNAME, "")).strip()
    password = str(options.get(CONF_PASSWORD, "")).strip()
    if username and password:
        return aiohttp.BasicAuth(username, password)
    return None


def _get_subentry_schema(
    subentry_type: str,
    options: dict[str, Any] | None = None,
    is_new: bool = True,
    hass: HomeAssistant | None = None,
) -> vol.Schema:
    """Return the subentry configuration schema."""
    if options is None:
        options = {}

    schema_dict: dict[vol.Required | vol.Optional, Any] = {}

    if is_new:
        if subentry_type == "conversation":
            default_name = DEFAULT_CONVERSATION_NAME
        elif subentry_type == "ai_task":
            default_name = DEFAULT_AI_TASK_NAME
        elif subentry_type == "tts":
            default_name = DEFAULT_TTS_NAME
        elif subentry_type == "stt":
            default_name = DEFAULT_STT_NAME
        else:
            raise ValueError(f"Unknown subentry type: {subentry_type}")

        schema_dict[vol.Required(CONF_NAME, default=default_name)] = str

    schema_dict.update(
        {
            vol.Required(
                CONF_WEBHOOK_URL,
                description={"suggested_value": options.get(CONF_WEBHOOK_URL)},
                default=None,
            ): str,
            vol.Optional(
                CONF_TIMEOUT,
                description={
                    "suggested_value": options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
                },
                default=DEFAULT_TIMEOUT,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
            vol.Required(
                CONF_AUTH_TYPE,
                description={
                    "suggested_value": options.get(CONF_AUTH_TYPE, DEFAULT_AUTH_TYPE)
                },
                default=DEFAULT_AUTH_TYPE,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[auth_type.value for auth_type in AuthType],
                    translation_key="auth_type",
                )
            ),
        }
    )

    if subentry_type in ("conversation", "ai_task"):
        schema_dict.update(
            {
                vol.Required(
                    CONF_OUTPUT_FIELD,
                    description={
                        "suggested_value": options.get(
                            CONF_OUTPUT_FIELD, DEFAULT_OUTPUT_FIELD
                        )
                    },
                    default=DEFAULT_OUTPUT_FIELD,
                ): str,
                vol.Optional(
                    CONF_ENABLE_STREAMING,
                    description={
                        "suggested_value": options.get(
                            CONF_ENABLE_STREAMING, DEFAULT_ENABLE_STREAMING
                        )
                    },
                    default=DEFAULT_ENABLE_STREAMING,
                ): bool,
            }
        )
    elif subentry_type in ("tts", "stt"):
        default_languages = options.get(
            CONF_SUPPORTED_LANGUAGES, DEFAULT_SUPPORTED_LANGUAGES
        )

        schema_dict.update(
            {
                vol.Required(
                    CONF_SUPPORTED_LANGUAGES,
                    description={"suggested_value": default_languages},
                    default=default_languages,
                ): TextSelector(
                    TextSelectorConfig(
                        multiple=True,
                    )
                ),
            }
        )

        # TTS-spezifische Konfiguration: Die Stimme wird in einem zweiten
        # Schritt (async_step_select_voice) gewählt, sobald die Webhook-URL
        # bekannt ist und der Katalog geladen werden kann.

        # STT-specific configuration
        if subentry_type == "stt":
            schema_dict[
                vol.Required(
                    CONF_OUTPUT_FIELD,
                    description={
                        "suggested_value": options.get(
                            CONF_OUTPUT_FIELD, DEFAULT_OUTPUT_FIELD
                        )
                    },
                    default=DEFAULT_OUTPUT_FIELD,
                )
            ] = str

    return vol.Schema(schema_dict)


def _get_auth_schema(options: dict[str, Any] | None = None) -> vol.Schema:
    """Return the authentication schema."""
    if options is None:
        options = {}

    return vol.Schema(
        {
            vol.Required(
                CONF_USERNAME,
                description={"suggested_value": options.get(CONF_USERNAME, "")},
            ): str,
            vol.Required(
                CONF_PASSWORD,
                description={"suggested_value": options.get(CONF_PASSWORD, "")},
            ): str,
        }
    )


class WebhookConversationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for webhook conversation integration."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        return self.async_create_entry(title=MANUFACTURER, data={}, subentries=[])

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {
            "conversation": WebhookSubentryFlowHandler,
            "ai_task": WebhookSubentryFlowHandler,
            "stt": WebhookSubentryFlowHandler,
            "tts": WebhookSubentryFlowHandler,
        }


class WebhookSubentryFlowHandler(ConfigSubentryFlow):
    """Flow for managing webhook subentries."""

    def __init__(self) -> None:
        """Initialize the subentry flow handler."""
        self._user_input: dict[str, Any] = {}

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == "user"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle initial step for new subentry."""
        return await self.async_step_set_options(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of existing subentry."""
        return await self.async_step_set_options(user_input)

    async def async_step_set_options(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Set subentry options."""
        errors: dict[str, str] = {}

        if user_input is None:
            if self._is_new:
                if self._subentry_type == "conversation":
                    options = RECOMMENDED_CONVERSATION_OPTIONS.copy()
                elif self._subentry_type == "ai_task":
                    options = RECOMMENDED_AI_TASK_OPTIONS.copy()
                elif self._subentry_type == "stt":
                    options = RECOMMENDED_STT_OPTIONS.copy()
                else:  # tts
                    options = RECOMMENDED_TTS_OPTIONS.copy()
            else:
                options = self._get_reconfigure_subentry().data.copy()

            return self.async_show_form(
                step_id="set_options",
                data_schema=_get_subentry_schema(
                    self._subentry_type, options, self._is_new, self.hass
                ),
            )

        _LOGGER.debug(
            "Processing webhook %s subentry configuration with user input: %s",
            self._subentry_type,
            user_input,
        )

        webhook_url: str = user_input[CONF_WEBHOOK_URL]
        valid_http = webhook_url.startswith(("http://", "https://"))
        valid_ws = webhook_url.startswith(("ws://", "wss://"))
        if not valid_http and not (self._subentry_type == "stt" and valid_ws):
            _LOGGER.error("Invalid webhook URL: %s", webhook_url)
            errors["base"] = "invalid_webhook_url"

        if self._subentry_type in ("tts", "stt"):
            if not (supported_languages := user_input.get(CONF_SUPPORTED_LANGUAGES)):
                errors[CONF_SUPPORTED_LANGUAGES] = "no_languages_specified"

            for language_code in cast(list[str], supported_languages):
                if not (language_code := language_code.strip()):
                    errors[CONF_SUPPORTED_LANGUAGES] = "invalid_language_code"
                    break

                try:
                    language_util.Dialect.parse(language_code)
                except (ValueError, AttributeError):
                    errors[CONF_SUPPORTED_LANGUAGES] = "invalid_language_code"
                    break

        if errors:
            return self.async_show_form(
                step_id="set_options",
                data_schema=_get_subentry_schema(
                    self._subentry_type, user_input, self._is_new, self.hass
                ),
                errors=errors,
            )

        self._user_input = user_input

        # Auth zuerst: die Katalog-Abfragen (Stimmen/Profile) brauchen
        # ggf. die Credentials.
        auth_type = user_input.get(CONF_AUTH_TYPE, DEFAULT_AUTH_TYPE)
        if auth_type == AuthType.BASIC:
            return await self.async_step_auth()

        return await self._async_step_catalog(user_input)

    async def _async_step_catalog(
        self, user_input: dict[str, Any]
    ) -> SubentryFlowResult:
        """Nach dem Auth-Schritt: Katalog-Auswahl bzw. direkter Abschluss."""
        self._user_input = user_input

        # Bei TTS wird die Stimme im zweiten Schritt gewählt; dort ist die
        # Webhook-URL bekannt und der Katalog kann geladen werden.
        if self._subentry_type == "tts":
            return await self.async_step_select_voice()

        # Bei conversations wird das Profil im zweiten Schritt gewählt
        # (gleiches Muster wie die Stimme bei TTS).
        if self._subentry_type == "conversation":
            return await self.async_step_select_profile()

        return await self._finish(user_input)

    async def async_step_select_voice(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Zweiter TTS-Schritt: Stimme aus dem Backend-Katalog wählen."""
        errors: dict[str, str] = {}

        try:
            voice_options = await _fetch_voice_options(
                self.hass,
                self._user_input[CONF_WEBHOOK_URL],
                auth=_auth_from_options(self._user_input),
            )
        except HomeAssistantError:
            _LOGGER.exception("Failed to load voice catalog")
            return self.async_abort(reason="voices_fetch_failed")

        selected_voice = self._user_input.get(CONF_VOICE)
        if selected_voice is None and (legacy := self._user_input.get(CONF_VOICES)):
            # Migration alter Freitext-Listen: erste Stimme übernehmen.
            selected_voice = legacy[0] if isinstance(legacy, list) else str(legacy)

        if user_input is not None:
            selected_voice = user_input.get(CONF_VOICE)
            if not selected_voice:
                errors[CONF_VOICE] = "voice_required"
            else:
                return await self._finish({**self._user_input, **user_input})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_VOICE,
                    description={"suggested_value": selected_voice},
                    default=selected_voice,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=voice_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="select_voice", data_schema=schema, errors=errors
        )

    async def async_step_select_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Zweiter Conversation-Schritt: Profil aus dem Backend-Katalog wählen."""
        errors: dict[str, str] = {}
        has_previous_profile = CONF_PROFILE in self._user_input

        try:
            profile_options = await _fetch_profile_options(
                self.hass,
                self._user_input[CONF_WEBHOOK_URL],
                auth=_auth_from_options(self._user_input),
            )
        except HomeAssistantError:
            _LOGGER.exception("Failed to load profile catalog")
            if has_previous_profile and user_input is None:
                # Reconfigure: mit dem bisherigen Profil weitermachen, statt
                # an einem Backend-Ausfall zu scheitern (das Profil wird
                # beim nächsten Reconfigure neu gewählt).
                return await self._finish({})
            errors["base"] = "profiles_fetch_failed"
            return self.async_show_form(
                step_id="select_profile",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_PROFILE,
                            description={
                                "suggested_value": self._user_input.get(
                                    CONF_PROFILE, DEFAULT_PROFILE
                                )
                            },
                            default=self._user_input.get(CONF_PROFILE, DEFAULT_PROFILE),
                        ): str
                    }
                ),
                errors=errors,
            )

        selected_profile = self._user_input.get(CONF_PROFILE, DEFAULT_PROFILE)

        if user_input is not None:
            selected_profile = user_input.get(CONF_PROFILE) or DEFAULT_PROFILE
            return await self._finish({**self._user_input, CONF_PROFILE: selected_profile})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PROFILE,
                    description={"suggested_value": selected_profile},
                    default=selected_profile,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=profile_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="select_profile", data_schema=schema, errors=errors
        )

    async def _finish(self, user_input: dict[str, Any]) -> SubentryFlowResult:
        """Subentry anlegen bzw. aktualisieren (Auth wurde zuvor abgefragt)."""
        self._user_input = user_input

        if self._is_new:
            return self.async_create_entry(
                title=user_input.pop(CONF_NAME),
                data=user_input,
            )

        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            data=user_input,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle authentication configuration step."""
        current_auth_data = {}
        if not self._is_new:
            existing_data = self._get_reconfigure_subentry().data
            if existing_data.get(CONF_AUTH_TYPE) == AuthType.BASIC:
                current_auth_data = {
                    CONF_USERNAME: existing_data.get(CONF_USERNAME, ""),
                    CONF_PASSWORD: existing_data.get(CONF_PASSWORD, ""),
                }

        if user_input is None:
            return self.async_show_form(
                step_id="auth", data_schema=_get_auth_schema(current_auth_data)
            )

        username = user_input.get(CONF_USERNAME, "").strip()
        password = user_input.get(CONF_PASSWORD, "").strip()

        if not username or not password:
            return self.async_show_form(
                step_id="auth",
                data_schema=_get_auth_schema(user_input),
                errors={"base": "invalid_auth"},
            )

        _LOGGER.debug("Processing authentication configuration")

        # Mit Credentials weiter zum Katalog-Schritt (Stimmen/Profile).
        return await self._async_step_catalog({**self._user_input, **user_input})
