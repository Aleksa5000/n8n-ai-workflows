// Flatten the Gmail Trigger's parsed email (simplify = off) into the fields the rest of the workflow uses.
const MAX_BODY = 6000; // keeps the LLM prompt (and the bill) bounded

return $input.all().map((item) => {
  const m = item.json;
  const from = (m.from && m.from.value && m.from.value[0]) || {};
  const body = String(m.text || m.snippet || '').replace(/\r/g, '').replace(/\n{3,}/g, '\n\n').trim();
  return {
    json: {
      message_id: m.id,
      thread_id: m.threadId,
      from_email: String(from.address || '').toLowerCase(),
      from_name: from.name || '',
      subject: String(m.subject || '(no subject)').slice(0, 300),
      body: body.slice(0, MAX_BODY),
      received_at: m.date || new Date().toISOString(),
    },
  };
});
