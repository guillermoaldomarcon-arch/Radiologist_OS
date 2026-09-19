"""
engines/voice_engine.py

Transcribes dictated audio to text. Thin orchestrator over an
injected transcription function -- same dependency-injection pattern
as parser_engine's call_claude and quality_engine's call_claude: this
file has no idea it's Groq/Whisper underneath (see
integrations/groq_client.py), and can be tested with a fake
transcribe function that needs no network access.

Privacy note: the audio itself is never written to disk or a
database anywhere in this pipeline -- it's received by the /voice/
transcribe endpoint in backend/main.py, passed straight through to
here and then to Groq, and discarded once the text comes back.
Consistent with the project's no-patient-data-persistence principle.
"""

from typing import Callable, Optional


def transcribe(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    call_transcribe: Optional[Callable[[bytes, str], str]] = None,
) -> str:
    """
    Returns the transcribed text for the given audio bytes.

    call_transcribe: injected dependency, (audio_bytes, filename) -> str.
    Defaults to the real Groq-backed integrations.groq_client.transcribe_audio
    if not provided -- pass a fake here in tests to avoid network calls.
    """
    if call_transcribe is None:
        from groq_client import transcribe_audio as call_transcribe

    return call_transcribe(audio_bytes, filename)
