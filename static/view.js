import { yardState } from './storage.js';
import { showPrices } from './prices.js';

const status = document.querySelector('#view-status');
const renderStatus = document.querySelector('#render-status');
const renderButton = document.querySelector('#render-yard');
let state;
let fallingBack = false;

async function photoRender() {
  if (renderButton.disabled) return;
  renderButton.disabled = true;
  renderStatus.textContent = 'Rendering your redesigned yard… This may take a few minutes.';
  try {
    if (!state.renderImage) {
      const elements = state.layout.elements.filter(e => e.sourced_product || e.estimated_feature);
      if (!elements.length) throw new Error('No priced items to render. Your selected items remain in the sidebar.');
      if (!state.originalPhoto) throw new Error('Original photo unavailable. Return to the input page to upload it.');
      const original = await new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('Could not read original photo.'));
        reader.readAsDataURL(state.originalPhoto);
      });
      const response = await fetch('/render', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis: state.analysis, layout: { ...state.layout, elements }, original_photo: original }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Photo rendering failed. Please retry.');
      if (!data.image_url?.startsWith('data:image/png;base64,')) throw new Error('Invalid photo render. Please retry.');
      state.renderImage = data.image_url;
    }
    const image = document.querySelector('#rendered-photo');
    image.src = state.renderImage;
    await image.decode();
    document.querySelector('#render-results').hidden = false;
    renderStatus.textContent = 'Rendering complete.';
    renderButton.hidden = true;
    try { await yardState(state); } catch { /* The displayed image still works. */ }
  } catch (error) {
    state.renderImage = null;
    renderStatus.textContent = error.message;
  } finally { renderButton.disabled = false; }
}

async function fallback() {
  if (fallingBack) return;
  fallingBack = true;
  document.querySelector('#scene').hidden = true;
  document.querySelector('#scene-controls').hidden = true;
  document.querySelector('#fallback').hidden = false;
  status.textContent = '3D preview unavailable. Showing the photo preview and selected items.';
  if (state.originalPhoto) {
    const url = URL.createObjectURL(state.originalPhoto);
    document.querySelector('#original-photo').src = url;
    window.addEventListener('pagehide', () => URL.revokeObjectURL(url), { once: true });
  }
  await photoRender();
}
renderButton.addEventListener('click', photoRender);

try {
  state = await yardState();
  if (!state) {
    status.textContent = 'No saved design in this tab. Start on the input page to upload a photo and select your items.';
  } else {
    showPrices(state.layout, state);
    for (const note of [...state.layout.notes, ...(state.layout.warnings || [])]) {
      const li = document.createElement('li'); li.textContent = note;
      document.querySelector('#layout-notes').append(li);
    }
    status.textContent = 'Building your 3D yard…';
    try {
      let model = state.model;
      if (!model?.model_url) {
        const response = await fetch('/model', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ analysis: state.analysis, layout: state.layout,
            existing_feature_bounds: state.existingFeatureBounds || [] }),
        });
        if (!response.ok) throw new Error('3D generation failed');
        model = await response.json();
      }
      for (const warning of model.warnings || []) {
        const li = document.createElement('li'); li.textContent = warning;
        document.querySelector('#scene-warnings').append(li);
      }
      if (!model.model_url || model.fallback) throw new Error('Blender unavailable');
      const { showScene } = await import('./scene.js');
      const reset = await showScene(document.querySelector('#scene'), model.model_url, fallback);
      document.querySelector('#reset-camera').onclick = reset;
      document.querySelector('#scene-controls').hidden = false;
      status.textContent = '3D yard ready. Existing features are included as static geometry.';
      state.model = model;
      try { await yardState(state); } catch { /* Keep the loaded scene. */ }
    } catch {
      state.model = null;
      await fallback();
    }
  }
} catch {
  status.textContent = 'Could not load your saved design. Return to the input page and confirm your selections again.';
}
