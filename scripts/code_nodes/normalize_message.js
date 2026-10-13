// One entry shape for both channels. route: process | reject_web | ignore
const MAX_QUESTION = 1000;
const item = $input.first().json;
const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
let out;

if (item.message) {
  // Telegram update
  const t = item.message;
  const text = clean(t.text);
  out = {
    channel: 'telegram',
    session_id: 'tg-' + t.chat.id,
    chat_id: String(t.chat.id),
    user_name: [t.from && t.from.first_name, t.from && t.from.last_name].filter(Boolean).join(' '),
    question: text.slice(0, MAX_QUESTION),
    history: [], // add a memory node if the Telegram bot should remember earlier turns
    route: text && !text.startsWith('/') ? 'process' : 'ignore', // commands and non-text updates are skipped
  };
} else {
  // Website widget: POST { message, session_id?, history?, user?: { name } }
  const b = item.body || {};
  const question = clean(b.message);
  const history = (Array.isArray(b.history) ? b.history : []).slice(-6).map((h) => ({
    role: h && h.role === 'assistant' ? 'assistant' : 'user',
    content: clean(h && h.content).slice(0, 500),
  }));
  out = {
    channel: 'web',
    session_id: clean(b.session_id).slice(0, 64) || 'web-' + Date.now(),
    chat_id: '',
    user_name: clean(b.user && b.user.name).slice(0, 80),
    question,
    history,
    route: question && question.length <= MAX_QUESTION ? 'process' : 'reject_web',
  };
  if (out.route === 'reject_web') {
    out.error = question ? `message is longer than ${MAX_QUESTION} characters` : 'message is required';
  }
}
return [{ json: out }];
