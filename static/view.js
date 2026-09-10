import { yardState } from './storage.js';
import { showPrices } from './prices.js';
import { selectedLayout } from './selection.js';

const $ = selector => document.querySelector(selector);
const status = $('#view-status'), button = $('#render-yard');
let state, selectedIds, sceneController, busy = false, dirty = false;
const currentLayout = () => selectedLayout(state.layout, selectedIds, state.budget || state.layout.budget || 0);
function stage(name, value, message) {
  $(`[data-stage="${name}"]`).dataset.state = value;
  $(`#${name}-status`).textContent = message;
}
async function save() { try { await yardState(state); } catch { status.textContent = 'Preview available, but browser storage could not save it.'; } }
function list(selector, messages) {
  $(selector).replaceChildren(...messages.map(message => {
    const li = document.createElement('li'); li.textContent = message; return li;
  }));
}
function refreshItems() {
  showPrices(currentLayout(), state, selectedIds, async (id, checked) => {
    if (checked) selectedIds.add(id); else selectedIds.delete(id);
    state.selectedIds = [...selectedIds];
    state.renderImage = state.renderLayout = state.reconciliation = state.model = null;
    dirty = true;
    sceneController?.setSelection(selectedIds);
    refreshItems();
    $('#render-results').hidden = true;
    $('#corrected-data').hidden = true;
    list('#corrections', []);
    stage('render','waiting','Selection changed. Update the preview to show these items.');
    stage('reconcile','waiting','Waiting for the updated photo.');
    stage('model','waiting','Selection updated; update the preview to rebuild from the new photo.');
    button.hidden = false; button.textContent = 'Update preview';
    status.textContent = 'Totals updated. The walkthrough will be rebuilt after the new photo is checked.';
    await save();
  });
  $('#sourced-items').querySelectorAll('input').forEach(input => { input.disabled ||= busy; });
}
async function post(endpoint, payload) {
  const response = await fetch(endpoint, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload),
    ...(endpoint === '/reconcile' ? {signal:AbortSignal.timeout(105000)} : {}) });
  let data;
  try { data = await response.json(); } catch { throw new Error(`${endpoint.slice(1)} failed. Please retry.`); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `${endpoint.slice(1)} failed. Please retry.`);
  return data;
}
function originalData() {
  if (!state.originalPhoto) throw new Error('Original photo unavailable. Return to the input page to upload it.');
  return new Promise((resolve,reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Could not read original photo.'));
    reader.readAsDataURL(state.originalPhoto);
  });
}
function fallback() {
  $('#scene').hidden = $('#scene-controls').hidden = true;
  $('#fallback').hidden = false;
  stage('model','failed','3D unavailable. Showing the before/after and item list.');
  status.textContent = state.reconciliation?.skipped ? 'Reconciliation skipped. The 3D preview is unavailable; the photo remains visible.'
    : 'Photo and reconciliation complete. The 3D preview is unavailable.';
  button.hidden = false; button.textContent = 'Retry 3D';
}
async function runPreview() {
  if (busy) return;
  if (dirty || sceneController) { await save(); location.reload(); return; }
  busy = true; button.disabled = true; button.hidden = true; refreshItems();
  let current = 'render';
  try {
    const original = await originalData();
    stage('render','running','Editing your original photo with the selected products...');
    status.textContent = 'Stage 1 of 3: generating the before/after. This may take a few minutes.';
    if (!state.renderImage) {
      const layout = currentLayout();
      state.renderLayout = {...layout, elements:layout.elements.filter(e => e.sourced_product || e.estimated_feature)};
      const data = await post('/render', {analysis:state.analysis, layout:state.renderLayout, original_photo:original});
      if (!data.image_url?.startsWith('data:image/png;base64,')) throw new Error('Invalid photo render. Please retry.');
      state.renderImage = data.image_url;
    }
    $('#rendered-photo').src = state.renderImage;
    try { await $('#rendered-photo').decode(); } catch { state.renderImage=null; throw new Error('Invalid photo render. Please retry.'); }
    $('#render-results').hidden = false;
    stage('render','done','Before/after ready.');
    await save();

    current = 'reconcile'; stage(current,'running','Reading the redesigned image and correcting the layout...');
    status.textContent = 'Stage 2 of 3: checking depicted items and existing features.';
    if (!state.reconciliation) {
      const originalLayout = state.renderLayout || currentLayout();
      let result;
      try {
        result = await post('/reconcile', {analysis:state.analysis, layout:originalLayout,
          original_photo:original, redesigned_photo:state.renderImage, existing_feature_bounds:state.existingFeatureBounds || []});
        if (!Array.isArray(result?.layout?.elements) || !Array.isArray(result.corrections)
            || !result.layout.elements.every(e => e && typeof e.id === 'string' && typeof e.type === 'string'
              && Number.isInteger(e.quantity) && e.quantity > 0
              && ['position_x_ft','position_y_ft','width_ft','length_ft'].every(k=>Number.isFinite(e[k])))
            || !Array.isArray(result.layout.notes) || !Number.isFinite(result.layout.sourced_materials_total_usd)
            || !Number.isFinite(result.layout.estimated_features_range_usd?.min)
            || !Number.isFinite(result.layout.estimated_features_range_usd?.max)
            || !(result.depicted_instances === null || Array.isArray(result.depicted_instances))
            || !Array.isArray(result.existing_feature_bounds)) {
          throw new Error('Incomplete reconciliation response.');
        }
      } catch (error) {
        console.warn('Reconciliation skipped:',error);
        result = {layout:originalLayout, skipped:true, depicted_instances:null,
          existing_feature_bounds:state.existingFeatureBounds || [], confidence:'low',
          corrections:['Reconciliation skipped. Using the original sourced layout to build 3D.'],
          limitations:'Image placement was not verified.'};
      }
      // A skipped reconciliation must never change selections, prices or geometry.
      if (result.skipped) { result.layout=originalLayout; result.depicted_instances=null; }
      state.reconciliation = result;
      if (!result.skipped) {
      const corrected = new Map(result.layout.elements.map(e => [e.id,e]));
      const requested = new Set((state.renderLayout?.elements || []).map(e => e.id));
      state.layout = {...result.layout, elements:[...state.layout.elements.map(e => corrected.get(e.id) || e),
        ...result.layout.elements.filter(e => !state.layout.elements.some(old => old.id===e.id))]};
      for (const id of requested) if (!corrected.has(id)) selectedIds.delete(id);
      for (const id of corrected.keys()) selectedIds.add(id);
      state.selectedIds = [...selectedIds];
      }
    }
    const reconciliation = state.reconciliation;
    list('#corrections', [...(reconciliation.corrections || []),
      ...(Array.isArray(reconciliation.observations?.elements) ? reconciliation.observations.elements : [])
        .filter(e=>e && typeof e.observation === 'string').map(e => `${e.depicted_type}: ${e.observation}`)]);
    $('#corrected-json').textContent = JSON.stringify(reconciliation.layout,null,2);
    $('#corrected-data').hidden = false;
    stage(current,reconciliation.skipped ? 'skipped' : 'done',reconciliation.skipped
      ? 'Reconciliation skipped. Proceeding to 3D with the original layout.'
      : `${reconciliation.confidence || 'low'} confidence. ${reconciliation.limitations || 'Positions inferred from perspective.'}`);
    refreshItems(); await save();

    current = 'model'; stage(current,'running',reconciliation.skipped ? 'Building the walkthrough from the original layout...' : 'Building the walkthrough from the corrected layout...');
    status.textContent = 'Stage 3 of 3: building the 3D yard.';
    $('#fallback').hidden = true;
    if (!state.model || state.model.fallback || state.model.scene_version !== 4) {
      state.model = await post('/model', {analysis:state.analysis, layout:reconciliation.layout,
        existing_feature_bounds:reconciliation.existing_feature_bounds,
        ...(reconciliation.depicted_instances ? {depicted_instances:reconciliation.depicted_instances} : {})});
      await save();
    }
    list('#scene-warnings',state.model.warnings || []);
    if (!state.model.model_url || state.model.fallback) { fallback(); return; }
    const {showScene} = await import('./scene.js');
    sceneController = await showScene($('#scene'),state.model.model_url,fallback);
    sceneController.setSelection(selectedIds);
    $('#reset-camera').onclick = sceneController.reset;
    $('#scene-controls').hidden = false;
    stage(current,'done',reconciliation.skipped ? 'Walkthrough ready, using the original layout. Reconciliation was skipped.' : 'Walkthrough ready, using the corrected image-derived layout.');
    status.textContent = reconciliation.skipped ? 'Before/after and 3D ready. Reconciliation skipped.' : 'Before/after, reconciliation and 3D ready.';
  } catch (error) {
    stage(current,'failed',error.message);
    if (current === 'model') { list('#scene-warnings',[error.message]); fallback(); }
    else {
      status.textContent = `${current === 'render' ? 'Photo editing' : 'Reconciliation'} paused. Retry to continue from this stage.`;
      button.hidden = false; button.textContent = current === 'render' ? 'Retry photo render' : 'Retry reconciliation';
    }
  } finally { busy=false; button.disabled=false; refreshItems(); }
}
button.onclick = runPreview;
try {
  state = await yardState();
  if (!state) status.textContent = 'No saved design in this tab. Start on the input page.';
  else {
    if (state.previewVersion !== 1) {
      state.renderImage = state.reconciliation = state.model = null;
      state.previewVersion = 1;
    }
    selectedIds = new Set(state.selectedIds || state.layout.elements.map(e=>e.id));
    // Undo persisted size clamps and automatic area removals from scene version 5.
    if (state.model?.scene_version === 5) {
      const original = new Map((state.reconciliation?.layout?.elements || state.renderLayout?.elements || []).map(e=>[e.id,e]));
      state.layout.elements = state.layout.elements.map(e=>original.get(e.id) || e);
      for (const id of state.model.omitted_element_ids || []) if (original.has(id)) selectedIds.add(id);
      state.selectedIds = [...selectedIds];
      state.model = null;
    }
    refreshItems();
    list('#layout-notes',[...(state.layout.notes || []), ...(state.layout.warnings || []),
      ...(state.layout.existing_feature_decisions || []).map(d=>`${d.feature}: ${d.action} — ${d.reason}`)]);
    if (state.originalPhoto) {
      const url=URL.createObjectURL(state.originalPhoto); $('#original-photo').src=url;
      window.addEventListener('pagehide',()=>URL.revokeObjectURL(url),{once:true});
    }
    await runPreview();
  }
} catch { status.textContent = 'Could not load your saved design. Return to the input page.'; }
