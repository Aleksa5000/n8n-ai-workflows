// Demo only (no LLM): "answer" with the best passage, in the same shape the Claude step returns.
// The score is capped at 1 because some backends (BM25) are not 0..1.
const kb = $input.first().json;
const top = kb.context[0];
return [{ json: { output: { answer: `${top.text} (source: ${top.source})`, confidence: Math.min(1, top.score), answerable: true, sources: [top.n] } } }];
