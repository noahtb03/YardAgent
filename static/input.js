import { yardState } from './storage.js';
const form = document.querySelector('#design-form');
const inputs = document.querySelector('#inputs');
const status = document.querySelector('#status');
const photo = document.querySelector('#photo');
let savedPhoto = null;
let busy = false;
document.querySelectorAll('[data-style]').forEach(button => {
  button.onclick = () => {
    const intent = document.querySelector('#user-intent');
    intent.value = ((intent.value.trim() ? intent.value.trim() + '. ' : '') + button.dataset.style + ' style').slice(0, 4000);
  };
});
function stage(name, state, text) {
  const row = document.querySelector(`[data-stage="${name}"]`);
  row.dataset.state = state;
  row.querySelector('span').textContent = text;
}
async function post(endpoint, payload) {
  const response = await fetch(endpoint, payload instanceof FormData
    ? { method: 'POST', body: payload }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `${endpoint.slice(1)} failed. Please try again.`);
  return data;
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !form.reportValidity()) return;
  const file = photo.files[0] || savedPhoto;
  if (!file) { status.textContent = 'Choose a yard photo.'; return; }
  if (file.size > 10 * 1024 * 1024) { status.textContent = 'Image must be 10 MiB or smaller.'; return; }
  const budget = document.querySelector('#budget').valueAsNumber;
  const userIntent = document.querySelector('#user-intent').value.trim();
  const area = document.querySelector('#area').value;
  busy = true; inputs.disabled = true;
  document.querySelector('#results').hidden = true;
  document.querySelector('#progress').hidden = false;
  for (const name of ['analyze', 'design', 'source']) stage(name, 'waiting', 'Waiting');
  let current = 'analyze';
  try {
    stage(current, 'running', 'Reading your photo'); status.textContent = 'Analyzing your yard…';
    const upload = new FormData(); upload.append('file', file);
    const analysis = await post('/analyze', upload);
    stage(current, 'done', 'Complete');
    const range = (r, unit) => r ? `${r.min}–${r.max} ${unit}` : 'Scale assumed';
    document.querySelector('#dimensions').textContent = `${range(analysis.width_ft, 'ft')} × ${range(analysis.length_ft, 'ft')}`;
    document.querySelector('#area-range').textContent = range(analysis.area_sq_ft, 'sq ft');
    document.querySelector('#boundary-assumptions').textContent = `${analysis.confidence} confidence. ${(analysis.boundary_assumptions || []).join(' ')}`;
    document.querySelector('#limitations').textContent = analysis.limitations;
    const features = document.querySelector('#features'); features.replaceChildren();
    for (const feature of analysis.existing_features) { const li = document.createElement('li'); li.textContent = feature; features.append(li); }
    document.querySelector('#results').hidden = false;
    current = 'design'; stage(current, 'running', 'Planning additions'); status.textContent = 'Designing your yard…';
    const request = { analysis, budget, user_intent: userIntent };
    if (area !== '') request.area_sq_ft = Number(area);
    const proposedLayout = await post('/design', request);
    stage(current, 'done', 'Complete');
    current = 'source'; stage(current, 'running', 'Comparing retailers'); status.textContent = 'Finding prices and verifying product matches…';
    const layout = await post('/source', { layout: proposedLayout, budget });
    stage(current, 'done', layout.sourcing_complete ? 'Complete' : 'Partial prices');
    await yardState({ analysis, layout, proposedLayout, originalPhoto: file, budget,
      userIntent, area, selectedIds: layout.elements.map(item => item.id) });
    status.textContent = 'Opening your yard…';
    window.location.assign('/view');
  } catch (error) {
    stage(current, 'failed', 'Please retry'); status.textContent = error.message;
  } finally { inputs.disabled = false; busy = false; }
});
try {
  const saved = await yardState();
  if (saved && !busy) {
    savedPhoto = saved.originalPhoto; photo.required = !savedPhoto;
    document.querySelector('#budget').value = saved.budget;
    document.querySelector('#user-intent').value = saved.userIntent || '';
    document.querySelector('#area').value = saved.area || '';
    status.textContent = 'Your previous inputs are restored. Choose a new photo or reuse the analyzed photo.';
  }
} catch { status.textContent = 'Enable browser site storage to save and view your design.'; }
