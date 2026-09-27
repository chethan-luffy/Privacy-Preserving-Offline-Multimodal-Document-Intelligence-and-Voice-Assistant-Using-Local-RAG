"""
Local voice I/O:
  - Speech-to-text via faster-whisper (CTranslate2-optimized Whisper, runs on
    CPU). Model weights download once on first use, then everything runs
    offline.
  - Text-to-speech via pyttsx3, which drives your OS's own built-in voices
    (SAPI5 on Windows, NSSpeech on macOS, espeak/espeak-ng on Linux) — no
    model download at all, works the moment it's installed.
"""
import os
import threading
import tempfile
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_TMP_DIR = os.path.join(BASE_DIR, "audio_tmp")
os.makedirs(AUDIO_TMP_DIR, exist_ok=True)

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")  # tiny/base/small/medium/large-v3
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")  # int8 = fastest on CPU

_state = {"whisper_model": None}
_lock = threading.Lock()
_tts_lock = threading.Lock()  # pyttsx3 engines aren't safe to run concurrently


def get_whisper_model():
    with _lock:
        if _state["whisper_model"] is None:
            from faster_whisper import WhisperModel
            _state["whisper_model"] = WhisperModel(
                WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE
            )
        return _state["whisper_model"]


def transcribe_audio(file_path):
    """Transcribe an audio file (webm/ogg/wav/whatever the browser recorded)
    to text. Returns (text, detected_language)."""
    model = get_whisper_model()
    segments, info = model.transcribe(file_path, beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text, info.language


def synthesize_speech(text):
    """Generate a WAV file for `text` using the OS's local TTS voice.
    Returns the path to the generated file — caller is responsible for
    deleting it after sending (see app.py's after_this_request cleanup)."""
    import pyttsx3

    out_path = os.path.join(AUDIO_TMP_DIR, f"{uuid.uuid4().hex}.wav")
    with _tts_lock:
        engine = pyttsx3.init()
        try:
            engine.save_to_file(text, out_path)
            engine.runAndWait()
        finally:
            engine.stop()
    return out_path


def save_upload_to_temp(file_storage, suffix=".webm"):
    """Save an uploaded audio blob to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix, dir=AUDIO_TMP_DIR)
    os.close(fd)
    file_storage.save(path)
    return path
