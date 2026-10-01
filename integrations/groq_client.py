"""
integrations/groq_client.py

Provides a single function, transcribe_audio(audio_bytes, filename) -> str,
used by voice_engine.py as its injectable transcription dependency (same
pattern as claude_client.call_claude for the Parser/Quality engines).

Design principle (per project philosophy, same as claude_client.py):
this module is intentionally the ONLY place in the codebase that knows
how to talk to the Groq API. voice_engine.py receives this as an
injected function and has no idea it's Groq/Whisper underneath -- it
can be tested with a fake transcribe function, no network access.

Why Groq instead of the browser's Web Speech API: Web Speech API is
free but unreliable for Spanish medical terminology and unavailable
in in-app browsers (WhatsApp, Instagram). Groq's hosted
whisper-large-v3 has a free tier, noticeably better accuracy on
medical vocabulary, and only needs microphone access (getUserMedia)
on the client, which in-app browsers do support.

Setup:
    export GROQ_API_KEY="gsk_..."   (Linux/Mac)
    set GROQ_API_KEY=gsk_...        (Windows cmd)
Get a free key at https://console.groq.com/keys -- then set it as an
environment variable on Railway (Backend service -> Variables).

Usage from voice_engine:
    from groq_client import transcribe_audio
    text = transcribe_audio(audio_bytes, filename="dictado.webm")
"""

import os
import re

import httpx

_GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODEL = "whisper-large-v3"
_LANGUAGE = "es"
_TIMEOUT = 60.0

# Texto de contexto para Whisper. Whisper NO lo toma como instruccion: lo
# usa como "lo que se venia diciendo", asi que funciona mejor cuando se
# parece a un dictado real (frases cortas, con tildes, medidas en "mm") que
# cuando es una lista suelta de palabras. Las confusiones b/v (ej: "bazo" ->
# "vaso") se resuelven por contexto, por eso "bazo" aparece dentro de
# frases, y "vaso" tambien (como vaso sanguineo) para no sobrecorregirlo.
# Reglas para editarlo:
#  - Mantener las tildes y las medidas como "120 mm" (si se escribe
#    "milimetros", Whisper tiende a transcribir asi y se rompe el parser).
#  - No copiar frases normales de la plantilla ("higado de tamano normal"):
#    si un dictado real coincide con el prompt, el filtro de eco de abajo
#    lo podria descartar por error.
#  - Whisper solo usa los ultimos ~224 tokens: no alargarlo.
_MEDICAL_VOCABULARY_PROMPT = (
    "Informe de ecografía abdominal dictado en español rioplatense. "
    "Bazo aumentado de tamaño, esplenomegalia, mide 120 mm. "
    "Vaso sanguíneo de calibre normal, pared del vaso engrosada. "
    "Apéndice cecal con engrosamiento de las paredes, mide 11 mm. "
    "Riñón derecho, riñón izquierdo, glándulas suprarrenales, vesícula "
    "biliar, páncreas, aorta abdominal, vena cava inferior, próstata, "
    "vejiga, útero, ovarios, testículos, tiroides, mama, pulmón, pleura, "
    "colon, recto, ganglios, adenopatías, litiasis, quiste, nódulo "
    "hipoecoico, masa expansiva, ecogenicidad, parénquima, corticomedular."
)

# Si lo transcripto es una secuencia de al menos esta cantidad de palabras
# copiada tal cual del prompt, se trata como eco del prompt (no como dictado).
_PROMPT_ECHO_MIN_WORDS = 8


class GroqClientError(Exception):
    """
    Raised when the Groq transcription API cannot be reached or
    returns an unusable response. Same philosophy as
    ClaudeClientError: a failed API call is not the same as "the
    medico said nothing" -- it must propagate so the caller can tell
    the medico the transcription failed, not silently return empty
    text that reads as an empty dictation.
    """
    pass


def _normalize_for_echo_check(text: str) -> str:
    plain = text.lower().translate(str.maketrans("áéíóúü", "aeiouu"))
    return " ".join(re.findall(r"[a-zñ0-9]+", plain))


def _looks_like_prompt_echo(text: str) -> bool:
    """
    Con silencio o audio muy corto, Whisper a veces devuelve el texto del
    prompt como si fuera lo dictado. En un informe medico eso metería
    terminos que nadie dijo, asi que se descarta y se pide repetir.
    """
    normalized = _normalize_for_echo_check(text)
    if len(normalized.split()) < _PROMPT_ECHO_MIN_WORDS:
        return False
    return normalized in _normalize_for_echo_check(_MEDICAL_VOCABULARY_PROMPT)


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise GroqClientError(
            "GROQ_API_KEY environment variable is not set. "
            "Get a free key at https://console.groq.com/keys and set it "
            "on the backend (export GROQ_API_KEY=gsk_... on Linux/Mac, "
            "set GROQ_API_KEY=gsk_... on Windows, or as a Railway "
            "service variable)."
        )

    if not audio_bytes:
        raise GroqClientError("No audio bytes were provided to transcribe.")

    try:
        response = httpx.post(
            _GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data={
                "model": _MODEL,
                "language": _LANGUAGE,
                "prompt": _MEDICAL_VOCABULARY_PROMPT,
            },
            files={"file": (filename, audio_bytes)},
            timeout=_TIMEOUT,
        )
    except Exception as e:
        raise GroqClientError(f"Groq API call failed: {e}")

    if response.status_code != 200:
        raise GroqClientError(
            f"Groq API returned {response.status_code}: {response.text}"
        )

    try:
        data = response.json()
    except Exception as e:
        raise GroqClientError(f"Groq API returned a non-JSON response: {e}")

    text = (data.get("text") or "").strip()
    if not text:
        raise GroqClientError(
            "Groq API returned an empty transcription (silence, or audio "
            "too short/corrupt)."
        )

    if _looks_like_prompt_echo(text):
        raise GroqClientError(
            "No se detecto voz clara en el audio (la transcripcion repetia el "
            "texto de contexto). Volve a grabar."
        )

    return text
