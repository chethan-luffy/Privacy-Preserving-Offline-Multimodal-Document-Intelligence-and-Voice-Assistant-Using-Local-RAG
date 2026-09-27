// ---------------------------------------------------------------------------
// Elements
// ---------------------------------------------------------------------------
const newChatBtn = document.getElementById("new-chat-btn");
const convList = document.getElementById("conv-list");
const ollamaDot = document.getElementById("ollama-dot");
const ollamaStatusText = document.getElementById("ollama-status-text");

const convTitleEl = document.getElementById("conv-title");
const modelSelect = document.getElementById("model-select");
const ragToggleInput = document.getElementById("rag-toggle-input");
const docsBtn = document.getElementById("docs-btn");

const docsPanel = document.getElementById("docs-panel");
const docsCloseBtn = document.getElementById("docs-close-btn");
const docListEl = document.getElementById("doc-list");
const fileInput = document.getElementById("file-input");
const buildBtn = document.getElementById("build-btn");
const progressWrap = document.getElementById("progress-wrap");
const progressFill = document.getElementById("progress-fill");
const progressMsg = document.getElementById("progress-msg");

const messagesEl = document.getElementById("messages");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const micBtn = document.getElementById("mic-btn");
const micStatus = document.getElementById("mic-status");

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentConv = null;   // full conversation object incl. messages
let availableModels = [];
let buildPollTimer = null;
let lastFileStats = {};
let streaming = false;

// ---------------------------------------------------------------------------
// Ollama / models
// ---------------------------------------------------------------------------
async function loadModels() {
  const res = await fetch("/api/models");
  const data = await res.json();
  availableModels = data.models || [];
  modelSelect.innerHTML = "";

  if (data.error || availableModels.length === 0) {
    ollamaDot.className = "dot bad";
    ollamaStatusText.textContent = data.error ? "Ollama not reachable" : "No models pulled";
    const opt = document.createElement("option");
    opt.textContent = data.default;
    opt.value = data.default;
    modelSelect.appendChild(opt);
    return;
  }

  ollamaDot.className = "dot good";
  ollamaStatusText.textContent = `Ollama connected (${availableModels.length} model${availableModels.length === 1 ? "" : "s"})`;
  availableModels.forEach(name => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    modelSelect.appendChild(opt);
  });
}

// ---------------------------------------------------------------------------
// Conversations sidebar
// ---------------------------------------------------------------------------
async function loadConversations() {
  const res = await fetch("/api/conversations");
  const data = await res.json();
  convList.innerHTML = "";
  data.conversations.forEach(conv => {
    const item = document.createElement("div");
    item.className = "conv-item" + (currentConv && currentConv.id === conv.id ? " active" : "");

    const title = document.createElement("span");
    title.className = "conv-item-title";
    title.textContent = conv.title;
    title.onclick = () => selectConversation(conv.id);

    const delBtn = document.createElement("button");
    delBtn.className = "conv-item-del";
    delBtn.textContent = "✕";
    delBtn.onclick = async (e) => {
      e.stopPropagation();
      await fetch(`/api/conversations/${conv.id}`, { method: "DELETE" });
      if (currentConv && currentConv.id === conv.id) {
        currentConv = null;
        showEmptyState();
      }
      loadConversations();
    };

    item.appendChild(title);
    item.appendChild(delBtn);
    convList.appendChild(item);
  });
}

function showEmptyState() {
  convTitleEl.textContent = "Select or start a chat";
  modelSelect.disabled = true;
  ragToggleInput.disabled = true;
  ragToggleInput.checked = false;
  docsBtn.disabled = true;
  docsPanel.classList.add("hidden");
  chatInput.disabled = true;
  sendBtn.disabled = true;
  micBtn.disabled = true;
  messagesEl.innerHTML = `
    <div class="empty-state">
      <h2>Offline Chat</h2>
      <p>Fully local via Ollama. Start a new chat, pick a model, and optionally attach PDFs or photos for it to search.</p>
    </div>`;
}

async function newConversation() {
  const model = modelSelect.value || availableModels[0] || undefined;
  const res = await fetch("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  const conv = await res.json();
  await loadConversations();
  await selectConversation(conv.id);
}

async function selectConversation(id) {
  const res = await fetch(`/api/conversations/${id}`);
  if (!res.ok) return;
  currentConv = await res.json();

  convTitleEl.textContent = currentConv.title;
  modelSelect.disabled = false;
  modelSelect.value = currentConv.model;
  ragToggleInput.disabled = false;
  ragToggleInput.checked = !!currentConv.use_rag;
  docsBtn.disabled = false;
  chatInput.disabled = false;
  sendBtn.disabled = false;
  micBtn.disabled = false;

  renderMessages();
  await loadConversations(); // refresh active highlight
  lastFileStats = {};
  await refreshDocuments();
  await pollBuildStatusOnce();
}

function renderMessages() {
  messagesEl.innerHTML = "";
  if (!currentConv.messages.length) {
    messagesEl.innerHTML = `<div class="empty-state"><p>Say something to get started.</p></div>`;
    return;
  }
  currentConv.messages.forEach(m => {
    const sources = m.sources ? JSON.parse(m.sources) : null;
    addMessageBubble(m.role, m.content, sources);
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addMessageBubble(role, content, sources) {
  const div = document.createElement("div");
  div.className = `msg ${role === "user" ? "user" : "bot"}`;
  const body = document.createElement("div");
  body.className = "msg-body";
  body.innerHTML = renderMarkdown(content);
  div.appendChild(body);

  if (role !== "user") {
    const speakBtn = document.createElement("button");
    speakBtn.className = "speak-btn";
    speakBtn.textContent = "🔊";
    speakBtn.title = "Read aloud";
    speakBtn.onclick = () => speakText(body.dataset.rawText || content, speakBtn);
    div.appendChild(speakBtn);
  }
  body.dataset.rawText = content;

  if (sources && sources.length) {
    const s = document.createElement("div");
    s.className = "sources";
    const seen = new Set();
    const parts = [];
    sources.forEach(src => {
      const label = `${src.source}${src.page != null ? " (p." + (src.page + 1) + ")" : ""}`;
      if (!seen.has(label)) { seen.add(label); parts.push(label); }
    });
    s.textContent = "Sources: " + parts.join(", ");
    div.appendChild(s);
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return body;
}

// ---------------------------------------------------------------------------
// Model / RAG toggle changes
// ---------------------------------------------------------------------------
modelSelect.addEventListener("change", async () => {
  if (!currentConv) return;
  await fetch(`/api/conversations/${currentConv.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: modelSelect.value }),
  });
  currentConv.model = modelSelect.value;
});

ragToggleInput.addEventListener("change", async () => {
  if (!currentConv) return;
  await fetch(`/api/conversations/${currentConv.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ use_rag: ragToggleInput.checked }),
  });
  currentConv.use_rag = ragToggleInput.checked;
  if (ragToggleInput.checked) docsPanel.classList.remove("hidden");
});

docsBtn.addEventListener("click", () => docsPanel.classList.toggle("hidden"));
docsCloseBtn.addEventListener("click", () => docsPanel.classList.add("hidden"));

// ---------------------------------------------------------------------------
// Per-conversation documents
// ---------------------------------------------------------------------------
async function refreshDocuments() {
  if (!currentConv) return;
  const res = await fetch(`/api/conversations/${currentConv.id}/documents`);
  const data = await res.json();
  docListEl.innerHTML = "";
  if (!data.documents.length) {
    docListEl.innerHTML = '<p class="empty">No files attached.</p>';
    buildBtn.disabled = true;
    return;
  }
  buildBtn.disabled = false;
  data.documents.forEach(name => {
    const item = document.createElement("div");
    item.className = "doc-item";

    const info = document.createElement("div");
    info.className = "doc-info";
    const nameSpan = document.createElement("span");
    nameSpan.className = "name";
    nameSpan.textContent = name;
    info.appendChild(nameSpan);

    const stat = lastFileStats[name];
    if (stat) {
      const badge = document.createElement("span");
      if (stat.warning) {
        badge.className = "chunk-badge warn";
        badge.textContent = "0 chunks ⚠";
        badge.title = stat.warning;
      } else {
        badge.className = "chunk-badge ok";
        badge.textContent = `${stat.chunks} chunk${stat.chunks === 1 ? "" : "s"}`;
      }
      info.appendChild(badge);
    }

    const delBtn = document.createElement("button");
    delBtn.textContent = "✕";
    delBtn.onclick = async () => {
      await fetch(`/api/conversations/${currentConv.id}/documents/${encodeURIComponent(name)}`, { method: "DELETE" });
      refreshDocuments();
    };
    item.appendChild(info);
    item.appendChild(delBtn);
    docListEl.appendChild(item);
  });
}

fileInput.addEventListener("change", async () => {
  if (!fileInput.files.length || !currentConv) return;
  const formData = new FormData();
  for (const f of fileInput.files) formData.append("files", f);
  buildBtn.disabled = true;
  const res = await fetch(`/api/conversations/${currentConv.id}/documents`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json();
    alert(err.error || "Upload failed");
  }
  fileInput.value = "";
  lastFileStats = {};
  refreshDocuments();
});

buildBtn.addEventListener("click", async () => {
  if (!currentConv) return;
  const res = await fetch(`/api/conversations/${currentConv.id}/build`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json();
    alert(err.error || "Could not start build");
    return;
  }
  progressWrap.classList.remove("hidden");
  startBuildPolling();
});

async function pollBuildStatusOnce() {
  if (!currentConv) return;
  const res = await fetch(`/api/conversations/${currentConv.id}/build-status`);
  const data = await res.json();
  applyBuildStatus(data);
  if (data.status === "building") startBuildPolling();
}

function applyBuildStatus(data) {
  progressFill.style.width = `${data.progress}%`;
  progressMsg.textContent = data.message;
  if (data.status === "building") {
    progressWrap.classList.remove("hidden");
  } else if (data.status === "ready") {
    lastFileStats = data.file_stats || {};
    refreshDocuments();
  }
}

function startBuildPolling() {
  if (buildPollTimer) return;
  buildPollTimer = setInterval(async () => {
    if (!currentConv) { clearInterval(buildPollTimer); buildPollTimer = null; return; }
    const res = await fetch(`/api/conversations/${currentConv.id}/build-status`);
    const data = await res.json();
    applyBuildStatus(data);
    if (data.status === "ready" || data.status === "error") {
      clearInterval(buildPollTimer);
      buildPollTimer = null;
    }
  }, 1200);
}

// ---------------------------------------------------------------------------
// Streaming chat
// ---------------------------------------------------------------------------
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentConv || streaming) return;
  const question = chatInput.value.trim();
  if (!question) return;

  document.querySelector("#messages .empty-state")?.remove();
  addMessageBubble("user", question, null);
  currentConv.messages.push({ role: "user", content: question, sources: null });
  chatInput.value = "";
  streaming = true;
  chatInput.disabled = true;
  sendBtn.disabled = true;

  const assistantBody = addMessageBubble("assistant", "", null);
  let fullText = "";
  let finalSources = null;

  try {
    const res = await fetch(`/api/conversations/${currentConv.id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question }),
    });

    if (!res.body) throw new Error("Streaming not supported by this browser.");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // last (possibly incomplete) line stays in buffer

      for (const line of lines) {
        if (!line.trim()) continue;
        let obj;
        try { obj = JSON.parse(line); } catch { continue; }

        if (obj.error) {
          fullText += (fullText ? "\n\n" : "") + `⚠ ${obj.error}`;
          assistantBody.innerHTML = renderMarkdown(fullText);
          assistantBody.dataset.rawText = fullText;
          continue;
        }
        if (obj.token) {
          fullText += obj.token;
          assistantBody.innerHTML = renderMarkdown(fullText);
          assistantBody.dataset.rawText = fullText;
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
        if (obj.done) {
          finalSources = obj.sources || null;
        }
      }
    }

    if (finalSources && finalSources.length) {
      const parent = assistantBody.parentElement;
      const s = document.createElement("div");
      s.className = "sources";
      const seen = new Set();
      const parts = [];
      finalSources.forEach(src => {
        const label = `${src.source}${src.page != null ? " (p." + (src.page + 1) + ")" : ""}`;
        if (!seen.has(label)) { seen.add(label); parts.push(label); }
      });
      s.textContent = "Sources: " + parts.join(", ");
      parent.appendChild(s);
    }

    currentConv.messages.push({ role: "assistant", content: fullText, sources: finalSources ? JSON.stringify(finalSources) : null });
    loadConversations(); // title may have just been set from the first message

  } catch (err) {
    assistantBody.innerHTML = renderMarkdown(fullText + `\n\n⚠ Connection error: ${err.message}`);
  } finally {
    streaming = false;
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatInput.focus();
  }
});

// ---------------------------------------------------------------------------
// Voice output (text-to-speech)
// ---------------------------------------------------------------------------
let currentAudio = null;

async function speakText(text, btn) {
  if (!text || !text.trim()) return;

  // Toggle off if this button's audio is already playing
  if (btn.classList.contains("speaking")) {
    if (currentAudio) currentAudio.pause();
    btn.classList.remove("speaking");
    return;
  }

  document.querySelectorAll(".speak-btn.speaking").forEach(b => b.classList.remove("speaking"));
  if (currentAudio) currentAudio.pause();

  btn.classList.add("loading");
  try {
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.error || "Speech synthesis failed");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    currentAudio = new Audio(url);
    btn.classList.remove("loading");
    btn.classList.add("speaking");
    currentAudio.play();
    currentAudio.onended = () => { btn.classList.remove("speaking"); URL.revokeObjectURL(url); };
  } catch (err) {
    alert("Could not reach the server for speech synthesis.");
  } finally {
    btn.classList.remove("loading");
  }
}

// ---------------------------------------------------------------------------
// Voice input (speech-to-text via mic recording)
// ---------------------------------------------------------------------------
let mediaRecorder = null;
let audioChunks = [];
let recording = false;

async function toggleRecording() {
  if (recording) {
    mediaRecorder.stop();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert("This browser doesn't support microphone access.");
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream);

    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };

    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      recording = false;
      micBtn.classList.remove("recording");
      micStatus.textContent = "Transcribing...";
      micStatus.classList.remove("hidden");

      const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
      const formData = new FormData();
      formData.append("audio", blob, "recording.webm");

      try {
        const res = await fetch("/api/transcribe", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) {
          micStatus.textContent = data.error || "Transcription failed.";
        } else {
          chatInput.value = (chatInput.value ? chatInput.value + " " : "") + data.text;
          chatInput.focus();
          micStatus.classList.add("hidden");
        }
      } catch (err) {
        micStatus.textContent = "Could not reach the server for transcription.";
      }
      setTimeout(() => micStatus.classList.add("hidden"), 3000);
    };

    mediaRecorder.start();
    recording = true;
    micBtn.classList.add("recording");
    micStatus.textContent = "Recording... click the mic again to stop.";
    micStatus.classList.remove("hidden");
  } catch (err) {
    alert("Microphone access was denied or unavailable.");
  }
}

micBtn.addEventListener("click", toggleRecording);

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
newChatBtn.addEventListener("click", newConversation);

(async () => {
  await loadModels();
  await loadConversations();
  showEmptyState();
})();
