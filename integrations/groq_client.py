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

import httpx

_GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODEL = "whisper-large-v3"
_LANGUAGE = "es"
_TIMEOUT = 60.0

# Vocabulario de dominio para sesgar el reconocimiento de Whisper hacia
# terminologia radiologica/anatomica en espanol -- reduce (no elimina)
# confusiones por parecido sonoro con palabras de uso comun (ej: "bazo"
# transcripto como "vaso", visto en produccion). Whisper usa este texto
# como contexto de estilo/vocabulario, no como instruccion literal.
# Ir sumando terminos aca a medida que aparezcan nuevos errores reales
# en el uso diario -- no intentar anticiparlos todos de una.
_MEDICAL_VOCABULARY_PROMPT = (
    "Dictado radiologico en espanol. Organos y estructuras frecuentes: "
    "higado, bazo, rinon, rinones, vesicula biliar, pancreas, aorta "
    "abdominal, vena cava inferior, prostata, utero, ovario, ovarios, "
    "testiculo, tiroides, mama, pulmon, pleura, apendice, colon, recto, "
    "vejiga, ureter, glandula suprarrenal, ganglio, ganglios. "
    "Terminos descriptivos frecuentes: ecogenicidad, ecoestructura, "
    "hipodenso, hiperecoico, hipoecoico, isquemico, parenquima, "
    "corticomedular, litiasis, quiste, nodulo, masa expansiva, "
    "adenopatia, dilatacion."
)


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

    return text
