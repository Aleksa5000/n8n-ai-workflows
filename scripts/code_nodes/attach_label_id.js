// $input holds every Gmail label ("Get Gmail labels" runs once). Gmail needs label IDs, not names.
const labels = $input.all().map((i) => i.json);
const idByName = Object.fromEntries(labels.map((l) => [l.name, l.id]));

return $('Validate classification').all().map((item) => {
  const label_name = 'AI/' + item.json.category;
  return { json: { ...item.json, label_name, label_id: idByName[label_name] || '' } };
});
