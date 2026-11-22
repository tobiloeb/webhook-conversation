# Umsetzungsplan: TTS-Streaming (Websocket) für `myjarvis_webhook_conversation` + my-jarvis

> Stand: 2026-11-21
> Verwandtes Dokument: [`docs/machbarkeitsbericht-streaming-voice-pipeline.md`](machbarkeitsbericht-streaming-voice-pipeline.md) (Machbarkeitsanalyse, HA-Core-Befunde, Referenzen)
> **Dieses Dokument ist self-contained:** Es beschreibt Hintergrund, Motivation, Ziel-Architektur, Protokoll, Aufgaben, Abwärtskompatibilität und Tests so, dass es ohne Vorkenntnisse des bisherigen Gesprächs umgesetzt werden kann.

---

## 1. Kontext: Was ist dieses Projekt?

### 1.1 Die Integration `webhook-conversation` (dieses Repo)

HACS-Integration für Home Assistant (HA). Sie exponiert HAs Conversation-, AI-Task-, STT- und TTS-Plattformen als HTTP-/WebSocket-Webhooks an einen externen Server. So lassen sich eigene STT-, TTS- und KI-Agent-Implementierungen an die HA-Voice-Pipeline hängen.

Code-Struktur (`custom_components/myjarvis_webhook_conversation/`):

| Datei | Rolle |
|---|---|
| `entity.py` | Gemeinsame Basis: Auth (Basic), Payload-Senden, Streaming |
| `conversation.py` | Conversation-Plattform (LLM-Agent) |
| `stt.py` | STT-Plattform |
| `tts.py` | TTS-Plattform |
| `ai_task.py` | AI-Task-Plattform |
| `models.py` | Typdefinitionen aller Payloads |
| `config_flow.py` | Konfiguration (Subentries pro Plattform) |

**Wichtig für dieses Dokument:** Die Integration kann Webhook-URLs im Modus **`http(s)://` (klassischer POST)** oder **`ws://`/`wss://` (Streaming-Websocket)** ansprechen. Dieses Dual-Verhalten existiert bereits beim STT (`stt.py`) und beim Conversation-Agent (`conversation.py`) — **beim TTS fehlt es**.

### 1.2 Das Backend `my-jarvis`

Lokal unter `C:\Users\Tobias\repos\my-jarvis` (GitHub: `tobiloeb/my-jarvis`). FastAPI-Server (`src/jarvis_agent/server.py` bzw. `api/`) mit Endpunkten:

- `POST /api/agent/prompt` — LLM-Agent (Conversation), Antwort als JSON oder JSON-Lines-Stream (`{"type":"item","content":...}`)
- `ws://.../ws/audio` — STT: erst Metadaten-JSON, dann Binary-Audio-Chunks, dann `{"type":"eof"}`; Antwort als JSON mit Transkript
- `POST /api/tts` — TTS: JSON `{text, language, voice, voice_id}` → komplette Audio-Bytes (aktuell mp3, `Content-Type: audio/mp3`)

### 1.3 Die Voice-Satelliten

Amazon-Echo-Geräte mit [echo-dot-assist](https://github.com/Gamer92000/echo-dot-assist) (Daemon `hassmic`). HA erkennt sie als **ESPHome-Geräte** (ESPHome-Native-API, Default-Modus des Projekts). Wichtige, verifizierte Eigenschaften (Quellen: `src/hassmic/proto_esphome.c`, `PLAN.md:728-732`, `tests/fake_ha_esphome.py:262-274`):

- TTS-Audio kommt als **HTTP-URL** (HAs `/api/tts_proxy/<token>`, 48 kHz WAV/MP3), **nicht** als Audio-Chunks über die API. Der `SPEAKER`-Flag wird in hassmic bewusst nicht gesetzt.
- Sobald HA `INTENT_PROGRESS {"tts_start_streaming": "1"}` sendet, **startet hassmic den HTTP-Fetch sofort und spielt Bytes chunkweise ab, während HA den Rest noch generiert** (Play-Start beim ersten ankommenden Byte, Backpressure 256 KB). Messung im Projekt: „playback starts before TTS_START (streaming)".
- Follow-Ups (`continue_conversation`) und Barge-in werden unterstützt.
- **Folge:** Am Satelliten muss nichts geändert werden. Sobald HA frühes Audio in den `/api/tts_proxy`-Stream liefert und `tts_start_streaming` sendet, gibt es frühe Sprachausgabe.

---

## 2. Motivation: Warum tun wir das?

### 2.1 Problem

Die Voice-Pipeline fühlt sich heute träge an: Nach der Spracheingabe muss der Nutzer warten, bis der **komplette** KI-Agent-Text generiert und **komplett** in Sprache umgewandelt ist, bevor die erste Silbe zu hören ist. Bei langlaufenden Recherche-Aufgaben (Tool-Calls, Web-Suchen) sind das leicht viele Sekunden — obwohl der Agent schon nach wenigen Worten eine sinnvolle Ankündigung liefern könnte („Ja, ich recherchiere das für dich").

### 2.2 Ziel

Der Antwort-Text des KI-Agenten soll **gestreamt** und **direkt und laufend** in Sprache umgewandelt werden (Text-Deltas → TTS → Audio zum Satelliten), sodass Sprachausgabe einsetzt, sobald die ersten Sätze des Agenten vorliegen — auch wenn die Recherche noch läuft. Aus Sicht des Nutzers antwortet das System sofort.

### 2.3 Warum dieses Design? (Entscheidungsarchäologie)

Die HA-Voice-Pipeline kann intern bereits genau dieses textseitige Streaming (Befund siehe Machbarkeitsbericht, Abschnitt 2): LLM-Deltas laufen über `chat_log.async_add_delta_content_stream` in einen `tts.ResultStream`, die Pipeline sendet `tts_start_streaming`, und `/api/tts_proxy` liefert Audio chunked, während es generiert wird. Zwei Bedingungen fehlen bislang in dieser Integration:

1. Die TTS-Entity meldet `supports_streaming_input == False` (weil `async_stream_tts_audio` nicht implementiert ist) → die Pipeline sammelt den kompletten Text, bevor sie TTS anstößt. **→ Wir implementieren `async_stream_tts_audio` (nur im WS-Modus).**
2. my-jarvis `/api/tts` akzeptiert nur einen fertigen Text → keine Sätze während des LLM-Streams. **→ Neuer Websocket-Endpunkt, der Text-Deltas annimmt und Audio-Chunks zurück gibt.**

**Warum ein Websocket (und nicht nur HTTP)?** Genau wie beim STT ist der Websocket der Kanal für inkrementelle Daten: Text rein, Audio raus, in beide Richtungen gleichzeitig, ohne dass pro Satz eine neue HTTP-Verbindung aufgebaut werden muss. Das Dual-Verhalten (http:// bleibt POST, ws:// wird Streaming) ist das bereits beim STT etablierte Muster — daher auch der Wunsch nach **konsequenter Abwärtskompatibilität** (Abschnitt 6).

**Warum nicht stattdessen Roh-Audio direkt durchreichen (Speech-to-Speech)?** HA-Core führt dafür gerade neue APIs ein (home-assistant/core#188223, #188283, Stand Nov 2026 noch in Bewegung). Zu instabil als Fundament; der hier gewählte Text-Deltas-Weg nutzt ausschließlich stabile HA-APIs. Ein späterer Umstieg ist nur innerhalb der my-jarvis-Synthese-Schicht nötig (Abschnitt 8, Risiken).

---

## 3. Ausgangslage: Ist-Zustand (verifiziert am Code)

### 3.1 Integration (`webhook-conversation`)

| Baustein | Zustand | Fundstelle |
|---|---|---|
| Conversation-Streaming in HA | **vorhanden**: `_attr_supports_streaming`, `chat_log.async_add_delta_content_stream(self._transform_webhook_stream(payload))` | `conversation.py:68, 162-186` |
| STT-Dual-Modus (http/ws) | **vorhanden**: `ws://`-Präfix-Check, Metadaten-JSON → Bytes → `{"type":"eof"}`, sonst POST | `stt.py:157-265` |
| TTS-HTTP-POST | **vorhanden**: `async_get_tts_audio` sendet `{text, language, voice_id}`, erwartet komplette Bytes + `Content-Type: audio/{wav,mp3}` | `tts.py:99-141` |
| TTS-Streaming (WS) | **fehlt** — `async_stream_tts_audio` nicht implementiert | — |
| TTS-Payload-Typen | nur `WebhookTTSRequestPayload` (`text, language, voice, voice_id`) | `models.py` |

### 3.2 my-jarvis

| Baustein | Zustand | Fundstelle |
|---|---|---|
| `POST /api/tts` | **vorhanden**, nicht streamend: `synthesize_speech(...)` → komplette Bytes (`audio/{format}`) | `src/jarvis_agent/api/tts_routes.py:39-79` |
| STT-Websocket `/ws/audio` | **vorhanden** (Metadaten → Binary-Chunks → `eof` → JSON-Antwort), Basic-Auth via `verify_ws_auth` | `src/jarvis_agent/api/audio_ws.py` |
| TTS-Websocket | **fehlt** | — |
| TTS-Synthese | satzunabhängig, ein Aufruf für den ganzen Text (OpenRouter/ElevenLabs/Gemini/Microsoft/Mistral/lokal) | `src/jarvis_agent/tts/base.py:66` |

### 3.3 HA-Core-Mechanismus (relevant für die Umsetzung)

`homeassistant/components/tts/entity.py` (Core-Snapshot):

```python
@dataclass
class TTSAudioRequest:
    language: str
    options: dict[str, Any]
    message_gen: AsyncGenerator[str]      # Text-Deltas live rein

@dataclass
class TTSAudioResponse:
    extension: str
    data_gen: AsyncGenerator[bytes]       # Audio-Chunks live raus

def async_supports_streaming_input(self) -> bool:
    """Return if the TTS engine supports streaming input."""
    return (self.__class__.async_stream_tts_audio
            is not TextToSpeechEntity.async_stream_tts_audio)
```

- Der HA-Default-Check ist **klassenweit** („wurde `async_stream_tts_audio` überschrieben?") — **nicht pro URL**. `async_supports_streaming_input` ist eine normale Instanzmethode und kann überschrieben werden.
- Bei `supports_streaming_input == True` sammelt die Pipeline den Text **nicht**, sondern speist Deltas in `tts_stream.async_set_message_stream(...)` und sendet `INTENT_PROGRESS {"tts_start_streaming": true}` (Schwelle: >60 Zeichen **oder** Tool-Call nach Text, `assist_pipeline/pipeline.py`, `STREAM_RESPONSE_CHARS = 60`).
- `/api/tts_proxy/<token>` schreibt `data_gen`-Chunks laufend in die HTTP-Response — genau das, was hassmic schon heute früh abruft und abspielt.

---

## 4. Ziel-Architektur (End-to-End-Ablauf WS-Modus)

```
Echo (hassmic)          HA assist_pipeline           Integration (tts.py)             my-jarvis /ws/tts
    |  Mic-Audio (VA-API)  |                             |                               |
    |---------------------->| STT (ws, unverändert)     |                               |
    |                       |-------------------------->| (stt.py)                      |
    |                       | intent-start, LLM-Deltas  |                               |
    |                       | ab 60 Zeichen oder         |                               |
    |                       | Tool-Call nach Text:       |                               |
    |<----------------------| INTENT_PROGRESS             |                               |
    |  (URL von RUN_START;  |  tts_start_streaming=1     |                               |
    |   Fetch startet sofort)|                            |                               |
    |  HTTP-GET /api/tts_proxy  tts_stream.async_set_message_stream(...)                |
    |<======================|===== chunked HTTP ==========|===== ws: text-Deltas ========>|
    |                       |                             |   Satz-Segmentierung +       |
    |  spiele Bytes sofort  |                             |   Idle-Flush (400 ms)        |
    |  ab (chunkweise)      |                             |<===== ws: binary audio ======|
    |<======================|<===== ResultStream pumpt ====|<===== Chunks ================|
    |                       | tts-end / run-end           | {"type":"end"}               |
```

Es gibt keinen „komplettes Ergebnis abwarten"-Block mehr, außerhalb der unvermeidbaren VAD/STT-Phase (Sprachende-Erkennung).

---

## 5. Protokoll-Spezifikation: TTS-Websocket

**Endpunkt:** `ws(s)://<my-jarvis>/ws/tts` (Pfadschema analog `/ws/audio`).
**Auth:** HTTP Basic auf dem Handshake (vor `accept`, wie `verify_ws_auth` in `api/auth.py`).
**Frame-Typen:** JSON-Text-Frames für Steuerung, Binary-Frames für Audio.

### 5.1 Client → Server (Integration → my-jarvis)

| Reihenfolge | Frame | Beschreibung |
|---|---|---|
| 1 | `{"type": "start", "language": "de-DE", "voice_id": "<id>", "conversation_id": "<id>", "format": "mp3"}` | Metadaten, **genau einmal, erstes Frame** (Spiegel des STT-Metadaten-Prinzips) |
| 2 | `{"type": "text", "content": "<delta>"}` | 0..n Roh-Text-Deltas, in HA-Ankunftsreihenfolge |
| 3 | `{"type": "eof"}` | Text vollständig, Synthese abschließen |

### 5.2 Server → Client (my-jarvis → Integration)

| Frame | Beschreibung |
|---|---|
| **Binary-Frames** | Audio-Bytes (ein durchgehendes Format, mp3), sobald verfügbar — Reihenfolge = Abspielreihenfolge |
| `{"type": "end", "format": "mp3"}` | Letztes Audio-Byte gesendet, Stream beenden |
| `{"type": "error", "message": "..."}` | Fehler; danach wird die Verbindung geschlossen |

### 5.3 Regeln

- Erstes Audio-Frame so früh wie möglich senden (Ziel: < 500 ms nach dem ersten vollständigen Satz).
- Audio-Bytes müssen aneinanderhängend abspielbar sein → **mp3** (framebasiert, tolerantes Decoding in hassmic). WAV-Fragmente mit je eigenem Header sind verboten. Keine ID3-Tags mitten im Stream.
- `conversation_id` aus HAs `current_session` (wie in `stt.py`), damit my-jarvis den TTS-Lauf dem Agent-Turn zuordnen kann.
- Die Verbindung bleibt offen bis `{"type": "end"}` (auch nach `eof`); der Server darf nach `eof` noch Rest-Audio senden.

---

## 6. Abwärtskompatibilität (verbindliche Anforderung)

**Grundprinzip wie beim STT:** *Das URL-Schema entscheidet über den Modus. Es gibt keine neue Konfigurationsoption und keine Migration bestehender Config-Entries.*

| Konfiguration | Verhalten | Muss unverändert bleiben zu heute? |
|---|---|---|
| `http(s)://`-URL | Klassischer POST (`async_get_tts_audio`, aktueller Code). `supports_streaming_input` wird `False` → die Pipeline sammelt den Text, sendet **kein** `tts_start_streaming`, ruft **nur** `async_get_tts_audio` auf. | **Ja, exakt** |
| `ws(s)://`-URL | Neu: `async_stream_tts_audio` (Text-Deltas rein, Audio-Chunks raus). | Neues Feature |

**Konkrete Kompatibilitäts-Anforderungen:**

1. **Kein Config-Schema-Wandel:** `CONF_VOICE`/`CONF_VOICES`, `CONF_TIMEOUT`, `CONF_SUPPORTED_LANGUUAGEN`, Basic-Auth-Einstellungen gelten für beide Modi unverändert. Bestehende Config-Entries laufen ohne Migration.
2. **POST-Payload unverändert:** Bei http://-URLs wird weiterhin `WebhookTTSRequestPayload` (`text, language, voice, voice_id`) gesendet und weiterhin `Content-Type: audio/{wav,mp3}` + komplette Bytes erwartet. Ein älteres my-jarvis mit nur `POST /api/tts` funktioniert weiterhin gegen eine http://-konfigurierte Integration.
3. **WS ist opt-in:** Wer das Feature will, ändert (oder ergänzt) die TTS-Webhook-URL auf `ws(s)://.../ws/tts`. Ein my-jarvis *ohne* `/ws/tts`-Endpoint meldet beim Handshake einen Fehler (404/Refused) — die Integration wirft `HomeAssistantError` wie bei jedem TTS-Ausfall; kein Systembruch.
4. **Haftungsabgrenzung `async_supports_streaming_input`:** Da HAs Default diese Methode klassenweit ableitet („`async_stream_tts_audio` überschrieben?"), **muss** unsere Entity die Methode explizit überschreiben und URL-abhängig `True`/`False` liefern (Abschnitt 7, T2). Ohne dieses Override würde HA bei http://-URLs fälschlich `tts_start_streaming` senden — Verhaltensänderung, die vermieden werden muss.
5. **Rückwärtskompatibles Backend:** my-jarvis behält `POST /api/tts` **zusätzlich** zum neuen WS-Endpoint (kein Entfernen, kein Breaking Change für andere Clients).

---

## 7. Umsetzungsplan: `webhook-conversation` (Integration)

### T1 — `models.py`: TTS-WS-Metadaten ergänzen
- Neues TypedDict `WebhookTTSWebSocketMetadata`:
  `format: str`, `language: str`, `voice_id: NotRequired[str]`, `conversation_id: NotRequired[str]`.
- Akzeptanzkriterium: `mypy` sauber; keine Änderung bestehender Payloads (Regressionscheck: bestehende Tests grün).

### T2 — `tts.py`: `async_supports_streaming_input()` URL-abhängig überschreiben
```python
def async_supports_streaming_input(self) -> bool:
    return self._webhook_url.startswith(("ws://", "wss://"))
```
- Akzeptanzkriterium: Bei http-URL ruft HA ausschließlich `async_get_tts_audio` auf und sendet kein `tts_start_streaming`; bei ws-URL ausschließlich `async_stream_tts_audio`. (Prüfbar über den Pipeline-Event-Stream `assist_pipeline/run` bzw. Mock-Tests.)

### T3 — `tts.py`: `async_stream_tts_audio()` implementieren (nur WS-Pfad aufgerufen)
- Signatur: `async def async_stream_tts_audio(self, request: TTSAudioRequest) -> TTSAudioResponse`.
- Ablauf:
  1. `session.ws_connect(self._webhook_url, timeout=..., auth=BasicAuth(...))` (Muster aus `stt.py:175-180`).
  2. Metadaten-Frame senden (T1); `format` = `"mp3"`.
  3. `async for delta in request.message_gen:` → `{"type": "text", "content": delta}` senden. (Generator-Ende = Ende des Texts.)
  4. `{"type": "eof"}` senden.
  5. `TTSAudioResponse("mp3", data_gen())` zurückgeben; `data_gen()` yielded **Binary**-Frames lazily bis `{"type": "end"}` oder Verbindungsende; JSON `{"type":"error"}` → `HomeAssistantError`.
- **Aufräum-Garantie:** `try/finally` um die Verbindung — bei Abbruch (Barge-in → HA verwirft `data_gen`) muss die WS-Verbindung sicher schließen (kein Leak).
- Timeouts: Receive-Timeout pro Frame (erstes Audio-Frame ≤ 15 s), Gesamtlauf = `CONF_TIMEOUT`.
- Akzeptanzkriterium: `data_gen` liefert Chunks in Ankunftsreihenfolge; Mock-WS-Test „drei Sätze → drei Audio-Blöcke, Reihenfolge & Vollständigkeit".

### T4 — Fehlerbehandlung & Sonderfälle
- **Fehler vor dem ersten Audio-Frame:** `HomeAssistantError` werfen → HA meldet TTS-Fehler an die Pipeline (gleiches Verhalten wie heutige HTTP-Fehler).
- **Fehler nach dem ersten Audio-Frame:** Stream sauber beenden (nicht werfen — die HTTP-Response an den Satelliten läuft bereits), Fehler loggen. Ziel: Satellit spricht wenigstens den Teil, der da ist.
- **Leerer Text:** `{"type":"eof"}` sofort senden; `data_gen` beendet ohne Audio (entspricht leerem TTS-Result).
- Akzeptanzkriterium: alle drei Fälle durch Unit-Tests abgedeckt.

### T5 — Dokumentation
- README/AGENTS der Integration: Abschnitt „TTS-Streaming (ws://)" ergänzen — Hinweis auf URL-Schema-Umschaltung, Beispielkonfiguration, Verweis auf die Protokoll-Spezifikation (Abschnitt 5).
- Akzeptanzkriterium: Doku beschreibt beide Modi und die Kompatibilitätsregeln aus Abschnitt 6.

---

## 8. Umsetzungsplan: `my-jarvis`

### M1 — `api/tts_ws.py`: WebSocket-Endpoint `/ws/tts`
- Neuer `APIRouter` analog zu `api/audio_ws.py` (`@router.websocket("/ws/tts")`), Registrierung in `api/app.py`.
- Auth via `verify_ws_auth` (vor `accept`), Settings via `get_settings_ws`, ggf. `get_conversation_store_ws`.
- Empfangsschleife: Metadaten-Frame → Text-Deltas → `eof`. Nach `eof`: warten bis alle Audio-Chunks gesendet sind, dann `{"type":"end"}` senden und schließen.
- Akzeptanzkriterium: Verbindung mit ungültigem Basic-Auth wird abgelehnt (Close-Code 1008); vollständiger Lauf endet mit `{"type":"end"}`.

### M2 — `tts/stream.py` (neu) oder Erweiterung von `tts/base.py`: Satz-Segmentierung + Idle-Flush
- Eingehende Text-Deltas in **Sätze** segmentieren (Satzende `.!?`/`\n\n`, mit Abkürzungsschutz für z. B. „z. B.", „Dr.") — Puffer über Deltas hinweg, **nicht** pro Delta.
- Pro fertigem Satz `synthesize_speech(...)` (bestehend, `tts/base.py:66`) aufrufen und die Audio-Bytes sofort als Binary-Frame senden.
- **Idle-Flush (verbindlich):** Kommt nach einem Satzanfang **~400 ms** kein neues Delta (typisch bei Tool-Calls des Agenten), den Zwischensatz trotzdem synthetisieren und senden.
- **Warum Idle-Flush:** HA-interne Satz-Bufferung (Bibliothek `sentence-stream`) hält Text vor Tool-Calls bis Tool-Ende zurück (bekanntes HA-Core-Problem, home-assistant/core#187933). Unsere eigene Flush-Logik umgeht das vollständig und trifft den Wunschfall „Ja, ich recherchiere das für dich": **sofort hörbar, obwohl danach ein langlaufender Tool-Call startet.**
- Akzeptanzkriterium: Test „Deltas: ‚Ja, ich recherchiere das für dich‘ + Pause (Tool-Call) + späterer Rest" → erstes Audio-Frame **vor** dem Rest-Text; Satzerkennung inkl. Abkürzungen.

### M3 — Fehler- und Format-Handling
- Einheitliches Audio-Format pro Verbindung (mp3); `_normalize_format` (`tts/base.py:216`) als Leitfaden; keine ID3-Tags mitten im Stream.
- Provider-Fehler: `{"type":"error","message":...}` senden, Verbindung schließen, Logging analog `tts_routes.py:53-57`.
- Teilweiser Ausfall: Scheitert ein späterer Satz nach bereits gesendeten Audio-Chunks, Restsätze verwerfen + loggen, Stream endet sauber.
- Akzeptanzkriterium: Unit-Tests für Format, Fehler-Frame, Teil-Ausfall.

### M4 — (Optional, Phase 2) Provider-natives Streaming
- ElevenLabs-/Gemini-Streaming-Endpoints statt Satz-weise-Aufrufe → flüssigeres Audio innerhalb langer Sätze. **Nicht Teil dieses Plans.** Die Schnittstelle in M2 (`send_audio(bytes)`) bleibt identisch, der Austausch ist lokal.

---

## 9. Teststrategie

| Test | Ort | Was |
|---|---|---|
| Unit: Dual-Modus | Integration | ws-URL → `async_stream_tts_audio` (Mock-WS); http-URL → `async_get_tts_audio`, **unverändert** (bestehende Tests müssen grün bleiben) |
| Unit: Fehlerfälle | Integration | T4 (Fehler vor/nach erstem Chunk, leerer Text) |
| Unit: Abwärtskompatibilität | Integration | POST-Payload bei http:// byte-identisch zu heute; kein `tts_start_streaming` bei http:// |
| Unit: Satz-Segmentierung + Idle-Flush | my-jarvis | Satzerkennung inkl. Abkürzungen, Flush nach 400 ms Pause, Tool-Call-Muster (M2) |
| Unit: WS-Protokoll | my-jarvis | Metadaten → Deltas → `eof` → `end`; Auth-Ablehnung (1008) |
| Integration (Mock) | beide | Kette „LLM-Deltas simuliert" bis „Audio-Bytes raus"; Reihenfolge/Vollständigkeit |
| E2E / Latenz | Realbetrieb | Echo + echtes HA: „Ja, ich recherchiere das für dich" muss **während** des Tool-Calls hörbar sein; Time-to-first-audio messen |
| Regression | Realbetrieb | http://-konfigurierte TTS-Subentries verhalten sich unverändert; Barge-in (Antwort abbrechen) hinterlässt keine hängenden WS-Verbindungen |

---

## 10. Risiken & offene Punkte

| Punkt | Einschätzung / Umgang |
|---|---|
| 60-Zeichen-Schwelle (`STREAM_RESPONSE_CHARS`, HA-intern) | Kurze Ein-Wort-Antworten streamen nicht. Nicht änderbar (HA-Core). Im Wunschfall (Intro-Text + Tool-Call) triggert **Tool-Call nach Text** das Streaming ebenfalls — der Idle-Flush in M2 deckt den Use Case also ab. Deltas vor der Schwelle gehen nicht verloren (Queue), sie verzögern nur den Streaming-Start. |
| Konkatenierter mp3 aus mehreren Synthesen | Framebasiert robust; hassmic resynchronisiert an Frame-Grenzen. Keine ID3-Tags im Stream (M3). Im E2E-Test verifizieren. |
| `conversation_id` im TTS-Fluss | Annahme: `current_session` (wie in `stt.py`) steht auch im TTS-Kontext. **Vor M1 verifizieren** (HA `helpers/chat_session.py`); falls nicht verfügbar, `conversation_id` optional lassen (Protokoll erlaubt `NotRequired`). |
| HA-Core-Änderungen (core#188223/#188283, Speech-to-Speech) | Unser Plan nutzt nur stabile APIs (`TTSAudioRequest`/`TTSAudioResponse`, `async_supports_streaming_input`). Späterer Umstieg auf Audio-Streams betrifft nur `data_gen`/M2. |
| Parallelität mehrerer TTS-Läufe | Ein WS-Lauf = eine TTS-Anfrage; `data_gen` ist pro `ResultStream` isoliert. Kein Shared State in der Entity (T3). |
| hassmic-Seitige Timeouts | Fetch-Receive-Timeout 15 s („TTS may still be rendering"); bei unserem Streaming-Start kommt Audio sofort → unkritisch. |

---

## 11. Empfohlene Reihenfolge

1. **Integration zuerst (T1–T5)** — gegen einen handgeschriebenen Mock-WS-Server testbar, ohne Backend-Änderungen. Abwärtskompatibilitäts-Tests (Abschnitt 9) hier erzwingen.
2. **my-jarvis (M1–M3)** — Endpoint + Satz-Segmentierung + Idle-Flush.
3. **E2E am Echo** — Latenz messen, Idle-Flush-Zeit (400 ms) und Satzgrenzen feinjustieren.
4. **Optional M4** — provider-natives Streaming, sobald die Basis stabil läuft.