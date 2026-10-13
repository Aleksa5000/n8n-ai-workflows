// Answer only when the knowledge base had context AND the model returned a valid, answerable,
// confident result. Everything else becomes "I'm not sure" plus an escalation to a human.
const NOT_SURE = "I'm not sure about that one. I've passed your question to our team and someone will follow up with you shortly.";
const MIN_CONFIDENCE = Number($env.ANSWER_MIN_CONFIDENCE || 0.6);
const kb = $('Parse KB response').first().json;

function parse(raw) {
  if (typeof raw !== 'string') return raw;
  const m = raw.match(/\{[\s\S]*\}/);
  if (!m) return null;
  try {
    return JSON.parse(m[0]);
  } catch (e) {
    return null;
  }
}

let answer = null;
let confidence = 0;
let reason = '';

if (!kb.has_context) {
  if (kb.kb_error) reason = 'knowledge base unavailable: ' + kb.kb_error;
  else if (kb.best_score > 0) reason = `no passage scored above ${kb.min_score} (best: ${kb.best_score})`;
  else reason = 'no relevant context found';
} else {
  const item = $input.first().json;
  const c = parse(item.output !== undefined ? item.output : item);
  const valid =
    c && typeof c === 'object' && typeof c.answer === 'string' &&
    typeof c.answerable === 'boolean' && typeof c.confidence === 'number' && c.confidence >= 0 && c.confidence <= 1;
  if (!valid) {
    reason = 'invalid model output';
  } else {
    confidence = c.confidence;
    if (!c.answerable) reason = 'the context does not answer the question';
    else if (!c.answer.trim()) reason = 'invalid model output';
    else if (confidence < MIN_CONFIDENCE) reason = `low confidence (${confidence})`;
    else answer = c.answer.trim().slice(0, 1500);
  }
}

const escalate = answer === null;
const reply_text = escalate ? NOT_SURE : answer;
const conversation = kb.history
  .map((h) => `${h.role === 'assistant' ? 'Bot' : 'Customer'}: ${h.content}`)
  .concat(`Customer: ${kb.question}`, `Bot: ${reply_text}`)
  .join('\n');

return [
  {
    json: {
      channel: kb.channel,
      session_id: kb.session_id,
      chat_id: kb.chat_id,
      user_name: kb.user_name,
      question: kb.question,
      reply_text,
      answered: !escalate,
      escalate,
      escalate_reason: reason,
      confidence,
      sources: escalate ? [] : [...new Set(kb.context.map((c) => c.source))],
      slack_text:
        `*Support bot could not answer* (${reason})\n` +
        `Channel: ${kb.channel} | Session: ${kb.session_id}${kb.user_name ? ' | ' + kb.user_name : ''}\n\n` +
        `*Conversation*\n${conversation}`,
      logged_at: $now.toISO(),
    },
  },
];
