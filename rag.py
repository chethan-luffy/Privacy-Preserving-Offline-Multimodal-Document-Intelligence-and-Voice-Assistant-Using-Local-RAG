"""
Per-conversation RAG pipeline: PDF/image loading -> OCR -> chunk -> embed ->
FAISS. Each conversation gets its own documents/<id>/ folder and
faiss_index/<id>/ store, so attaching files to one chat never affects
another chat's retrieval.

Build state (status/progress/retriever) lives in an in-memory dict keyed by
conversation id. Like the original offline_rag_app, this state doesn't
survive an app restart — the FAISS files on disk do, but re-loading them
into a live retriever on startup isn't wired up (see README).
"""
import os
import glob
import threading

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_ROOT = os.path.join(BASE_DIR, "documents")
DB_ROOT = os.path.join(BASE_DIR, "faiss_index")
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")
ALL_EXTS = (".pdf",) + IMAGE_EXTS

os.makedirs(DOCS_ROOT, exist_ok=True)
os.makedirs(DB_ROOT, exist_ok=True)

_shared = {"embeddings": None, "ocr_reader": None}
_shared_lock = threading.Lock()

# conv_id -> {status, message, progress, retriever, file_stats}
rag_states = {}
rag_states_lock = threading.Lock()


def docs_dir(conv_id):
    d = os.path.join(DOCS_ROOT, str(conv_id))
    os.makedirs(d, exist_ok=True)
    return d


def db_dir(conv_id):
    d = os.path.join(DB_ROOT, str(conv_id))
    os.makedirs(d, exist_ok=True)
    return d


def get_embeddings():
    with _shared_lock:
        if _shared["embeddings"] is None:
            _shared["embeddings"] = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        return _shared["embeddings"]


def get_ocr_reader():
    with _shared_lock:
        if _shared["ocr_reader"] is None:
            import easyocr
            _shared["ocr_reader"] = easyocr.Reader(["en"], gpu=False)
        return _shared["ocr_reader"]


def ocr_image_to_document(image_path):
    reader = get_ocr_reader()
    lines = reader.readtext(image_path, detail=0, paragraph=True)
    text = "\n".join(lines).strip()
    if not text:
        text = "[No text could be recognized in this image.]"
    return Document(page_content=text, metadata={"source": image_path, "page": 0})


def _set_state(conv_id, **kwargs):
    with rag_states_lock:
        st = rag_states.setdefault(conv_id, {})
        st.update(kwargs)


def get_state(conv_id):
    with rag_states_lock:
        st = rag_states.get(conv_id) or {
            "status": "idle",
            "message": "No documents indexed yet.",
            "progress": 0,
            "retriever": None,
            "file_stats": {},
        }
        # never leak the retriever object itself into API responses
        return {k: v for k, v in st.items() if k != "retriever"}


def list_documents(conv_id):
    d = docs_dir(conv_id)
    return sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(d, "*"))
        if p.lower().endswith(ALL_EXTS)
    )


def build_index_background(conv_id):
    d = docs_dir(conv_id)
    try:
        _set_state(conv_id, status="building", message="Scanning documents...", progress=5, file_stats={})

        all_files = sorted(p for p in glob.glob(os.path.join(d, "*")) if p.lower().endswith(ALL_EXTS))
        pdf_files = [p for p in all_files if p.lower().endswith(".pdf")]
        image_files = [p for p in all_files if p.lower().endswith(IMAGE_EXTS)]

        if not all_files:
            _set_state(conv_id, status="error", message="No PDFs or images attached to this chat.", progress=0)
            return

        docs = []
        raw_char_counts = {}
        for i, pdf_path in enumerate(pdf_files):
            _set_state(conv_id, message=f"Loading {os.path.basename(pdf_path)} ({i + 1}/{len(pdf_files)})",
                       progress=5 + int(15 * (i + 1) / max(len(pdf_files), 1)))
            pdf_docs = PyPDFLoader(pdf_path).load()
            docs.extend(pdf_docs)
            raw_char_counts[os.path.basename(pdf_path)] = sum(len(x.page_content) for x in pdf_docs)

        for i, img_path in enumerate(image_files):
            _set_state(conv_id, message=f"Running OCR on {os.path.basename(img_path)} ({i + 1}/{len(image_files)})",
                       progress=20 + int(15 * (i + 1) / max(len(image_files), 1)))
            img_doc = ocr_image_to_document(img_path)
            docs.append(img_doc)
            raw_char_counts[os.path.basename(img_path)] = len(img_doc.page_content)

        _set_state(conv_id, message="Splitting text into chunks...", progress=40)
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        final_documents = splitter.split_documents(docs)

        chunk_counts = {}
        for doc in final_documents:
            fname = os.path.basename((doc.metadata or {}).get("source", "unknown"))
            chunk_counts[fname] = chunk_counts.get(fname, 0) + 1

        file_stats = {}
        for fname, raw_chars in raw_char_counts.items():
            file_stats[fname] = {
                "raw_chars": raw_chars,
                "chunks": chunk_counts.get(fname, 0),
                "warning": "No extractable text — likely a scanned/image-only PDF" if raw_chars == 0 else None,
            }
        _set_state(conv_id, file_stats=file_stats)

        _set_state(conv_id, message="Loading local embedding model...", progress=55)
        embeddings = get_embeddings()

        _set_state(conv_id, message=f"Embedding {len(final_documents)} chunks and building FAISS index...", progress=75)
        vector_store = FAISS.from_documents(final_documents, embeddings)
        vector_store.save_local(db_dir(conv_id))

        retriever = vector_store.as_retriever(search_kwargs={"k": 4})

        empty_files = [f for f, s in file_stats.items() if s["chunks"] == 0]
        msg = f"Index ready — {len(final_documents)} chunks from {len(pdf_files)} PDF(s) and {len(image_files)} image(s)."
        if empty_files:
            msg += f" ⚠ No text extracted from: {', '.join(empty_files)} — likely scanned/image-only."

        _set_state(conv_id, status="ready", message=msg, progress=100)
        with rag_states_lock:
            rag_states[conv_id]["retriever"] = retriever

    except Exception as e:
        import traceback
        traceback.print_exc()
        _set_state(conv_id, status="error", message=f"Failed: {e}", progress=0)


def start_build(conv_id):
    thread = threading.Thread(target=build_index_background, args=(conv_id,), daemon=True)
    thread.start()


def retrieve(conv_id, query):
    """Return (context_text, sources) for this query, or (None, []) if no
    ready retriever exists for this conversation."""
    with rag_states_lock:
        st = rag_states.get(conv_id)
        retriever = st.get("retriever") if st else None
    if retriever is None:
        return None, []

    result_docs = retriever.invoke(query)
    sources = []
    parts = []
    for doc in result_docs:
        meta = doc.metadata or {}
        sources.append({
            "source": os.path.basename(meta.get("source", "unknown")),
            "page": meta.get("page", None),
        })
        parts.append(doc.page_content)
    return "\n\n".join(parts), sources


def delete_document(conv_id, filename):
    path = os.path.join(docs_dir(conv_id), filename)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
