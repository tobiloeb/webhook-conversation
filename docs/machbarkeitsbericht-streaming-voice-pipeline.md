# Machbarkeitsbericht: Streaming STT → LLM-Agent → TTS in `myjarvis_webhook_conversation`

> Stand: 2026-11-21
> Analysiert gegen: Home Assistant Core (`~/repos/core`, Snapshot 2026.10/2026.11) und die Integration `custom_components/myjarvis_webhook_conversation/`.

## 1. Ziel & Ausgangslage

**Wunsch:** Text-Streaming der KI-Antwort *und* direkt ein gekoppelter TTS-Stream, sodass "Ja, ich recherchiere das für dich" sofort hörbar wird — ohne Medien-Brüche, möglichst als Audio-Chunks zurück zum Satelliten.

**Kurzbefund:** Home Assistant unterstützt bereits genau diesen textseitigen Streaming-Pfad (`LLM-Delta → TTS-Input-Stream → chunked Audio`). Die Integration hat die Hälfte davon schon angefangen (`_attr_supports_streaming`, `async_add_delta_content_stream` in `conversation.py`). Was fehlt, ist:

1. eine Streaming-fähige TTS-Engine (`async_stream_tts_audio`) und
2. ein echter Audio-Ende-zu-Ende-Kanal zum Satelliten (in HA bisher eine *wachsende HTTP-URL*, keine Roh-PCM-Pipe).

## 2. Wie HA intern streamt (Befund aus `~/repos/core`)

Die Pipeline (`assist_pipeline/pipeline.py`) feuert Events:
`run-start → stt-start → stt-end → intent-start → intent-progress → intent-end → tts-start → tts-end → run-end`.
Es gibt **kein `tts-chunk`-Event** — Audio-Chunks laufen ausschließlich über die TTS-HTTP-/Satelliten-Ebene.

Der entscheidende Streaming-Mechanismus (`pipeline.py`, `chat_log_delta_listener`, ~Zeile 1126–1210):

- Jedes LLM-Delta landet in `chat_log` (`conversation/chat_log.py`, `async_add_delta_content_stream`); das löst `delta_listener` aus.
- Ab **>60 Zeichen** (Konstante `STREAM_RESPONSE_CHARS = 60`, `pipeline.py:105`) oder bei einem Tool-Call nach Text wird `INTENT_PROGRESS {"tts_start_streaming": true}` gesendet und `tts_stream.async_set_message_stream(...)` befüllt.
- **Bedingung:** `tts_stream.supports_streaming_input == True`, d. h. die TTS-Entity muss `async_stream_tts_audio` (`tts/entity.py`, `TTSAudioRequest.message_gen → TTSAudioResponse.data_gen`) überschreiben. Der Default in `TextToSpeechEntity` sammelt sonst den ganzen Text und gibt `(extension, bytes)` zurück (`legacy.py`).
- Ausgabe: `ResultStream.async_stream_result()` (`tts/__init__.py:555`) liefert Chunks lazily; `/api/tts_proxy/{token}` schreibt sie chunked in die HTTP-Response.

**Satz-Trennung:** PR home-assistant/core#184535 (merged, 2026.10) trennt aufeinanderfolgende Assistant-Messages im TTS-Input mit Leerzeichen. Offene Bugs, die den Use Case betreffen:

- home-assistant/core#187933 — Text vor einem Tool-Call wird erst nach Tool-Ende gesprochen; Fix `"\n\n"`-Flush in home-assistant/core#193007 (offen).
- home-assistant/core#179576 — ESPHome verwirft `chat_log_delta`s.
- home-assistant/core#184204 — ffmpeg-WAV-Probe ~0,6 s Zusatzlatenz.

**Satelliten-Seite:**

- Wyoming-Satelliten bekommen echte `AudioChunk`s lazy (`wyoming/assist_satellite.py`, `_stream_tts`).
- ESPHome-Satelliten (Voice PE) bekommen die URL via `INTENT_PROGRESS tts_start_streaming` und fetchen `/api/tts_proxy/...` — oder, bei `speaker:`-Konfiguration, Roh-Chunks via `VoiceAssistantAudio` (Proto id 106, Events `TTS_STREAM_START/END`). **Aber:** `esphome/assist_satellite.py`, `_stream_tts_audio`, liest den Stream dort aktuell mit `b"".join(...)` komplett ein, bevor er in 512-Sample-Chunks sendet. Das ist ein echter Latenz-Engpass, der nicht von HA-Seite (Custom Component) behoben werden kann.

**Aktive Entwicklungsrichtung (Nov 2026):**

- PR home-assistant/core#188223 "Add raw PCM audio streams to TTS result streams" (merged 2026-10-23): `tts.PcmFormat`, `ResultStream.async_set_audio_stream()`, `tts.async_create_audio_stream()`.
- PR home-assistant/core#188283 "Add audio input and output to conversation agents" (offen).

Das ist der offizielle Speech-to-Speech-Weg — genau die Schnittstelle, über die der Agent künftig direkt Audio in den TTS-Stream speisen könnte. **Vorbehalt:** Diese APIs sind sehr neu und noch im Fluss (im lokalen `~/repos/core`-Snapshot noch nicht vorhanden).

## 3. Was davon kann heute in dieser Integration genutzt werden?

**Bereits vorhanden (muss nur vervollständigt werden):**

- `conversation.py:68` setzt `_attr_supports_streaming` korrekt aus dem Config-Flag.
- `conversation.py:162–186` nutzt bereits `chat_log.async_add_delta_content_stream(self._transform_webhook_stream(payload))` — Text-Deltas werden also schon in den Chat-Log gestreamt. Damit wird automatisch `chat_log_delta_listener` und damit der `tts_start_streaming`-Pfad der Pipeline ausgelöst.

**Fehlt (Hauptgrund, warum es sich heute nicht "live" anfühlt):**

- `tts.py:99` implementiert nur `async_get_tts_audio` (Bytes-komplett). Ohne Override von `async_stream_tts_audio` ist `supports_streaming_input` False, und die Pipeline fällt auf "ganzer Text → eine Synthese" zurück. **Das ist die wichtigste Stellschraube in diesem Repo.**
- `models.py` hat für TTS nur ein `text`-Feld im Payload (`WebhookTTSRequestPayload`) — es braucht entweder einen zweiten Modus (Text-Deltas senden) oder einen kombinierten Endpunkt.

## 4. Empfohlene Umsetzung (drei Optionen, aufsteigend nach Aufwand/Latenz)

### Option A — "Low-hanging fruit" (empfohlen als erster Schritt, kein HA-Fork nötig)

1. **TTS-Entity streamingfähig machen:** In `tts.py` `async_stream_tts_audio(self, request: TTSAudioRequest) -> TTSAudioResponse` implementieren:
   - `request.message_gen` ist ein `AsyncGenerator[str]` (die Text-Deltas).
   - Pro Delta (oder satzweise gesammelt, ähnlich HA Cloud/ElevenLabs mit `sentence-stream`) einen Websocket-Request an my-jarvis `/api/tts` senden, der Audio-Chunks zurück gibt.
   - `data_gen()` yielded diese Bytes lazily als `TTSAudioResponse(extension, data_gen())`.
2. **In my-jarvis:** `/api/tts` erweitern zu `ws://.../api/tts/stream` mit `{"type":"text_chunk"}` rein → `{"type":"audio_chunk", "data": base64}` raus, plus `eof`. Analog zum bestehenden STT-Websocket.
3. **Voraussetzung:** Der Voice-Satellit muss den `tts_start_streaming`-Pfad unterstützen (Voice PE mit `media_player:` liefert die URL und spielt den wachsenden `/api/tts_proxy`-Stream ab). `tts_playback_start_timeout` in der ESPHome-Firmware prüfen (Bug siehe Abschnitt 5).

**Erwarteter Effekt:** "Ja, ich recherchiere das für dich" wird gesprochen, sobald die ersten ~60 Zeichen (bzw. der erste Satz) aus dem LLM-Stream da sind — unabhängig davon, ob die LLM-Recherche fertig ist.

**Einschränkung:** Ab der 60-Zeichen-Schwelle (`STREAM_RESPONSE_CHARS`), sonst kein Streaming. Für sehr kurze Antworten ("Ja") bleibt es blockierend — das ist HA-intern und nicht konfigurierbar.

### Option B — "Pre-Announce" als Latenz-Brücke (einfach, kombinierbar mit A)

- `VoiceAssistantAnnounceRequest.preannounce_media_id` (ESPHome-Proto id 119) bzw. das `assist_satellite`-Announcement-Feature nutzen, um einen kurzen Bestätigungs-Sound (z. B. "Hmm?") direkt beim `intent-start`-Zeitpunkt zu spielen, bevor die LLM-Response kommt.
- Umsetzung: über die `assist_satellite`-API oder als kurze TTS-Announcement-Action.
- Gut als UX-Booster, ersetzt aber nicht Option A.

### Option C — "Roh-Audio-Stream" / Speech-to-Speech (zukunftssicher, aber mit Vorbehalt)

- Über home-assistant/core#188223 / home-assistant/core#188283 (`ResultStream.async_set_audio_stream()`, `tts.async_create_audio_stream()`, `ConversationAudioOutput.async_set_audio_stream()`) könnte der my-jarvis-Agent bzw. der TTS-Provider künftig direkt PCM in den TTS-Stream speisen, ohne Text-Zwischenschritt. Eleganteste Vermeidung von Medien-Brüchen.
- **Vorbehalt:** Die API ist in HA 2026.10/2026.11 frisch und home-assistant/core#188283 ist noch offen (kann sich ändern). Nicht als Fundament für die erste Implementierung nehmen; die Architektur aber so wählen, dass der Umstieg leicht ist (z. B. `data_gen()` in Option A isolieren).
- Voraussetzung: Pipeline/Satelliten-Seite muss den Audio-Stream annehmen — bei ESPHome-Satelliten nur über den `speaker:`-Pfad (`VoiceAssistantAudio`), und `_stream_tts_audio` hat das oben genannte `b"".join`-Sammel-Problem. Wyoming-Satelliten sind hier besser.

## 5. Konkrete Risiken / Stolperfallen

| Risiko | Auswirkung | Gegenmaßnahme |
|---|---|---|
| 60-Zeichen-Schwelle (`STREAM_RESPONSE_CHARS`) | Kurze Antworten streamen nicht | Akzeptieren oder abwarten, bis HA es konfigurierbar macht |
| Text vor Tool-Call bleibt liegen (home-assistant/core#187933) | "Ja, ich recherchiere..." wird erst nach Tool-Ende gesprochen, obwohl es früher generiert wurde | In my-jarvis bei Tool-Call-Übergabe explizit `"\n\n"`/Flush senden (wie home-assistant/core#193007 es tut); PR beobachten |
| ESPHome `_stream_tts_audio` liest alles mit `b"".join(...)` | Bei `speaker:`-Satelliten: TTS-Start-Verzögerung trotz Streaming-Input | Bei `media_player:` + wachsender HTTP-URL bleiben (besser für Voice PE); Wyoming-Satellit wäre ideal |
| ESPHome 2s-Playback-Timeout (esphome/esphome#16462, esphome/esphome#18419) | Folge-Dialog-Fenster öffnet sich zu früh bei langsamer TTS | `tts_playback_start_timeout: 10s` in der Satelliten-Firmware (ab ESPHome ≥2026.11) |
| ffmpeg-WAV-Probe ~0,6 s (home-assistant/core#184204) | Zusatzlatenz, wenn Audio konvertiert wird | TTS-Format wählen, das der Satellit direkt abspielen kann (mp3/wav ohne Umkodierung) |
| Keine Partial-STT-Transcripts | Zusatz-Latenz, bis das ganze Statement transkribiert ist | Nicht in der Pipeline lösbar; nur im my-jarvis-STT-Endpoint intern optimieren (z. B. erste Worte früher melden) |
| Neue HA-APIs (home-assistant/core#188223, home-assistant/core#188283) noch im Fluss | Breaking Changes möglich | Option A als stabile Basis nutzen, Option C als spätere Optimierung |

## 6. Fazit

| Frage | Antwort |
|---|---|
| Ist "Text streamen + direkt TTS" möglich? | **Ja.** Textseitiges Streaming ist HA-intern unterstützt und wird von `conversation.py` bereits bedient. |
| Was fehlt in dieser Integration? | Primär `async_stream_tts_audio` in `tts.py` (TTS-Input/Output-Streaming) + ein delta-fähiger TTS-Websocket in my-jarvis. |
| Kann Audio "nahtlos" von STT→LLM→TTS durchgereicht werden? | **Nicht byte-nahtlos über eine gemeinsame Pipe**, aber zeitlich überlappend (die Pipeline parallelisiert bereits `prepare_text_to_speech` mit `recognize_intent`). Der echte "Roh-PCM durchreichen"-Weg existiert seit 2026-10 (home-assistant/core#188223) nur als junge API. |
| Wo bleibt unvermeidbare Latenz? | STT/VAD-Ende (Silence-Erkennung), die 60-Zeichen-Schwelle, die TTS-Engine-Latenz (Time-to-first-audio) und ggf. das ESPHome-Satelliten-Playback-Timeout. |
| Empfehlung | **Option A (TTS-Websocket-Streaming) umsetzen** — großer UX-Gewinn, kein HA-Fork nötig, kompatibel mit dem geplanten home-assistant/core#188223/#188283-Weg. Optional Option B als Pre-Announce-Booster. Option C später beobachten. |

## Anhang: Wichtigste Referenzen

**Home Assistant Core**

- `homeassistant/components/assist_pipeline/pipeline.py` — `PipelineRun`, `chat_log_delta_listener`, `STREAM_RESPONSE_CHARS`, Event-Typen
- `homeassistant/components/conversation/chat_log.py` — `async_add_delta_content_stream`, `delta_listener`
- `homeassistant/components/tts/entity.py` — `TTSAudioRequest`/`TTSAudioResponse`, `async_stream_tts_audio`
- `homeassistant/components/tts/__init__.py` — `ResultStream`, `async_stream_result`, `/api/tts_proxy`
- `homeassistant/components/assist_satellite/entity.py`, `homeassistant/components/esphome/assist_satellite.py`, `homeassistant/components/wyoming/assist_satellite.py` — Satelliten-Übergabe
- PRs/Issues: home-assistant/core#184535, home-assistant/core#187933, home-assistant/core#179576, home-assistant/core#184204, home-assistant/core#188223, home-assistant/core#188283, home-assistant/core#193007

**Externe Protokolle / Doku**

- https://esphome.io/components/voice_assistant/ — `on_tts_end`, `on_intent_progress`, `on_tts_stream_start/end`, `tts_playback_start_timeout`
- https://github.com/esphome/esphome/blob/dev/esphome/components/api/api.proto — `VoiceAssistantEvent`, `VoiceAssistantAudio`, `VoiceAssistantAnnounceRequest`
- https://github.com/OHF-Voice/wyoming — `synthesize-start/-chunk/-stop`, `audio-chunk`, `transcript-chunk`, `supports_*_streaming`
- https://github.com/OHF-Voice/sentence-stream — Satztrennung für Streaming-TTS (genutzt von HA Cloud/ElevenLabs)