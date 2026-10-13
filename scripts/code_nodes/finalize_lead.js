// Runs after the CRM create/update succeeded: remember the lead for dedupe and build the response.
const scored = $('Merge lookup result').first().json;
const crm = $input.first().json;
const store = $getWorkflowStaticData('global');
store.leads = store.leads || {};
store.leads[scored.lead.email] = { ts: Date.now(), crm_id: crm.id };
for (const [email, v] of Object.entries(store.leads)) {
  if (Date.now() - v.ts > 7 * 24 * 3600 * 1000) delete store.leads[email]; // keeps the store small
}
return [
  {
    json: {
      status: scored.crm_contact_id ? 'updated' : 'created',
      crm_id: crm.id,
      email: scored.lead.email,
      name: scored.lead.name,
      company: scored.lead.company,
      score: scored.score,
      tier: scored.tier,
      reason: scored.reason,
      scoring_failed: scored.scoring_failed,
      source: scored.lead.source,
    },
  },
];
