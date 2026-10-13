// Validate and normalise the form payload. Failures are answered with 401/422 by the next nodes.
const req = $input.first().json;
const b = req.body || {};
const secret = $env.LEAD_WEBHOOK_SECRET || '';
const clean = (s, max) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim().slice(0, max);

if (secret && (req.headers || {})['x-webhook-secret'] !== secret) {
  return [{ json: { ok: false, status_code: 401, errors: ['missing or invalid X-Webhook-Secret header'] } }];
}

const errors = [];
const email = clean(b.email, 254).toLowerCase();
if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) errors.push('email is missing or invalid');
const name = clean(b.name, 120);
if (!name) errors.push('name is required');
const phone = clean(b.phone, 40).replace(/[^\d+]/g, '');
if (phone && !/^\+?\d{6,15}$/.test(phone)) errors.push('phone is invalid');
if (errors.length) return [{ json: { ok: false, status_code: 422, errors } }];

const [firstname, ...rest] = name.split(' ');
return [
  {
    json: {
      ok: true,
      lead: {
        email,
        name,
        firstname,
        lastname: rest.join(' '),
        company: clean(b.company, 120),
        phone,
        message: String(b.message == null ? '' : b.message).trim().slice(0, 2000),
        source: clean(b.source, 60) || 'web-form',
        received_at: new Date().toISOString(),
      },
    },
  },
];
