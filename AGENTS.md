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
- `whisper_state.py` — Whisper-Zustand pro `conversation_id` (hassmic-Sensor → TTS-Flag; einzige austauschbare Stelle für künftigen `tts_options`-Transport)
- `entity.py` — gemeinsame Basis (Auth, Payload-Senden, Streaming)
- `models.py` — Typdefinitionen aller Payloads (Änderungen hier zuerst prüfen)

## Die drei Webhook-Endpoints (Client-Seite)

### 1. Conversation / LLM-Agent (`conversation.py`)
- POST JSON `WebhookConversationPayload` mit `query`, `messages`, `exposed_entities` (Haus-Struktur inkl. Aliases), `area`, `language`, `device_info`, `profile`. Der System-Prompt wird ausschließlich aus dem Backend-Profil geladen (kein `system_prompt`-Feld mehr im Payload).
- Antwort: JSON mit Feld `output_field` (Default `"output"`) — oder Streaming als JSON-Lines mit `{"type":"item","content":...}`.
- Tool-Calls in der Webhook-Antwort werden **ignoriert** (Review S1): HA-Aktionen laufen ausschließlich über die MCP-Tools des my-jarvis-Backends; ein Rücklauf-Loop existiert nicht mehr.

### 2. STT (`stt.py`)
- HTTP: POST `WebhookSTTRequestPayload` mit base64-Audio (`binary_objects`-Schema).
- ODER WebSocket (URL beginnt mit `ws://`/`wss://`): erst Metadaten-JSON, dann Binary-Chunks, dann `{"type":"eof"}`; Antwort als JSON.
- Transkript steht im Antwortfeld `output_field`.

### 3. TTS (`tts.py`)
- POST `WebhookTTSRequestPayload` `{text, language, voice, voice_id, whisper}`.
- Antwort: **rohe Audio-Bytes**, `Content-Type` muss `wav` oder `mp3` sein — sonst Fehler.
- **Whisper-Modus** (`whisper: true` = echtes Flüstern): Das Flag kommt entweder
  explizit aus `tts.speak` (`options: {"whisper": true}`) oder aus dem
  hassmic-Sensor (`binary_sensor.*_last_request_whispered`, echo-dot-assist) über
  den `WhisperStateStore` (`whisper_state.py`): `conversation.py` merkt pro
  `conversation_id` (über `user_input.satellite_id` → Entity-Registry → Device →
  Sensor), `tts.py` liest es über `current_session.conversation_id` und sendet es
  im Payload. Strikt fail-closed: `true` nur bei Sensor `on` **und** Zustand
  höchstens `WHISPER_TTL_SECONDS` (30 s, zentrale Konstante in
  `whisper_state.py`) alt; unbekannte device_id, fehlender Sensor, veralteter
  Zustand oder fehlender Session-Kontext → `false`. Store-Einträge laufen nach
  derselben TTL ab; `consume()` poppt genau einmal (in `async_get_tts_audio`),
  `peek()`/`default_options` sind side-effect-frei. Cache-Hinweis: Explizite
  `tts.speak`-Optionen trennen den HA-Cache-Key, der Sensor-Store-Pfad nicht —
  Kollision nur bei wortgleichen Antworten (Residual-Risiko bis `tts_options`
  pro Run). Voraussetzung: hassmic ≥ PR #180 (ESPHome-Modus,
  `whisper-static`-Modell geladen).

## Stolperfallen

- Streaming antwortet in JSON-Lines; nach einem `"end"`-Event NICHT abbrechen, bis der Stream schließt (n8n sendet mehrere begin/end-Blöcke bei Tools).
- Entity-/Area-/Floor-Aliase aus den HA-Registries sind **Python-Listen** — kein `.filter()`/`.map()` (war schon mal ein Bug).
- Optional Basic Auth pro Subentry konfigurierbar (`entity.py`).

## Referenzen (Home Assistant Core)

- https://github.com/home-assistant/core
- Plattform-Implementierungen: `homeassistant/components/{conversation,stt,tts,ai_task}/`
- Registries: `homeassistant/helpers/{entity,device,area,floor}_registry.py`
