// Same email inside DEDUPE_WINDOW_MIN minutes = duplicate submission (double click, form retry).
// This only READS the store; "Finalize" writes it after the CRM call succeeded, so a failed run never blocks a retry.
// shortcut: workflow static data is per instance and not shared across queue-mode workers; use Redis, Postgres or Sheets at scale.
const input = $input.first().json;
const store = $getWorkflowStaticData('global');
const windowMs = Number($env.DEDUPE_WINDOW_MIN || 60) * 60000;
const prev = (store.leads || {})[input.lead.email];
const duplicate = Boolean(prev) && Date.now() - prev.ts < windowMs;
return [{ json: { ...input, duplicate, previous_crm_id: prev ? prev.crm_id : '' } }];
