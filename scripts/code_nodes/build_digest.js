// Reduce today's rows of the triage log to the numbers the digest needs.
const today = $now.toFormat('yyyy-MM-dd');
const truthy = (v) => String(v).toLowerCase() === 'true';
const rows = $input.all().map((i) => i.json).filter((r) => r['Date'] === today);

const counts = {};
for (const r of rows) counts[r['Category']] = (counts[r['Category']] || 0) + 1;

return [
  {
    json: {
      date: today,
      total: rows.length,
      counts,
      needs_reply: rows.filter((r) => truthy(r['Needs Reply'])).length,
      fallbacks: rows.filter((r) => truthy(r['Fallback'])).length,
      urgent: rows
        .filter((r) => r['Category'] === 'Urgent')
        .slice(0, 10)
        .map((r) => ({ from: r['From'], subject: r['Subject'], summary: r['Summary'] })),
    },
  },
];
