import os
from pathlib import Path

from .. import config

try:
    from openai import OpenAI  # type: ignore
except ImportError:
    OpenAI = None  # type: ignore


def _write_placeholder_audio(output_path: str) -> str:
    """
    Create a tiny placeholder 'audio' file.

    Our video pipeline will skip audio if the file is empty (size 0),
    so it's safe to leave this as an empty file. This avoids crashes
    when OpenAI is unavailable or the key is invalid.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    # Empty file is fine because video_service checks file size > 0
    with open(output_path, "wb") as f:
        f.write(b"")
    return output_path


def text_to_speech(text: str, output_dir: str, filename: str = "voiceover.mp3") -> str:
    """
    Generate speech audio from text.

    If OpenAI is not configured or the request fails (invalid / expired key, etc.),
    we create a placeholder file instead so the rest of the pipeline can still run.
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = str(Path(output_dir) / filename)

    # If there's no API key or library, go straight to placeholder.
    if not config.OPENAI_API_KEY or OpenAI is None:
        print("[tts_service] No OPENAI_API_KEY or OpenAI library; using placeholder audio.")
        return _write_placeholder_audio(output_path)

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    try:
        # OpenAI TTS: adjust model/voice as needed.
        response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text,
        )

        # For the new OpenAI SDK, response provides a streaming-like interface with .read()
        with open(output_path, "wb") as f:
            f.write(response.read())

        return output_path

    except Exception as e:
        # Any error (invalid / expired key, network, etc.) → log and fallback.
        print(f"[tts_service] OpenAI TTS error, using placeholder audio: {e}")
        return _write_placeholder_audio(output_path)