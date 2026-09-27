// Minimal markdown renderer — no dependencies, so the app never needs a
// CDN or bundler to stay offline. Covers what LLM chat responses actually
// use: code fences, inline code, bold/italic, headers, lists, links, breaks.
function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderMarkdown(src) {
  if (!src) return "";

  // 1. Pull out fenced code blocks first so nothing inside them gets touched.
  const codeBlocks = [];
  let text = src.replace(/```(\w*)\n?([\s\S]*?)```/g, (match, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(
      `<pre class="code-block"><code${lang ? ` data-lang="${escapeHtml(lang)}"` : ""}>${escapeHtml(code.trim())}</code></pre>`
    );
    return `\u0000CODEBLOCK${idx}\u0000`;
  });

  text = escapeHtml(text);

  // Inline code
  text = text.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>');

  // Bold / italic
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");

  // Headers
  text = text.replace(/^###### (.*)$/gm, "<h6>$1</h6>");
  text = text.replace(/^##### (.*)$/gm, "<h5>$1</h5>");
  text = text.replace(/^#### (.*)$/gm, "<h4>$1</h4>");
  text = text.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  text = text.replace(/^## (.*)$/gm, "<h2>$1</h2>");
  text = text.replace(/^# (.*)$/gm, "<h1>$1</h1>");

  // Links
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  // Lists: group consecutive "- " or "1. " lines into <ul>/<ol>
  const lines = text.split("\n");
  const out = [];
  let listType = null; // 'ul' | 'ol' | null
  for (const line of lines) {
    const ulMatch = line.match(/^[-*]\s+(.*)$/);
    const olMatch = line.match(/^\d+\.\s+(.*)$/);
    if (ulMatch) {
      if (listType !== "ul") { if (listType) out.push(`</${listType}>`); out.push("<ul>"); listType = "ul"; }
      out.push(`<li>${ulMatch[1]}</li>`);
    } else if (olMatch) {
      if (listType !== "ol") { if (listType) out.push(`</${listType}>`); out.push("<ol>"); listType = "ol"; }
      out.push(`<li>${olMatch[1]}</li>`);
    } else {
      if (listType) { out.push(`</${listType}>`); listType = null; }
      out.push(line);
    }
  }
  if (listType) out.push(`</${listType}>`);
  text = out.join("\n");

  // Paragraphs: wrap remaining bare lines, collapse blank-line runs
  text = text
    .split(/\n{2,}/)
    .map(block => {
      if (/^\s*<(h\d|ul|ol|pre|li)/.test(block.trim())) return block;
      const withBreaks = block.replace(/\n/g, "<br>");
      return withBreaks.trim() ? `<p>${withBreaks}</p>` : "";
    })
    .join("\n");

  // Restore code blocks
  text = text.replace(/\u0000CODEBLOCK(\d+)\u0000/g, (_, idx) => codeBlocks[Number(idx)]);

  return text;
}
