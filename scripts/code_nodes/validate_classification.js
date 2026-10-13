// Never trust model output. Parse it, check it against the schema, and fall back to "Routine"
// (no draft, flagged for a human) when anything is wrong. One result per email, in input order.
const CATEGORIES = ['Urgent', 'Important', 'Client', 'Billing', 'Routine', 'Informational', 'Low Value'];
const FALLBACK = 'Routine';
const emails = $('Normalize email').all();

function parse(raw) {
  if (typeof raw !== 'string') return raw;
  const m = raw.match(/\{[\s\S]*\}/); // tolerate prose or code fences around the JSON
  if (!m) return null;
  try {
    return JSON.parse(m[0]);
  } catch (e) {
    return null;
  }
}

function check(c) {
  if (!c || typeof c !== 'object' || Array.isArray(c)) return ['output is not a JSON object'];
  const errors = [];
  if (!CATEGORIES.includes(c.category)) errors.push('category must be one of ' + CATEGORIES.join(', '));
  if (typeof c.confidence !== 'number' || !(c.confidence >= 0 && c.confidence <= 1)) errors.push('confidence must be a number from 0 to 1');
  if (typeof c.summary !== 'string' || !c.summary.trim()) errors.push('summary must be a non-empty string');
  if (typeof c.needs_reply !== 'boolean') errors.push('needs_reply must be a boolean');
  if (typeof c.reply_draft !== 'string') errors.push('reply_draft must be a string');
  return errors;
}

return $input.all().map((item, i) => {
  const email = emails[i].json;
  const raw = item.json.output !== undefined ? item.json.output : item.json;
  const c = parse(raw);
  const errors = check(c);
  const ok = errors.length === 0;
  const draft = ok && c.needs_reply ? c.reply_draft.trim().slice(0, 4000) : '';
  return {
    json: {
      message_id: email.message_id,
      thread_id: email.thread_id,
      from_email: email.from_email,
      from_name: email.from_name,
      subject: email.subject,
      received_at: email.received_at,
      category: ok ? c.category : FALLBACK,
      confidence: ok ? c.confidence : 0,
      summary: ok ? c.summary.trim().slice(0, 300) : 'Automatic classification failed validation; please triage manually.',
      reason: ok ? String(c.reason || '').slice(0, 200) : '',
      needs_reply: draft.length > 0,
      reply_draft: draft,
      fallback: !ok,
      validation_errors: errors.join('; '),
    },
  };
});
