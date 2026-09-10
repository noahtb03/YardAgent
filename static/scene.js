import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export async function showScene(container, url, onFailure) {
  const model = await new GLTFLoader().loadAsync(url);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#dce6d6');
  scene.add(model.scene, new THREE.HemisphereLight(0xffffff, 0x777755, 2.5));
  const sun = new THREE.DirectionalLight(0xffffff, 3);
  sun.position.set(-15, 30, 20);
  scene.add(sun);
  const box = new THREE.Box3().setFromObject(model.scene);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.y, size.z, 1);
  const camera = new THREE.PerspectiveCamera(45, 1, .01, span * 100);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI / 2 - .02;
  controls.minDistance = span * .08;
  controls.maxDistance = span * 8;
  container.hidden = false;
  container.replaceChildren(renderer.domElement);
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute('aria-label', '3D yard: drag to rotate, right-drag to pan, scroll to zoom');
  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }
  resize();
  function reset() {
    controls.target.copy(center);
    const distance = span * 1.25 / Math.min(camera.aspect, 1);
    camera.position.copy(center).add(new THREE.Vector3(distance * .65, distance * .85, distance));
    controls.update();
  }
  reset();
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  renderer.domElement.addEventListener('webglcontextlost', event => {
    event.preventDefault(); renderer.setAnimationLoop(null); onFailure();
  }, { once: true });
  window.addEventListener('pagehide', () => {
    observer.disconnect(); controls.dispose(); renderer.setAnimationLoop(null); renderer.dispose();
    model.scene.traverse(object => {
      object.geometry?.dispose();
      if (object.material) for (const material of [object.material].flat()) material.dispose();
    });
  }, { once: true });
  container.dataset.ready = 'true';
  return reset;
}
