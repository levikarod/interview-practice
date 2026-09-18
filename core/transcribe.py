"""Local speech-to-text with faster-whisper.

Runs entirely on this machine and costs nothing. No system ffmpeg is required:
faster-whisper decodes through PyAV, which ships its own FFmpeg libraries, so
the browser's webm/opus blob is read directly.

The model is loaded once and reused. First use downloads weights (~0.5GB for
small.en), which is the long pause a first-time user hits; callers should say so
rather than letting it look like a hang.

WHISPER_MODEL and WHISPER_COMPUTE override the defaults. Measured on a 25s clip,
CPU int8, with the CV vocabulary supplied:

    small.en    0.44x realtime   a 120s answer transcribes in ~53s
    medium.en   1.73x realtime   the same answer takes ~3.5 minutes

Both recognised the same named entities. medium.en was clearly better on the
surrounding sentence - "the lock alone was not enough" where small.en heard "the
local owner was" - which matters, because that phrase is what the analysis step
reads. It is still not the default: 3.5 minutes per answer breaks the practice
loop, and the gap narrows on real speech. Set WHISPER_MODEL=medium.en when
accuracy matters more than pace.

Those figures come from synthesised speech, which is harder for Whisper than a
real voice, so treat them as a floor rather than an estimate.

`vocabulary` is passed to Whisper as an initial_prompt. Feeding it the tech terms
from the CV costs nothing and fixes exactly the words a technical answer turns
on - ClickHouse, Qdrant, idempotency - which a general model otherwise mangles.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.schemas import Transcript, Word

DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "small.en")
DEFAULT_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")

_model = None
_model_key: tuple[str, str] | None = None


def get_model(name: str = DEFAULT_MODEL, compute: str = DEFAULT_COMPUTE):
    """Load the Whisper model, reusing it across calls."""
    global _model, _model_key
    if _model is None or _model_key != (name, compute):
        from faster_whisper import WhisperModel

        _model = WhisperModel(name, device="cpu", compute_type=compute)
        _model_key = (name, compute)
    return _model


def is_model_cached(name: str = DEFAULT_MODEL) -> bool:
    """Whether the weights are already on disk.

    Lets the UI warn about a one-off download instead of showing a spinner that
    looks broken for two minutes.
    """
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    if not hub.is_dir():
        return False
    needle = f"faster-whisper-{name}"
    return any(d.is_dir() and d.name.endswith(needle) for d in hub.iterdir())


def transcribe(audio_path: Path, vocabulary: list[str] | None = None,
               model_name: str = DEFAULT_MODEL) -> Transcript:
    """Transcribe an audio file. Blocking - call it via asyncio.to_thread."""
    model = get_model(model_name)

    initial_prompt = None
    if vocabulary:
        initial_prompt = "Technical terms: " + ", ".join(vocabulary[:60]) + "."

    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        word_timestamps=True,
        initial_prompt=initial_prompt,
        vad_filter=True,
    )

    words: list[Word] = []
    parts: list[str] = []
    for segment in segments:
        parts.append(segment.text)
        for word in (segment.words or []):
            words.append(Word(text=word.word.strip(),
                              start=round(word.start, 3),
                              end=round(word.end, 3)))

    return Transcript(
        text=" ".join(p.strip() for p in parts).strip(),
        words=words,
        duration_s=round(getattr(info, "duration", 0.0) or 0.0, 2),
        language=getattr(info, "language", "") or "",
    )
