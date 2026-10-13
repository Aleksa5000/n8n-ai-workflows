// Demo entry point: a sample email POSTed to the webhook is turned into the same fields
// that "Normalize email" produces from the Gmail Trigger, so everything after this node is identical.
const b = $input.first().json.body || {};
const raw = String(b.from || '');
const m = raw.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/); // "Name <addr@x.com>" or a bare address

return [
  {
    json: {
      message_id: String(b.message_id || 'demo-' + Date.now()),
      thread_id: String(b.thread_id || 'thread-' + Date.now()),
      from_email: (m ? m[2] : raw).trim().toLowerCase(),
      from_name: m ? m[1].trim() : '',
      subject: String(b.subject || '(no subject)').slice(0, 300),
      body: String(b.body || '').slice(0, 6000),
      received_at: new Date().toISOString(),
      simulate: b.simulate_classifier || null, // lets the demo feed the validator bad "LLM" output on purpose
    },
  },
];
