// Turn the Error Trigger payload into one readable alert.
// Failures of a trigger node itself arrive as "trigger" instead of "execution".
const e = $input.first().json;
const wf = e.workflow || {};
const ex = e.execution || {};
const err = ex.error || (e.trigger || {}).error || {};
const node = ex.lastNodeExecuted || (err.node && err.node.name) || 'unknown';
const message = String(err.message || 'unknown error').slice(0, 500);
const url = ex.url || '(no execution URL: the trigger failed before an execution was created)';
const text = [
  `[n8n ALERT] Workflow failed: ${wf.name || 'unknown'}`,
  `Failed node: ${node}`,
  `Error: ${message}`,
  `Execution: ${url}`,
  `Mode: ${ex.mode || 'trigger'}`,
].join('\n');
return [{ json: { text, workflow: wf.name || 'unknown', node, message, execution_url: url } }];
