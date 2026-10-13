// Keep the payload and the CRM lookup result together, so the update/create nodes only need $json.
const payload = $('Build CRM payload').first().json;
const hit = (($input.first().json.results) || [])[0];
return [{ json: { ...payload, crm_contact_id: hit ? hit.id : '' } }];
