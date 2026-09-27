<<<<<<< HEAD
# Offline Chat — ChatGPT/Claude-style, fully local

A multi-conversation chat app that runs entirely on your machine via
[Ollama](https://ollama.com), with optional per-chat document search (PDFs
and photos, including handwritten notes, via local OCR).

## Features

- **Multiple saved conversations** — sidebar to create, switch, rename (auto
  from first message), and delete chats. Stored in a local SQLite file
  (`app_data.db`), so history survives restarts.
- **Streaming responses** — tokens appear as the model generates them,
  proxied straight from Ollama's native streaming API.
- **Multi-turn memory** — the full conversation history is sent to the model
  each turn, so it remembers earlier messages in the same chat.
- **Model switching** — pick any model you've already pulled into Ollama,
  per conversation, from a dropdown.
- **Optional per-chat document search (RAG)** — toggle "Use documents" on a
  chat, attach PDFs/images, click **Build Index**, and that chat's answers
  will pull from those files. Other chats are unaffected — each conversation
  has its own document folder and FAISS index.
- **Local OCR for photos** — including handwritten notes, via EasyOCR. First
  run downloads its recognition weights (needs internet once); after that,
  everything — chat, embeddings, and OCR — runs fully offline.
- **Voice input** — click the 🎤 next to the input box, speak, click again to
  stop. Transcribed locally with **faster-whisper** and dropped into the
  input box for you to review/edit before sending (it never auto-sends).
- **Voice output** — click 🔊 under any assistant reply to hear it read aloud
  with **pyttsx3**, using your OS's built-in voice (no model download).

## Setup

```bash
cd offline_rag_app
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Pull at least one model in Ollama, e.g.:

```bash
ollama pull qwen2.5:1.5b
ollama pull llama3.2:1b     # optional — pull more to get a model switcher
```

Make sure Ollama is running (`ollama serve`, or just leave the desktop app
open — it serves on `http://localhost:11434` by default).

**Linux only** — `pyttsx3` needs a system TTS engine, which pip can't
install for you:
```bash
sudo apt install espeak-ng   # or: espeak, libespeak1
```
Windows and macOS already ship a built-in voice, so nothing extra is needed
there.

`faster-whisper` downloads its model (default: `small`, ~250MB) the first
time you use voice input. Set `WHISPER_MODEL_SIZE=tiny` (fastest, least
accurate) through `WHISPER_MODEL_SIZE=large-v3` (slowest, most accurate) as
an env var if you want to change that trade-off:
```bash
WHISPER_MODEL_SIZE=base python app.py
```

## Run

```bash
python app.py
```

Open **http://127.0.0.1:5000**.

## Using it

1. Click **+ New chat**. Pick a model from the dropdown in the header.
2. Just type — this is a normal chat, no documents required.
3. To search documents in *this* chat: turn on **Use documents**, click
   **📎 Docs**, upload PDFs/photos, then **Build Index**. Chunk-count badges
   per file tell you whether text was actually extracted (a red "0 chunks ⚠"
   usually means a scanned PDF with no real text layer — OCR only runs on
   images you upload directly, not on pages inside a PDF).
4. Switch chats anytime from the sidebar — each has its own model choice,
   document set, and history.

## Known limitations / things you may want to change

- **State is in-memory + SQLite hybrid.** Conversations and messages persist
  in SQLite across restarts. The *built* FAISS retriever for a chat does
  **not** — the FAISS files stay on disk under `faiss_index/<chat_id>/`, but
  a fresh process needs you to click **Build Index** again before "Use
  documents" works. Wiring up auto-reload from disk on startup is a
  reasonable next step if this bugs you.
- **OCR runs only on directly-uploaded images**, not on scanned pages inside
  a PDF. If you need that too, say the word — it's a matter of rendering PDF
  pages to images and OCR'ing any page `PyPDFLoader` extracts zero text
  from.
- **Single-user, local app.** No auth, no multi-device sync — everything
  lives in the SQLite file and the `documents/` / `faiss_index/` folders
  next to `app.py`.
- **Markdown rendering is a small custom renderer**, not a full CommonMark
  implementation — deliberately, so nothing needs a CDN or npm build step to
  stay 100% offline. It covers headers, bold/italic, code blocks, inline
  code, lists, and links; edge cases in exotic markdown may not render
  perfectly.
- **Retriever `k=4`** (top 4 chunks) per RAG query — fine for direct
  questions, less reliable for "summarize everything" style questions across
  a long document, since it only sees a slice, not the whole file.
- **pyttsx3's voice quality is whatever your OS ships** — functional, not
  natural. If you want a noticeably better voice later, Coqui TTS is a
  drop-in-ish swap in `voice.py`'s `synthesize_speech()`, at the cost of a
  much heavier dependency.
- **Voice input records one utterance per click**, not continuous
  hands-free listening — click to start, click to stop, review the text,
  then send. Wake-word / always-listening mode would be a separate (bigger)
  feature.
=======
# Privacy-Preserving-Offline-Multimodal-Document-Intelligence-and-Voice-Assistant-Using-Local-RAG
Offline Chat — ChatGPT/Claude-style, fully local  A multi-conversation chat app that runs entirely on your machine via [Ollama](https://ollama.com), with optional per-chat document search (PDFs and photos, including handwritten notes, via local OCR).
>>>>>>> 07f0ff5bd75b3f2f70f57d0ccb46a3c270821bdb
