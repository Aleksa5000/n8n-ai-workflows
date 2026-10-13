// Demo only: the production workflow asks Claude to write the digest; here it is a plain template.
const d = $input.first().json;
const lines = [`Daily inbox digest for ${d.date}: ${d.total} emails triaged.`];
const parts = Object.entries(d.counts).map(([k, v]) => `${k}: ${v}`);
if (parts.length) lines.push(parts.join(', '));
lines.push(`${d.needs_reply} need a reply (drafts are waiting in Gmail), ${d.fallbacks} fell back to Routine.`);
for (const u of d.urgent) lines.push(`URGENT - ${u.from}: ${u.subject}`);
return [{ json: { ...d, text: lines.join('\n') } }];
