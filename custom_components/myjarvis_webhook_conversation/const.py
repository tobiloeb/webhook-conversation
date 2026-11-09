"Constants for the webhook conversation integration."

from enum import StrEnum

from homeassistant.helpers import llm

DOMAIN = "myjarvis_webhook_conversation"
MANUFACTURER = "Webhook Conversation for MyJarvis"

# Main config entry constants
CONF_NAME = "name"
DEFAULT_TITLE = "Webhook Conversation for MyJarvis"

# Subentry names
DEFAULT_CONVERSATION_NAME = "Webhook Conversation for MyJarvis"
DEFAULT_AI_TASK_NAME = "MyJarvis AI Task"
DEFAULT_TTS_NAME = "MyJarvis TTS"
DEFAULT_STT_NAME = "MyJarvis STT"

# Subentry configuration constants
CONF_WEBHOOK_URL = "webhook_url"
CONF_OUTPUT_FIELD = "output_field"
CONF_TIMEOUT = "timeout"
CONF_ENABLE_STREAMING = "enable_streaming"
CONF_PROMPT = "prompt"
CONF_PROFILE = "profile"
CONF_AUTH_TYPE = "auth_type"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SUPPORTED_LANGUAGES = "supported_languages"
CONF_VOICES = "voices"
CONF_VOICE = "voice"

# Defaults for subentries
DEFAULT_OUTPUT_FIELD = "output"
DEFAULT_TIMEOUT = 30
DEFAULT_ENABLE_STREAMING = True
DEFAULT_PROMPT = llm.DEFAULT_INSTRUCTIONS_PROMPT
DEFAULT_PROFILE = "default"
DEFAULT_SUPPORTED_LANGUAGES = ["en-US"]


class AuthType(StrEnum):
    """Authentication types for webhook requests."""

    NONE = "none"
    BASIC = "basic_auth"


DEFAULT_AUTH_TYPE = AuthType.NONE

# Recommended options for subentries
RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_OUTPUT_FIELD: DEFAULT_OUTPUT_FIELD,
    CONF_PROMPT: DEFAULT_PROMPT,
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
    CONF_ENABLE_STREAMING: DEFAULT_ENABLE_STREAMING,
    CONF_AUTH_TYPE: DEFAULT_AUTH_TYPE,
}

# Keine feste Voice-Vorgabe: Die Stimme wird im Konfigurations-Dialog aus dem
# Katalog des Backends gewählt (siehe GET /api/tts/voices).
RECOMMENDED_TTS_OPTIONS = {
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
    CONF_AUTH_TYPE: DEFAULT_AUTH_TYPE,
    CONF_SUPPORTED_LANGUAGES: DEFAULT_SUPPORTED_LANGUAGES,
}

RECOMMENDED_AI_TASK_OPTIONS = {
    CONF_OUTPUT_FIELD: DEFAULT_OUTPUT_FIELD,
    CONF_PROMPT: DEFAULT_PROMPT,
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
    CONF_ENABLE_STREAMING: DEFAULT_ENABLE_STREAMING,
    CONF_AUTH_TYPE: DEFAULT_AUTH_TYPE,
}

RECOMMENDED_STT_OPTIONS = {
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
    CONF_AUTH_TYPE: DEFAULT_AUTH_TYPE,
    CONF_SUPPORTED_LANGUAGES: DEFAULT_SUPPORTED_LANGUAGES,
}

# Legacy constants for backward compatibility
CONF_AI_TASK_WEBHOOK_URL = "ai_task_webhook_url"
