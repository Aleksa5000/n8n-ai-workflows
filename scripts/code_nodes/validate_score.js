// The tier is derived from the number here, never taken from the model.
// An invalid answer does NOT drop the lead: it is stored as "unscored" for a human to review.
const lead = $('Dedupe check').first().json.lead;
const HOT = Number($env.LEAD_HOT_SCORE || 70);
const WARM = Number($env.LEAD_WARM_SCORE || 40);
const item = $input.first().json;

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

const c = parse(item.output !== undefined ? item.output : item);
const valid =
  c && typeof c === 'object' && typeof c.score === 'number' && Number.isFinite(c.score) &&
  c.score >= 0 && c.score <= 100 && typeof c.reason === 'string' && c.reason.trim().length > 0;
const score = valid ? Math.round(c.score) : 0;
const tier = !valid ? 'unscored' : score >= HOT ? 'hot' : score >= WARM ? 'warm' : 'cold';

return [
  {
    json: {
      lead,
      score,
      tier,
      reason: valid ? c.reason.trim().slice(0, 300) : 'AI scoring failed validation; review this lead manually.',
      scoring_failed: !valid,
    },
  },
];
