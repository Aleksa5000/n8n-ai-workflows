// Understands two knowledge-base shapes and keeps only passages that score above KB_MIN_SCORE:
//   1. JSON { results: [{ text, source, score }] }  (the mock service, or any small search endpoint)
//   2. docs-rag-assistant POST /api/chat server-sent events: the "sources" event carries the passages
const q = $('Normalize message').first().json;
const MIN_SCORE = Number($env.KB_MIN_SCORE || 0.4);
const MAX_PASSAGES = 4;
const res = $input.first().json;
let hits = [];
let kbError = '';

function sseSources(text) {
  for (const block of text.split(/\r?\n\r?\n/)) {
    if (!/^event:\s*sources/m.test(block)) continue;
    const line = block.split(/\r?\n/).find((l) => l.startsWith('data:'));
    if (line) return JSON.parse(line.slice(5).trim()).sources || [];
  }
  return [];
}

try {
  if (res.error) throw new Error(typeof res.error === 'string' ? res.error : res.error.message || 'request failed');
  const raw = typeof res.data === 'string' ? res.data.trim() : JSON.stringify(res);
  if (raw.startsWith('{')) {
    const j = JSON.parse(raw);
    hits = (j.results || j.sources || []).map((r) => ({ text: r.text, source: r.source || r.filename || r.title || 'kb', score: Number(r.score) }));
  } else if (raw.includes('event: sources')) {
    hits = sseSources(raw).map((r) => ({ text: r.text, source: r.filename + (r.page ? ', p.' + r.page : ''), score: Number(r.score) }));
  }
} catch (e) {
  kbError = String(e.message || e).slice(0, 300);
}

hits.sort((a, b) => b.score - a.score);
const context = hits
  .filter((h) => h.text && h.score >= MIN_SCORE)
  .slice(0, MAX_PASSAGES)
  .map((h, i) => ({ n: i + 1, ...h }));
// Escaped so a passage cannot close the tag or fake an instruction block; the prompt treats it as data.
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

return [
  {
    json: {
      ...q,
      kb_error: kbError,
      has_context: context.length > 0,
      top_score: context.length ? context[0].score : 0,
      best_score: hits.length ? hits[0].score : 0, // best passage even if it was below the threshold
      min_score: MIN_SCORE,
      context,
      context_text: context.map((c) => `<passage id="${c.n}" source="${esc(c.source)}">\n${esc(c.text)}\n</passage>`).join('\n'),
    },
  },
];
