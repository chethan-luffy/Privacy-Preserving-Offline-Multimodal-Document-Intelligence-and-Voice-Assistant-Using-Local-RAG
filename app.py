"""
Offline chat app — ChatGPT/Claude-style UI, fully local via Ollama.

Features:
  - Multiple saved conversations (SQLite), sidebar to switch/rename/delete
  - Streaming responses (token-by-token, proxied from Ollama's native stream)
  - Multi-turn memory (full conversation history sent to the model each turn)
  - Model switching per conversation (pick from whatever's pulled in Ollama)
  - Optional per-conversation document RAG (PDF + image/handwriting OCR),
    reusing the same local embeddings + FAISS pipeline as before, but scoped
    per chat instead of one global index
  - Voice input (faster-whisper speech-to-text) and voice output (pyttsx3
    text-to-speech), both local

Everything talks to http://localhost:11434 (Ollama) and runs local models
for embeddings/OCR/voice — no cloud calls anywhere, once models are pulled
or downloaded.
"""
import os
import json
import shutil
import traceback

import requests
from flask import Flask, request, jsonify, render_template, Response, send_file, after_this_request
from werkzeug.utils import secure_filename

import db
import rag
import voice

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB per upload request

db.init_db()

RAG_SYSTEM_PROMPT = (
    "You are an assistant for question-answering tasks. Use the following "
    "pieces of retrieved context to answer the question. If the answer "
    "isn't in the context, say you don't know rather than guessing.\n\n"
    "Context:\n{context}"
)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", default_model=DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# Models (from local Ollama)
# ---------------------------------------------------------------------------
@app.route("/api/models", methods=["GET"])
def list_models():
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return jsonify({"models": models, "default": DEFAULT_MODEL})
    except Exception as e:
        return jsonify({"models": [], "default": DEFAULT_MODEL,
                         "error": f"Could not reach Ollama at {OLLAMA_BASE_URL}: {e}"}), 200


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
@app.route("/api/conversations", methods=["GET"])
def get_conversations():
    return jsonify({"conversations": db.list_conversations()})


@app.route("/api/conversations", methods=["POST"])
def new_conversation():
    data = request.get_json(silent=True) or {}
    model = data.get("model") or DEFAULT_MODEL
    conv_id = db.create_conversation(model=model, title="New chat", use_rag=False)
    return jsonify(db.get_conversation(conv_id))


@app.route("/api/conversations/<int:conv_id>", methods=["GET"])
def get_conversation(conv_id):
    conv = db.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    conv["messages"] = db.get_messages(conv_id)
    return jsonify(conv)


@app.route("/api/conversations/<int:conv_id>", methods=["PATCH"])
def patch_conversation(conv_id):
    if not db.get_conversation(conv_id):
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    fields = {}
    if "title" in data:
        fields["title"] = data["title"].strip()[:120] or "New chat"
    if "model" in data:
        fields["model"] = data["model"]
    if "use_rag" in data:
        fields["use_rag"] = int(bool(data["use_rag"]))
    db.update_conversation(conv_id, **fields)
    return jsonify(db.get_conversation(conv_id))


@app.route("/api/conversations/<int:conv_id>", methods=["DELETE"])
def remove_conversation(conv_id):
    db.delete_conversation(conv_id)
    shutil.rmtree(rag.docs_dir(conv_id), ignore_errors=True)
    shutil.rmtree(rag.db_dir(conv_id), ignore_errors=True)
    with rag.rag_states_lock:
        rag.rag_states.pop(conv_id, None)
    return jsonify({"deleted": conv_id})


# ---------------------------------------------------------------------------
# Per-conversation documents (RAG)
# ---------------------------------------------------------------------------
@app.route("/api/conversations/<int:conv_id>/documents", methods=["GET"])
def conv_documents(conv_id):
    return jsonify({"documents": rag.list_documents(conv_id)})


@app.route("/api/conversations/<int:conv_id>/documents", methods=["POST"])
def conv_upload(conv_id):
    if not db.get_conversation(conv_id):
        return jsonify({"error": "Not found"}), 404
    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    saved = []
    for f in request.files.getlist("files"):
        if not f.filename.lower().endswith(rag.ALL_EXTS):
            continue
        filename = secure_filename(f.filename)
        if not filename:
            continue
        f.save(os.path.join(rag.docs_dir(conv_id), filename))
        saved.append(filename)

    if not saved:
        return jsonify({"error": "No valid PDF or image files in upload"}), 400
    return jsonify({"saved": saved})


@app.route("/api/conversations/<int:conv_id>/documents/<path:filename>", methods=["DELETE"])
def conv_delete_document(conv_id, filename):
    filename = secure_filename(filename)
    if rag.delete_document(conv_id, filename):
        return jsonify({"deleted": filename})
    return jsonify({"error": "File not found"}), 404


@app.route("/api/conversations/<int:conv_id>/build", methods=["POST"])
def conv_build(conv_id):
    if not db.get_conversation(conv_id):
        return jsonify({"error": "Not found"}), 404
    state = rag.get_state(conv_id)
    if state["status"] == "building":
        return jsonify({"error": "Index build already in progress"}), 409
    rag.start_build(conv_id)
    return jsonify({"started": True})


@app.route("/api/conversations/<int:conv_id>/build-status", methods=["GET"])
def conv_build_status(conv_id):
    return jsonify(rag.get_state(conv_id))


# ---------------------------------------------------------------------------
# Chat (streaming, multi-turn, optional RAG)
# ---------------------------------------------------------------------------
def _auto_title(text):
    text = " ".join(text.split())
    return (text[:47] + "...") if len(text) > 50 else text


@app.route("/api/conversations/<int:conv_id>/chat", methods=["POST"])
def chat(conv_id):
    conv = db.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "Message is empty"}), 400

    # First message of a fresh chat becomes its title
    existing = db.get_messages(conv_id)
    if not existing:
        db.update_conversation(conv_id, title=_auto_title(user_message))

    db.add_message(conv_id, "user", user_message)
    history = db.get_messages(conv_id)  # includes the message we just added

    sources = []
    ollama_messages = []

    if conv["use_rag"]:
        context, sources = rag.retrieve(conv_id, user_message)
        if context is None:
            # RAG is on for this chat but no ready index yet
            def err():
                yield json.dumps({
                    "error": "Document search is on for this chat, but the index isn't built yet. "
                             "Upload files and click Build Index, or turn document search off."
                }) + "\n"
            return Response(err(), mimetype="application/x-ndjson")
        ollama_messages.append({"role": "system", "content": RAG_SYSTEM_PROMPT.format(context=context)})

    # Full multi-turn history so the model has conversation memory
    for m in history:
        ollama_messages.append({"role": m["role"], "content": m["content"]})

    def generate():
        full_response = ""
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={"model": conv["model"], "messages": ollama_messages, "stream": True},
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                token = obj.get("message", {}).get("content", "")
                full_response += token
                payload = {"token": token, "done": obj.get("done", False)}
                if obj.get("done"):
                    payload["sources"] = sources
                yield json.dumps(payload) + "\n"

            db.add_message(conv_id, "assistant", full_response,
                            sources=json.dumps(sources) if sources else None)

        except Exception as e:
            traceback.print_exc()
            yield json.dumps({
                "error": f"Ollama error: {e}. Is 'ollama serve' / '{conv['model']}' running at {OLLAMA_BASE_URL}?"
            }) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


# ---------------------------------------------------------------------------
# Voice: speech-to-text (faster-whisper) and text-to-speech (pyttsx3)
# ---------------------------------------------------------------------------
@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]
    suffix = os.path.splitext(audio_file.filename or "")[1] or ".webm"
    temp_path = voice.save_upload_to_temp(audio_file, suffix=suffix)

    try:
        text, language = voice.transcribe_audio(temp_path)
        return jsonify({"text": text, "language": language})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Transcription failed: {e}"}), 500
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@app.route("/api/speak", methods=["POST"])
def speak():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
    # pyttsx3 chokes on very long input in one go; cap to something sane for a single utterance
    text = text[:2000]

    try:
        wav_path = voice.synthesize_speech(text)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Speech synthesis failed: {e}. Is a TTS voice installed "
                                  f"(espeak/espeak-ng on Linux)?"}), 500

    @after_this_request
    def cleanup(response):
        try:
            os.remove(wav_path)
        except OSError:
            pass
        return response

    return send_file(wav_path, mimetype="audio/wav")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
