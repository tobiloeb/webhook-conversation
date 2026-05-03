"""Conversation platform for webhook conversation integration."""

from collections import defaultdict
import json
import logging
from collections.abc import AsyncIterator
from operator import attrgetter
from typing import Any, Literal
from decimal import Decimal
from enum import Enum
import time

from voluptuous import extra


from homeassistant.components import conversation
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    floor_registry as fr,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util import yaml as yaml_util

from .const import CONF_OUTPUT_FIELD, DEFAULT_OUTPUT_FIELD, DOMAIN
from .entity import WebhookConversationLLMBaseEntity
from .models import WebhookConversationPayload

_LOGGER = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the integration from a config entry."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "conversation":
            continue

        async_add_entities(
            [WebhookConversationEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class WebhookConversationEntity(
    conversation.ConversationEntity,
    conversation.models.AbstractConversationAgent,
    WebhookConversationLLMBaseEntity,
):
    """Webhook conversation agent."""

    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    exposed_entities = None

    def __init__(self, config_entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the agent."""
        super().__init__(config_entry, subentry)
        self._attr_supports_streaming = self._streaming_enabled

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        # self.exposed_entities: dict[str, Any] = (
        #    self._get_home_structure_with_exposed_entities()
        # )
        conversation.async_set_agent(self.hass, self._config_entry, self)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        conversation.async_unset_agent(self.hass, self._config_entry)
        await super().async_will_remove_from_hass()

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Process the user input and call the API."""
        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                user_llm_hass_api=None,
                user_llm_prompt=self._system_prompt,
                user_extra_system_prompt=user_input.extra_system_prompt,
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        await self._async_handle_chat_log(user_input, chat_log)

        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    async def _async_handle_chat_log(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> None:
        """Send the chat log to the webhook and process the response."""
        payload = self._build_payload(chat_log)
        user_messages = [
            self._convert_content_to_param(user_message)
            for user_message in chat_log.content
            if isinstance(user_message, conversation.UserContent)
        ]

        if not user_messages:
            raise HomeAssistantError("No user message found in chat log")

        def set_default(obj: Any) -> Any:
            if isinstance(obj, set):
                return list(obj)
            return obj

        device_registry = dr.async_get(self.hass)

        payload["query"] = user_messages[-1]["content"]
        payload["agent_id"] = user_input.agent_id
        payload["device_id"] = user_input.device_id
        payload["device_info"] = (
            (
                device.dict_repr
                if (device := device_registry.async_get(user_input.device_id))
                else None
            )
            if user_input.device_id
            else None
        )
        payload["exposed_entities"] = self._get_home_structure_with_exposed_entities()
        payload["area"] = self._get_current_area(user_input.as_llm_context(DOMAIN))
        payload["language"] = user_input.language
        user = (
            await self.hass.auth.async_get_user(user_input.context.user_id)
            if user_input.context.user_id
            else None
        )
        payload["user_id"] = user_input.context.user_id
        payload["user_name"] = user.name if user else None

        output_field: str = self._subentry.data.get(
            CONF_OUTPUT_FIELD, DEFAULT_OUTPUT_FIELD
        )

        for _iteration in range(MAX_TOOL_ITERATIONS):
            if self._streaming_enabled:
                async for _ in chat_log.async_add_delta_content_stream(
                    self.entity_id,
                    self._transform_webhook_stream(payload),
                ):
                    pass
            else:
                result = await self._send_payload(payload, allow_tool_only=True)
                reply = result.get(output_field)
                tool_calls = _parse_tool_calls(result.get("tool_calls"))
                async for _ in chat_log.async_add_assistant_content(
                    conversation.AssistantContent(
                        agent_id=self.entity_id,
                        content=reply,
                        tool_calls=tool_calls or None,
                    )
                ):
                    pass

            if not chat_log.unresponded_tool_results:
                break

            payload = self._build_payload(chat_log, include_last=True)
            payload["query"] = user_messages[-1]["content"]
            payload["agent_id"] = user_input.agent_id
            payload["device_id"] = user_input.device_id
            payload["device_info"] = (
                (
                    device.dict_repr
                    if (device := device_registry.async_get(user_input.device_id))
                    else None
                )
                if user_input.device_id
                else None
            )
            payload["exposed_entities"] = json.dumps(
                self._get_exposed_entities(), default=set_default
            )
            payload["language"] = user_input.language
            payload["user_id"] = user_input.context.user_id
            payload["user_name"] = user.name if user else None
        else:
            raise HomeAssistantError(
                f"Webhook tool call loop exceeded {MAX_TOOL_ITERATIONS} iterations"
            )

    async def _transform_webhook_stream(
        self, payload: WebhookConversationPayload
    ) -> AsyncIterator[conversation.AssistantContentDeltaDict]:
        """Transform webhook streaming content into HA format."""
        yield {"role": "assistant"}

        async for chunk_data in self._send_payload_streaming(payload):
            _LOGGER.debug("Webhook streaming response: %s", chunk_data)
            if chunk_data.get("type") == "item" and "content" in chunk_data:
                yield {"content": chunk_data["content"]}
            elif chunk_data.get("type") == "tool_calls" and "tool_calls" in chunk_data:
                tool_calls = _parse_tool_calls(chunk_data["tool_calls"])
                if tool_calls:
                    yield {"tool_calls": tool_calls}

    def _get_exposed_entities(self) -> list[dict[str, Any]]:
        states = [
            state
            for state in self.hass.states.async_all()
            if async_should_expose(self.hass, conversation.DOMAIN, state.entity_id)
        ]
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        area_registry = ar.async_get(self.hass)
        exposed_entities: list[dict[str, Any]] = []

        for state in states:
            entity_id = state.entity_id
            entity = entity_registry.async_get(entity_id)

            aliases: list[str] = []
            if entity and entity.aliases:
                aliases = [
                    state.name if isinstance(a, er.ComputedNameType) else a
                    for a in entity.aliases
                ]

            area_id = None
            area_name = None

            if entity and entity.area_id:
                area_id = entity.area_id
                area = area_registry.async_get_area(area_id)
                if area:
                    area_name = area.name
            elif entity and entity.device_id:
                device = device_registry.async_get(entity.device_id)
                if device and device.area_id:
                    area_id = device.area_id
                    area = area_registry.async_get_area(area_id)
                    if area:
                        area_name = area.name

            exposed_entities.append(
                {
                    "entity_id": entity_id,
                    "name": state.name,
                    "state": state.state,
                    "aliases": aliases,
                    "area_id": area_id,
                    "area_name": area_name,
                }
            )
        return exposed_entities


def _parse_tool_calls(
    raw_tool_calls: list[dict[str, Any]] | None,
) -> list[llm.ToolInput] | None:
    """Parse tool calls from webhook response into ToolInput objects."""
    if not raw_tool_calls:
        return None
    return [
        llm.ToolInput(
            tool_name=tool_call["name"],
            tool_args=tool_call.get("arguments", {}),
            id=tool_call.get("id", ""),
        )
        for tool_call in raw_tool_calls
        if "name" in tool_call
    ] or None

    def _get_current_area(self, llm_context: str) -> str | None:
        area: ar.AreaEntry | None = None
        if llm_context.device_id:
            device_reg = dr.async_get(self.hass)
            device = device_reg.async_get(llm_context.device_id)

            if device:
                area_reg = ar.async_get(self.hass)
                area = area_reg.async_get_area(device.area_id)

        if area:
            return area.name
        return None

    def _get_home_structure_with_exposed_entities(
        self,
        include_state: bool = True,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        start = time.perf_counter()
        """Get exposed entities.

        Splits out calendars and scripts.
        """
        area_registry = ar.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        floor_registry = fr.async_get(self.hass)
        interesting_attributes = {
            "temperature",
            "current_temperature",
            "brightness",
            "percentage",
            "volume_level",
            "media_title",
        }

        data: dict[str, dict[str, Any]] = {
            CALENDAR_DOMAIN: {},
        }

        ignored: dict[str, dict[str, Any]] = {
            SCRIPT_DOMAIN: {},
        }

        floors_dict: dict[str, dict[str, Any]] = {}
        rooms_dict: dict[str, dict[str, Any]] = {}

        # Hilfsstruktur: floors[floor_id][area_id] -> list[devices]
        floors_devices: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )

        entities_list: list[dict[str, Any]] = []

        for state in sorted(self.hass.states.async_all(), key=attrgetter("name")):
            if not async_should_expose(self.hass, conversation.DOMAIN, state.entity_id):
                continue

            entity_entry = entity_registry.async_get(state.entity_id)
            names = [state.name]
            area_entry = None
            _LOGGER.info(
                "Entity %s is exposed:",
                state.name,
            )

            if entity_entry is not None:
                names.extend(entity_entry.aliases)

                # 1. Area direkt an der Entity
                if entity_entry.area_id:
                    area_entry = area_registry.async_get_area(entity_entry.area_id)
                # 2. andernfalls Area über Device
                elif entity_entry.device_id and (
                    device := device_registry.async_get(entity_entry.device_id)
                ):
                    if device.area_id:
                        area_entry = area_registry.async_get_area(device.area_id)

            info: dict[str, Any] = {
                "entity_id": state.entity_id,
                "names": ", ".join(names),
                "domain": state.domain,
            }

            if include_state:
                info["state"] = state.state

                if state.attributes.get("device_class") == "timestamp" and state.state:
                    if (parsed_utc := dt_util.parse_datetime(state.state)) is not None:
                        info["state"] = dt_util.as_local(parsed_utc).isoformat()

            if include_state and (
                attributes := {
                    attr_name: (
                        str(attr_value)
                        if isinstance(attr_value, (Enum, Decimal, int))
                        else attr_value
                    )
                    for attr_name, attr_value in state.attributes.items()
                    if attr_name in interesting_attributes
                }
            ):
                info["attributes"] = attributes

            # Area- / Floor-Infos auflösen
            if area_entry is not None:
                area_id = area_entry.id
                area_name = area_entry.name
                area_aliases = list(area_entry.aliases)

                # Room-Metadaten speichern (einmalig pro area_id)
                if area_id not in rooms_dict:
                    rooms_dict[area_id] = {
                        "id": area_id,
                        "name": area_name,
                        "aliases": area_aliases,
                    }

                floor_id = area_entry.floor_id  # kann None sein
                if floor_id is not None:
                    floor_entry = floor_registry.async_get_floor(floor_id)
                    if floor_entry is not None:
                        # Floor-Metadaten speichern (einmalig pro floor_id)
                        if floor_id not in floors_dict:
                            floors_dict[floor_id] = {
                                "id": floor_id,
                                "name": floor_entry.name,
                                "aliases": list(floor_entry.aliases),
                                "level": floor_entry.level,
                            }

                        # Device dem Floor/Room zuordnen
                        floors_devices[floor_id][area_id].append(info)
                else:
                    # Area ohne Floor: du kannst hier entweder einen speziellen Floor
                    # wie "Unassigned" anlegen oder sie ignorieren
                    pass

            entities_list.append(info)

        # Jetzt hierarchische Struktur bauen
        home: dict[str, Any] = {"floors": []}

        for floor_id, floor_meta in floors_dict.items():
            floor_obj = {
                "id": floor_meta["id"],
                "name": floor_meta["name"],
                "aliases": floor_meta.get("aliases", []),
                "level": floor_meta.get("level"),
                "rooms": [],
            }

            rooms_for_floor = floors_devices.get(floor_id, {})
            for area_id, devices in rooms_for_floor.items():
                room_meta = rooms_dict.get(
                    area_id, {"id": area_id, "name": area_id, "aliases": []}
                )
                room_obj = {
                    "id": room_meta["id"],
                    "name": room_meta["name"],
                    "aliases": room_meta.get("aliases", []),
                    "devices": devices,
                }
                # Räume innerhalb der Etage sortieren (optional)
                floor_obj["rooms"].append(room_obj)

            floor_obj["rooms"].sort(key=lambda r: r["name"])
            home["floors"].append(floor_obj)

        # Etagen sortieren, z.B. nach level, fallback Name
        home["floors"].sort(
            key=lambda f: (f.get("level") is None, f.get("level", 0), f["name"])
        )

        # JSON für dein System Prompt
        json_output = json.dumps(home, ensure_ascii=False, indent=2)

        _LOGGER.info(
            "get exposed entities time to take %s:",
            time.perf_counter() - start,
        )
        return json_output
