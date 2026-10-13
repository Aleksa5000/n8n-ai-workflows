// Runs one n8n Code-node source file against a fake n8n context. stdin: JSON, stdout: JSON.
//   { file, input: [json...], nodes: { "Node name": [json...] }, env: {}, staticData: {}, today: "2026-10-13" }
const fs = require('fs');
const req = JSON.parse(fs.readFileSync(0, 'utf8'));
const wrap = (rows) => rows.map((json) => ({ json }));
const handle = (rows) => ({ all: () => wrap(rows), first: () => wrap(rows)[0], last: () => wrap(rows).slice(-1)[0] });
const $input = handle(req.input || []);
const $ = (name) => {
  if (!(name in (req.nodes || {}))) throw new Error('unknown node ' + name);
  return handle(req.nodes[name]);
};
const staticData = req.staticData || {};
const $now = { toFormat: () => req.today || '2026-10-13', toISO: () => (req.today || '2026-10-13') + 'T10:00:00.000+00:00' };
const code = fs.readFileSync(req.file, 'utf8');
const fn = new Function('$input', '$', '$env', '$getWorkflowStaticData', '$now', code);
const out = fn($input, $, req.env || {}, () => staticData, $now);
process.stdout.write(JSON.stringify({ items: out.map((i) => i.json), staticData }));
