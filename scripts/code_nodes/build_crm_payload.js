// HubSpot-style contact properties. Empty values are left out so an update never blanks existing CRM data.
// ai_lead_score, ai_lead_tier, ai_lead_reason and lead_source are custom properties: create them in the CRM first.
const d = $input.first().json;
const l = d.lead;
const all = {
  email: l.email,
  firstname: l.firstname,
  lastname: l.lastname,
  company: l.company,
  phone: l.phone,
  message: l.message,
  lead_source: l.source,
  ai_lead_score: d.score,
  ai_lead_tier: d.tier,
  ai_lead_reason: d.reason,
};
const crm_properties = Object.fromEntries(Object.entries(all).filter(([, v]) => v !== '' && v != null));
return [{ json: { ...d, crm_properties } }];
