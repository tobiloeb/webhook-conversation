# Webhook Conversation for MyJarvis

[![My Home Assistant](https://img.shields.io/badge/Home%20Assistant-%2341BDF5.svg?style=flat&logo=home-assistant&label=My)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tobiloeb&repository=webhook-conversation&category=integration)

![GitHub License](https://img.shields.io/github/license/tobiloeb/webhook-conversation)

> [!NOTE]
> This integration requires Home Assistant `>=2026.4`.

_Integration, um Home Assistant an das [my-jarvis Backend](https://github.com/tobiloeb/my-jarvis) anzubinden._

**Diese Integration erweitert die Home-Assistant-Pipeline um my-jarvis: Conversation-Agent, AI Tasks, Speech-to-Text und Text-to-Speech werden vom my-jarvis-Server bereitgestellt. Home Assistant spricht dabei die HTTP-/WebSocket-Endpoints des Backends direkt an — die Integration ist fest an dieses Backend gebunden (siehe [my-jarvis](https://github.com/tobiloeb/my-jarvis)).**

## Features

- 🤖 Conversation-Agent: LLM-Interaktionen via `POST /api/agent/prompt` (Streaming)
- 🧩 AI Tasks via denselben Endpoint, mit strukturierten Ausgaben (JSON Schema) und Dateianhängen
- 💬 Text-to-Speech (TTS) via `POST /api/tts` mit Stimmen-Katalog des Backends (`GET /api/tts/voices`)
- 🎤 Speech-to-Text (STT) via WebSocket `ws(s)://…/ws/audio` (Audio-Streaming) oder HTTP-POST
- 📎 Support für Dateianhänge in AI Tasks (Bilder, Dokumente etc.)
- 📡 Sendet Gesprächskontext und die exponierten Entities (Hausstruktur: Etagen, Räume, Geräte) an das Backend
- 🏠 Nahtlose Integration in die Voice-Assistant-Pipelines von Home Assistant
- 🔧 Konfigurierbare Webhook-URLs und Ausgabefelder pro Subentry
- ⏱️ Konfigurierbarer Timeout für langlaufende Anfragen (1–300 Sekunden)
- 🚀 Response-Streaming für Echtzeit-Antworten

## Architektur

```
Home Assistant (diese Integration)          my-jarvis Backend
───────────────────────────────────          ─────────────────────────
Conversation / AI Task  ──── POST ─────────► /api/agent/prompt (NDJSON-Stream)
Profile-Auswahl         ◄──── GET ────────── /api/profiles
STT (Streaming)         ──── WS ───────────► /ws/audio
STT (HTTP-Fallback)     ──── POST ─────────► <konfigurierte URL>
TTS                     ──── POST ─────────► /api/tts
TTS-Stimmen-Auswahl     ◄──── GET ────────── /api/tts/voices
```

## Installation

### HACS (Recommended)

> [!NOTE]
> **Quick Install**: Click the "My Home Assistant" badge at the top of this README for one-click installation via HACS.

1. Make sure [HACS](https://hacs.xyz/) is installed
2. Add this repository as a custom repository in HACS:
   - Go to HACS → ⋮ → Custom repositories
   - Add `https://github.com/tobiloeb/webhook-conversation` with type `Integration`
3. Search for "Webhook Conversation for MyJarvis" in HACS and install it
4. Restart Home Assistant

> [!NOTE]
> Dieses Repository installiert direkt aus dem `master`-Branch, sodass jeder Push auf `master` von HACS als Update erkannt wird.

### Manual Installation

1. Clone or download this repository
2. Copy the `custom_components/myjarvis_webhook_conversation` folder to your `custom_components` directory
3. Restart Home Assistant

## Configuration

### Home Assistant Setup

The setup process consists of two steps:

#### Step 1: Create the Integration Entry

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration** and search for "Webhook Conversation for MyJarvis"
3. Add the integration (no configuration options are required at this stage)

#### Step 2: Add Conversation Agents and AI Tasks

After the integration is added, you'll see the "Webhook Conversation for MyJarvis" integration on your integrations page. From there:

1. **Add Conversation Agent**: Click the **"Add Entry"** button on the integration page and select **"Conversation Agent"** to create a new conversation agent. Configure it with:
   - **Webhook URL**: The URL of the my-jarvis endpoint, e.g. `http://<myjarvis-host>:8001/api/agent/prompt`
   - **Output Field**: The field name in the response containing the reply (default: "output")
   - **Timeout**: The timeout in seconds for waiting for a response (default: 30 seconds, range: 1-300 seconds)
   - **Enable Response Streaming**: Enable real-time streaming of responses as they are generated (default: enabled)
   - **Profile**: The agent profile provided by the backend (`GET /api/profiles`). The profile determines the system prompt and which tools and skills are available — the prompt is maintained exclusively in the backend.

2. **Add AI Task**: Click the **"Add Entry"** button on the integration page and select **"AI Task"** to create a new AI task handler. Configure it with:
   - **Webhook URL**: The URL of the my-jarvis endpoint, e.g. `http://<myjarvis-host>:8001/api/agent/prompt`
   - **Output Field**: The field name in the response containing the reply (default: "output")
   - **Timeout**: The timeout in seconds for waiting for a response (default: 30 seconds, range: 1-300 seconds)
   - **Enable Response Streaming**: Enable real-time streaming of responses as they are generated (default: enabled)
   - **Profile**: The agent profile provided by the backend

3. **Add TTS (Text-to-Speech)**: Click the **"Add Entry"** button on the integration page and select **"TTS"** to create a new text-to-speech service. Configure it with:
   - **Webhook URL**: The URL of the my-jarvis TTS endpoint, e.g. `http://<myjarvis-host>:8001/api/tts`
   - **Supported Languages**: List of language codes the TTS service supports
   - **Voice**: Dropdown with all voices offered by the backend (`GET /api/tts/voices`), labeled with provider and voice name (e.g. "Gemini – Charon"). The backend maps the selected voice to the correct provider, model and voice.
   - **Timeout**: The timeout in seconds for waiting for audio response (default: 30 seconds, range: 1-300 seconds)
   - **Authentication**: Optional HTTP basic authentication for securing the endpoint

4. **Add STT (Speech-to-Text)**: Click the **"Add Entry"** button on the integration page and select **"STT"** to create a new speech-to-text service. Configure it with:
   - **Webhook URL**: The URL of the my-jarvis audio endpoint, e.g. `ws://<myjarvis-host>:8001/ws/audio` (WebSocket streaming) or an HTTP endpoint for the non-streaming fallback
   - **Timeout**: The timeout in seconds for waiting for transcription response (default: 30 seconds, range: 1-300 seconds)
   - **Supported Languages**: List of supported language codes (e.g., "en-US", "de-DE", "fr-FR")
   - **Output Field**: The field name in the response containing the transcribed text (default: "output")
   - **Authentication**: Optional HTTP basic authentication for securing the endpoint

> [!NOTE]
> You can add multiple conversation agents, AI task handlers, TTS services, and STT services by repeating steps 2-4. Each can be configured with different webhook URLs and settings to support various use cases.

### my-jarvis Backend Setup

Die Integration ist fest an das [my-jarvis Backend](https://github.com/tobiloeb/my-jarvis) gebunden. Starte den Server (Details in der [my-jarvis README](https://github.com/tobiloeb/my-jarvis)) und trage die folgenden URLs in den Subentries ein:

| Subentry | Webhook URL |
| --- | --- |
| Conversation Agent | `http://<myjarvis-host>:8001/api/agent/prompt` |
| AI Task | `http://<myjarvis-host>:8001/api/agent/prompt` |
| TTS | `http://<myjarvis-host>:8001/api/tts` |
| STT | `ws://<myjarvis-host>:8001/ws/audio` |

Die Profile-Auswahl (`GET /api/profiles`) und der TTS-Stimmen-Katalog (`GET /api/tts/voices`) werden vom Backend bereitgestellt und im Konfigurationsdialog geladen. Der System-Prompt wird ausschließlich im Backend-Profil gepflegt — es gibt kein Prompt-Feld in der Konfiguration.

#### Input schema

##### For **conversations** and **AI tasks** (POST `/api/agent/prompt`)

```json
{
  "conversation_id": "abc123",
  "user_id": "user id from ha",
  "user_name": "John Doe",
  "language": "de-DE",
  "agent_id": "conversation.webhook_agent",
  "device_id": "satellite_device_id",
  "device_info": {
    "name": "Kitchen Voice Satellite",
    "manufacturer": "Raspberry Pi",
    "model": "Pi 4B"
  },
  "area": "Living Room",
  "messages": [
    {
      "role": "assistant|system|tool_result|user",
      "content": "message content"
    }
  ],
  "query": "latest user message",
  "exposed_entities": "{\"floors\": [{\"id\": \"ground\", \"name\": \"Ground Floor\", \"aliases\": [], \"level\": 0, \"rooms\": [{\"id\": \"living_room\", \"name\": \"Living Room\", \"aliases\": [\"wohnzimmer\"], \"devices\": [{\"entity_id\": \"light.living_room\", \"names\": \"Living Room Light\", \"domain\": \"light\"}]}]}]}",
  "profile": "default",
  "stream": true
}
```

> `exposed_entities` enthält die Hausstruktur der exponierten Entities (Etagen → Räume → Geräte, inkl. Aliases) als serialisierte JSON-Struktur.

##### Zusätzliche Felder für **AI tasks**

```json
{
  "query": "task instructions",
  "task_name": "task name",
  "structure": "json schema for output",
  "binary_objects": [
    {
      "name": "filename.jpg",
      "path": "/path/to/file",
      "mime_type": "image/jpeg",
      "data": "base64_encoded_file_content"
    }
  ]
}
```

```json
{
  "audio": {
    "name": "audio.wav",
    "path": "/path/to/audio.wav",
    "mime_type": "audio/wav",
    "data": "base64_encoded_audio_content"
  },
  "language": "en-US"
}
```

> [!NOTE]
> For **conversations**: The `device_id` and `device_info` fields are only set when the conversation was initiated via a voice satellite. The `language` field contains the language code (e.g., "de-DE") configured for the conversation. The `agent_id` field contains the entity ID of the conversation agent. The `area` field contains the name of the room the request originated from (voice satellite), if known. The `profile` field contains the conversation profile ID selected in the configuration (e.g. "default"); the system prompt is loaded from the backend profile — there is no `system_prompt` field in the payload.
>
> For **AI tasks**: The `binary_objects` field is only included when attachments are present in the AI task. The `structure` field is only included when a JSON schema is provided by the action call. The `task_name` field is only included when provided by the action call. Each attachment is converted to base64 format and includes metadata such as filename, file path, and MIME type. The `profile` field is sent here as well and determines the system prompt used for the task.
>
> **For TTS**: The `voice_id` field contains the selected voice identifier from the backend catalog (see `GET /api/tts/voices`) and is always sent. The legacy `voice` field is only sent by older configurations. The `whisper` field (boolean) is `true` when the user whispered at a voice satellite (hassmic sensor) or `tts.speak` was called with `options: {"whisper": true}`. The webhook should return audio data with an appropriate Content-Type header (e.g., "audio/wav" or "audio/mp3").
>
> For **STT** via http/https: The audio data is automatically converted to the appropriate format and encoded as base64. The `conversation_id` field is included when the STT request is part of a voice pipeline run, allowing you to correlate STT requests with their corresponding conversation calls. The endpoint should return a JSON response with the transcribed text in the configured output field (default: "output").
>
> For **STT** via ws/wss (e.g. `/ws/audio`): The websocket message sequence is:
> 1. a first **text** frame containing the JSON metadata shown above,
> 2. one or more **binary** frames containing the audio bytes,
> 3. a final **text** frame with `{"type": "eof"}` to mark the end of the audio stream,
> 4. a final **text** frame from the webhook containing the JSON response with the transcribed text in the configured output field (default: `output`).
> 
> The binary frames contain the audio payload only. For WAV/PCM-style input, the streamed bytes are **raw PCM samples** matching the provided `sample_rate`, `bit_rate`, and `channels` metadata, **not** a complete WAV file with container/header bytes. For other encoded formats, treat the binary frames as the actual encoded file bytes for that format. WebSocket webhook implementations should therefore decode the stream based on the metadata JSON and wait for the `eof` marker before finalizing transcription.

## Authentication

The integration supports **basic HTTP authentication** for secure communication with the my-jarvis backend (or any other compatible endpoint). This ensures that only authorized requests can access your endpoints.

### Configuration

To enable basic HTTP authentication:

1. In the integration configuration, provide:
   - **Username**: Your HTTP authentication username
   - **Password**: Your HTTP authentication password
2. The integration will automatically include the proper authentication headers in all requests

### Backend Authentication Setup

The my-jarvis backend can optionally require basic authentication for its endpoints. Configure the same username and password on both sides — the integration will then authenticate automatically with every request (including the WebSocket connection for STT).

> [!IMPORTANT]
> Basic HTTP authentication credentials are transmitted with every request. Always use HTTPS/WSS to ensure credentials are encrypted in transit.

## Usage

### Voice Assistant Pipeline Setup

To use my-jarvis with voice assistants, you need to create a voice assistant pipeline:

1. Go to **Settings** → **Voice assistants**
2. Click **Add Assistant**
3. Configure your pipeline:
   - **Name**: Give your pipeline a descriptive name (e.g., "Webhook Assistant")
   - **Language**: Select your preferred language
   - **Speech-to-text**: Choose your preferred STT engine (e.g., the my-jarvis STT service via `/ws/audio`)
   - **Conversation agent**: Select your my-jarvis conversation agent from the dropdown
   - **Text-to-speech**: Choose your preferred TTS engine (e.g., the my-jarvis TTS service)
   - **Wake word**: Optionally configure a wake word engine
4. Click **Create** to save your pipeline
5. Set this pipeline as the default for voice assistants or assign it to specific devices

## Response Streaming

The webhook conversation integration supports **response streaming** for real-time conversation responses. When enabled, responses are streamed as they are generated, providing a more natural and responsive conversation experience.

### How Response Streaming Works

When response streaming is enabled:

1. **Real-time Updates**: Responses appear in real-time as they are generated by the backend
2. **Improved User Experience**: Users see responses being typed out naturally, similar to ChatGPT-style interfaces
3. **Better Performance**: No need to wait for the complete response before displaying it to the user

### Response Format for Streaming

When streaming is enabled, the endpoint should return responses as **NDJSON** (one JSON object per line) instead of a single JSON response. The expected format is:

```json
{"type": "item", "content": "First part of the response"}
{"type": "item", "content": " continues here"}
{"type": "item", "content": " and more content"}
{"type": "end"}
```

The my-jarvis backend (`/api/agent/prompt`) streams exactly in this format (with `{"type": "done"}` / `{"type": "error", "message": "…"}` as terminator events). The integration keeps reading until the stream closes, since the backend can emit multiple begin/end blocks when tools are used.

> [!TIP]
> Streaming is enabled by default. Disable it in the subentry options if your endpoint only returns a single JSON response (with the configured output field).

## Attachment Support

The webhook conversation integration supports file attachments in AI Tasks, allowing you to send images, documents, and other files to the my-jarvis backend for processing.

### How Attachments Work

When an AI Task includes attachments, they are automatically:

- Read from the file system
- Encoded as base64 strings
- Included in the `binary_objects` field of the webhook payload

### Attachment Data Structure

Each attachment in the `binary_objects` array contains:

- `name`: The filename or media content ID
- `path`: The full file path on the system
- `mime_type`: The MIME type of the file (e.g., "image/jpeg", "application/pdf")
- `data`: The base64-encoded file content

### Verarbeitung von Anhängen im Backend

Das my-jarvis-Backend verarbeitet die `binary_objects` direkt (z. B. für Bildverarbeitung im Agenten). Falls du ein eigenes Backend anbindest:

1. **`binary_objects`-Array auslesen**: Alle Anhänge stehen dort zur Verfügung
2. **Einzelne Dateien verarbeiten**: Schleife über das Array oder Zugriff per Index
3. **Base64 dekodieren**: Die `data`-Felder enthalten den base64-kodierten Dateiinhalt
4. **Dateityp beachten**: Das `mime_type`-Feld bestimmt die Verarbeitung

> [!TIP]
> Die AI-Task-Ausgabe sollte dem JSON-Schema aus dem `structure`-Feld entsprechen. Tool-Calls in der Webhook-Antwort werden ignoriert — Home-Assistant-Aktionen laufen ausschließlich über die MCP-Tools des my-jarvis-Backends.

## Speech-to-Text (STT) Support

The integration forwards voice input to my-jarvis for speech-to-text transcription. The backend streams the audio via WebSocket (`/ws/audio`, with Google STT and speaker recognition) and returns the transcript, which is then passed to the conversation agent.

### How STT Works

When configured, the STT service:

1. **Receives audio data**: Home Assistant captures voice input from microphones or voice satellites
2. **Processes via backend**: The audio is streamed to my-jarvis (`ws://…/ws/audio`) or sent as a base64 POST request (HTTP fallback)
3. **Returns transcribed text**: The transcript is returned as a JSON response
4. **Integrates with conversation**: The transcribed text is passed to the conversation agent for processing

### STT Configuration

When adding an STT subentry, you can configure:

- **Webhook URL**: The endpoint handling transcription requests — `ws://<myjarvis-host>:8001/ws/audio` for streaming, or an HTTP URL for the non-streaming fallback
- **Supported Languages**: List of language codes your STT service supports (e.g., "en-US", "de-DE", "fr-FR")
- **Output Field**: The field name in the response containing the transcribed text (default: "output")
- **Timeout**: How long to wait for transcription (default: 30 seconds)
- **Authentication**: HTTP basic authentication for securing the endpoint

### STT Request Format (HTTP fallback)

The endpoint will receive POST requests with this JSON payload:

```json
{
  "audio": {
    "name": "audio.wav",
    "path": "/path/to/audio.wav",
    "mime_type": "audio/wav",
    "data": "base64_encoded_audio_content"
  },
  "language": "en-US"
}
```

### STT Response Format

The endpoint should return a JSON response with the transcribed text:

```json
{
  "output": "Hello, this is the transcribed text from the audio"
}
```

### Usage in Voice Assistants

Once configured, your STT service will appear in Home Assistant's STT service list and can be used:

1. **Voice Assistant Pipelines**: Select your my-jarvis STT service in voice assistant pipeline configuration
2. **Voice Satellites**: Use with Wyoming satellite devices or other voice input devices
3. **Mobile Apps**: Compatible with Home Assistant mobile app voice input

> [!TIP]
> For the HTTP fallback, the integration automatically converts raw audio streams to properly formatted WAV files with headers before encoding to base64. In WebSocket mode the binary frames contain raw PCM samples matching the metadata (see the note on the STT websocket protocol above) — my-jarvis decodes the stream accordingly.

## Text-to-Speech (TTS) Support

The integration synthesizes speech via my-jarvis. The backend maps the selected `voice_id` to the configured provider (Gemini, ElevenLabs, Microsoft, Mistral, or a local OpenAI-compatible TTS server) and returns the audio.

### How TTS Works

When configured, the TTS service:

1. **Receives TTS requests**: Home Assistant sends text that needs to be synthesized to speech
2. **Processes via backend**: my-jarvis generates the audio with the configured provider
3. **Returns audio data**: The endpoint returns audio data in WAV or MP3 format
4. **Plays in Home Assistant**: The audio is played through Home Assistant's audio system

### TTS Configuration

When adding a TTS subentry, you can configure:

- **Webhook URL**: The endpoint handling TTS synthesis requests (`http://<myjarvis-host>:8001/api/tts`)
- **Supported Languages**: List of language codes your TTS service supports (e.g., "en-US", "de-DE", "fr-FR")
- **Voice**: The voice to use, selected from a dropdown fetched from the backend's `GET /api/tts/voices` endpoint. Each TTS subentry can use a different voice — add multiple TTS subentries to use different voices in different voice pipelines.
- **Timeout**: How long to wait for audio generation (default: 30 seconds)
- **Authentication**: HTTP basic authentication for securing the endpoint

### TTS Request Format

The endpoint will receive POST requests with this JSON payload:

```json
{
  "text": "Hello, this is the text to be synthesized",
  "language": "en-US",
  "voice": "optional_voice_name",
  "voice_id": "optional_voice_id_from_catalog",
  "whisper": false
}
```

### Whisper Mode

If the user whispers at a voice satellite (echo-dot-assist/hassmic), the
integration detects the satellite's `binary_sensor.*_last_request_whispered`
sensor and sends `"whisper": true` so the backend can synthesize real whispered
speech. The flag is stored per `conversation_id` in `whisper_state.py` and read
back by the TTS entity via the current chat session. It is also exposed as a TTS
option: `tts.speak` with `options: {"whisper": true}` whispers explicitly (an
explicit option always wins over the sensor). Whisper is strictly fail-closed:
it is only `true` when the sensor state is `on` **and** that state is at most
`WHISPER_TTL_SECONDS` (30 s) old; if the device cannot be resolved, the sensor
is missing, the state is unknown/stale, or the session context is absent, the
flag is `false` (normal speech). Store entries expire after the same 30 s TTL,
so answers slower than that are spoken normally. If the HA TTS cache collides
for identical reply text in both modes (the sensor-derived flag is not part of
the cache key; only explicit `tts.speak` options are), the wrong variant may be
played back — a known residual risk until per-run `tts_options` are implemented.
Requirement: hassmic ≥ PR #180 (ESPHome mode with the
`whisper-static` model loaded).

### TTS Response Format

The endpoint should return audio data with the appropriate Content-Type header:

- **Content-Type**: Must be `audio/wav` or `audio/mp3`
- **Body**: Raw audio data in the specified format

### Usage in Voice Assistants

Once configured, your TTS webhook service will appear in Home Assistant's TTS service list and can be used:

1. **Voice Assistant Pipelines**: Select your my-jarvis TTS service in voice assistant pipeline configuration
2. **TTS Service Calls**: Use the `tts.speak` service with your my-jarvis TTS entity
3. **Media Players**: The generated audio can be played on any media player device

### Supported Audio Formats

The TTS webhook integration supports:

- **WAV**: Uncompressed audio format (`audio/wav`)
- **MP3**: Compressed audio format (`audio/mp3`)

> [!TIP]
> For best performance, consider using MP3 format to reduce bandwidth usage, especially for longer text synthesis. Make sure the endpoint sets the correct Content-Type header to match the audio format being returned.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

- 🐛 [Report issues](https://github.com/tobiloeb/webhook-conversation/issues)

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.
