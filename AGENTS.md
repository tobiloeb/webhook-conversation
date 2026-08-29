# AGENTS.md

## Was ist das?

HACS-Integration für Home Assistant. Sie exponiert HAs Conversation-, AI-Task-, STT- und TTS-Plattformen als HTTP/WebSocket-Webhooks an einen externen Server (z. B. n8n oder das my-jarvis-Projekt).

## Backend: my-jarvis

Dieses Repo ist nur die HA-Seite. Der Server, den die Webhooks aufrufen, liegt in:

- Lokal: `C:\Users\Tobias\repos\my-jarvis`
- GitHub: `https://github.com/tobiloeb/my-jarvis`

Dort implementieren `src/jarvis_agent/server.py` die Ziel-Endpoints `/ws/audio` (STT), `/api/agent/prompt` (LLM) und `/api/tts`. Details stehen in der `AGENTS.md` des my-jarvis-Projekts.

## Code-Struktur

- `custom_components/myjarvis_webhook_conversation/` — die Integration (Setup über `__init__.py` + `config_flow.py`)
- `conversation.py`, `ai_task.py`, `stt.py`, `tts.py` — die vier Plattformen
- `entity.py` — gemeinsame Basis (Auth, Payload-Senden, Streaming)
- `models.py` — Typdefinitionen aller Payloads (Änderungen hier zuerst prüfen)

## Die drei Webhook-Endpoints (Client-Seite)

### 1. Conversation / LLM-Agent (`conversation.py`)
- POST JSON `WebhookConversationPayload` mit `query`, `messages`, `system_prompt`, `exposed_entities` (Haus-Struktur inkl. Aliases), `area`, `language`, `device_info`.
- Antwort: JSON mit Feld `output_field` (Default `"output"`) — oder Streaming als JSON-Lines mit `{"type":"item","content":...}`; optional `tool_calls`.
- Tool-Calls erzeugen einen Rücklauf-Loop (max. `MAX_TOOL_ITERATIONS` = 10).

### 2. STT (`stt.py`)
- HTTP: POST `WebhookSTTRequestPayload` mit base64-Audio (`binary_objects`-Schema).
- ODER WebSocket (URL beginnt mit `ws://`/`wss://`): erst Metadaten-JSON, dann Binary-Chunks, dann `{"type":"eof"}`; Antwort als JSON.
- Transkript steht im Antwortfeld `output_field`.

### 3. TTS (`tts.py`)
- POST `WebhookTTSRequestPayload` `{text, language, voice}`.
- Antwort: **rohe Audio-Bytes**, `Content-Type` muss `wav` oder `mp3` sein — sonst Fehler.

## Stolperfallen

- Streaming antwortet in JSON-Lines; nach einem `"end"`-Event NICHT abbrechen, bis der Stream schließt (n8n sendet mehrere begin/end-Blöcke bei Tools).
- Entity-/Area-/Floor-Aliase aus den HA-Registries sind **Python-Listen** — kein `.filter()`/`.map()` (war schon mal ein Bug).
- Optional Basic Auth pro Subentry konfigurierbar (`entity.py`).

## Referenzen (Home Assistant Core)

- https://github.com/home-assistant/core
- Plattform-Implementierungen: `homeassistant/components/{conversation,stt,tts,ai_task}/`
- Registries: `homeassistant/helpers/{entity,device,area,floor}_registry.py`
