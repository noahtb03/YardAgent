import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { EYE_HEIGHT, groundHeight, canStand, spawnPoint, moveWithCollision } from './walking.js';
import { upgradeMaterials, addEnvironment, postProcessing } from './scene-quality.js';

function grassTexture() {
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 512;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#778354'; ctx.fillRect(0,0,512,512);
  let seed = 19;
  const random = () => { seed = (1664525*seed+1013904223)>>>0; return seed/4294967296; };
  for (let i=0;i<24000;i++) {
    const x=random()*512,y=random()*512;
    ctx.strokeStyle = ['#657643','#8d985b','#45592c','#acaa75'][i%4];
    ctx.lineWidth = .6+random(); ctx.beginPath(); ctx.moveTo(x,y); ctx.lineTo(x+random()*4-2,y-2-random()*9); ctx.stroke();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function instanceParts(group) {
  const batches = new Map();
  group.updateWorldMatrix(true,true);
  const inverse = group.matrixWorld.clone().invert();
  group.traverse(mesh => {
    if (!mesh.isMesh || mesh.isInstancedMesh || Array.isArray(mesh.material) || mesh.material.transparent) return;
    const key = mesh.geometry.uuid + mesh.material.uuid;
    if (!batches.has(key)) batches.set(key, []);
    batches.get(key).push(mesh);
  });
  for (const meshes of batches.values()) {
    if (meshes.length < 2) continue;
    const first = meshes[0];
    const batch = new THREE.InstancedMesh(first.geometry, first.material, meshes.length);
    batch.name = first.name + ' instances';
    meshes.forEach((mesh,i) => batch.setMatrixAt(i,new THREE.Matrix4().multiplyMatrices(inverse,mesh.matrixWorld)));
    batch.instanceMatrix.needsUpdate = true;
    batch.castShadow = batch.receiveShadow = true;
    batch.computeBoundingSphere();
    for (const mesh of meshes) mesh.removeFromParent();
    group.add(batch);
  }
}

export async function showScene(container, url, onFailure) {
  const model = await new GLTFLoader().loadAsync(url);
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate=false;
  renderer.shadowMap.needsUpdate=true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#b7d4e0');
  scene.add(model.scene, new THREE.HemisphereLight(0xd7ecff,0x847354,1.45),new THREE.AmbientLight(0xffead0,.25));
  let width, length;
  const groups = [], fills = [], surfaces = [], environmentGroups=[];
  const grass = grassTexture();
  grass.anisotropy = Math.min(8,renderer.capabilities.getMaxAnisotropy());
  model.scene.traverse(object => {
    if (object.userData.yard_width_m) { width=object.userData.yard_width_m; length=object.userData.yard_length_m; }
    if ('element_id' in object.userData) groups.push(object);
    if (object.userData.fill_for) fills.push(object);
    if (object.userData.environment_geometry && object.children.length) environmentGroups.push(object);
    if (object.isMesh) {
      object.castShadow = object.material.name !== 'Grass' && object.material.name !== 'Water';
      object.receiveShadow = true;
      if (object.material.name === 'Grass') {
        object.material.map = grass; object.material.bumpMap = grass; object.material.bumpScale = .018;
        object.material.color.set('#a8b681'); object.material.roughness = .97;
        const position=object.geometry.getAttribute('position');
        const colors=new Float32Array(position.count*3);
        for(let i=0;i<position.count;i++){
          const x=position.getX(i),z=position.getZ(i),y=position.getY(i);
          const variation=.88+.10*Math.sin(x*.43+y*.18+z*.23)+.07*Math.cos(x*.13-y*.71+z*.31);
          colors.set([variation,variation*.98,variation*.91],i*3);
        }
        object.geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));object.material.vertexColors=true;
      }
    }
  });
  const box = new THREE.Box3().setFromObject(model.scene);
  const center = new THREE.Vector3();
  const size = box.getSize(new THREE.Vector3());
  width ||= size.x; length ||= size.z;
  center.set(width/2,0,-length/2);
  const span = Math.max(width,length,1);
  const materialQuality=upgradeMaterials(model.scene,renderer);
  for (const group of [...groups,...environmentGroups]) {
    if (group.userData.walk_surface) surfaces.push({ group, bounds: new THREE.Box3().setFromObject(group), height: group.userData.walk_surface });
    instanceParts(group);
  }
  const sun = new THREE.DirectionalLight(0xffd6a0,2.8);
  sun.position.copy(center).add(new THREE.Vector3(-span,span*.52,span*.6));
  sun.target.position.copy(center);
  sun.castShadow = true; sun.shadow.mapSize.set(2048,2048);
  Object.assign(sun.shadow.camera,{left:-span,right:span,top:span,bottom:-span,near:.1,far:span*5});
  sun.shadow.normalBias = .025; sun.shadow.bias = -.00015; sun.shadow.radius = 3;
  scene.add(sun,sun.target);
  const disposeEnvironment=addEnvironment(scene,center,span,renderer);
  const camera = new THREE.PerspectiveCamera(60,1,.03,span*100);
  let effects=null;
  const orbit = new OrbitControls(camera,renderer.domElement);
  orbit.enableDamping = false; orbit.maxPolarAngle = Math.PI/2-.02;
  orbit.minDistance = span*.08; orbit.maxDistance = span*8;
  const pointer = new PointerLockControls(camera,renderer.domElement);
  pointer.minPolarAngle = .12; pointer.maxPolarAngle = Math.PI-.12;
  const toggle = document.querySelector('#mode-toggle');
  const walkStatus = document.querySelector('#walk-status');
  const keys = new Set();
  let mode = 'orbit', obstacles = [], disposed = false, lockTimer, needsRender=true;
  orbit.addEventListener('change',()=>{needsRender=true;});
  pointer.addEventListener('change',()=>{needsRender=true;});
  const coarse = matchMedia('(pointer: coarse)').matches;
  container.hidden=false; container.replaceChildren(renderer.domElement);
  renderer.domElement.tabIndex=0;
  renderer.domElement.setAttribute('aria-label','3D yard: WASD and mouse in walk mode; drag and scroll in orbit mode');
  function resize() {
    camera.aspect=container.clientWidth/container.clientHeight; camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth,container.clientHeight,false);
    effects?.resize(container.clientWidth,container.clientHeight);
    needsRender=true;
  }
  resize();
  try { effects=postProcessing(renderer,scene,camera,container.clientWidth,container.clientHeight); }
  catch { /* Keep the lit 3D scene when optional postprocessing is unsupported. */ }
  container.dataset.effects=effects?'ao+bloom':'basic';
  function standingHeight(x,z) {
    let height = groundHeight(x,z);
    for (const surface of surfaces) if (surface.group.visible && x>=surface.bounds.min.x && x<=surface.bounds.max.x && z>=surface.bounds.min.z && z<=surface.bounds.max.z) height=Math.max(height,surface.height);
    return EYE_HEIGHT+height;
  }
  function resetOrbit(message = 'Orbit mode. Drag to rotate, right-drag to pan, scroll to zoom.') {
    needsRender=true;
    mode='orbit'; container.dataset.mode=mode; keys.clear(); clearTimeout(lockTimer);
    if (pointer.isLocked) pointer.unlock();
    orbit.enabled=true; orbit.target.copy(center);
    const distance=span*1.1/Math.min(camera.aspect,1);
    camera.position.copy(center).add(new THREE.Vector3(distance*.65,distance*.85,distance));
    orbit.update(); toggle.textContent='Walk mode'; walkStatus.textContent=message;
  }
  function prepareWalk() {
    needsRender=true;
    const point=spawnPoint(width,length,obstacles);
    if (!point) { resetOrbit('No clear walking space. Orbit mode is available.'); return false; }
    orbit.enabled=false; mode='walk-ready'; container.dataset.mode=mode;
    camera.position.set(point.x,standingHeight(point.x,point.z),point.z);
    camera.lookAt(point.x,camera.position.y,-length);
    toggle.textContent='Enter walk mode'; walkStatus.textContent='Click Enter walk mode or the yard. WASD to move, mouse to look, Esc for orbit.';
    return true;
  }
  function enterWalk() {
    if (coarse || !renderer.domElement.requestPointerLock) { resetOrbit('Walk controls unavailable on this device. Using orbit mode.'); return; }
    if (mode==='orbit' && !prepareWalk()) return;
    try {
      // PointerLockControls handles mouse-look and lock events. Capture the
      // browser promise here too so a rejected lock never leaks an error.
      const pending = renderer.domElement.requestPointerLock();
      pending?.catch(() => resetOrbit('Mouse capture unavailable. Using orbit mode.'));
      lockTimer=setTimeout(() => { if (!pointer.isLocked) resetOrbit('Mouse capture unavailable. Using orbit mode.'); },1500);
    } catch { resetOrbit('Walk controls unavailable. Using orbit mode.'); }
  }
  toggle.onclick=() => { if (mode==='walk') resetOrbit(); else enterWalk(); };
  renderer.domElement.addEventListener('click',() => { if (mode==='walk-ready') enterWalk(); });
  pointer.addEventListener('lock',() => {
    clearTimeout(lockTimer); mode='walk'; container.dataset.mode=mode;
    toggle.textContent='Orbit mode'; walkStatus.textContent='WASD to move · Mouse to look · Esc to return to orbit';
  });
  pointer.addEventListener('unlock',() => { if (mode!=='orbit') resetOrbit(); });
  const lockError=() => resetOrbit('Mouse capture failed. Using orbit mode.');
  document.addEventListener('pointerlockerror',lockError);
  const keyDown=event => {
    if (event.code==='Escape' && mode!=='orbit') resetOrbit();
    if (mode==='walk' && ['KeyW','KeyA','KeyS','KeyD'].includes(event.code)) { keys.add(event.code); event.preventDefault(); }
  };
  const clearKeys=() => keys.clear();
  const keyUp=event => keys.delete(event.code);
  window.addEventListener('keydown',keyDown); window.addEventListener('keyup',keyUp); window.addEventListener('blur',clearKeys);
  document.addEventListener('visibilitychange',clearKeys);
  function setSelection(ids) {
    needsRender=true;renderer.shadowMap.needsUpdate=true;
    for (const group of groups) group.visible=group.userData.existing_feature || !group.userData.element_id || ids.has(group.userData.element_id);
    for (const fill of fills) fill.visible=!ids.has(fill.userData.fill_for);
    obstacles=groups.filter(g=>g.visible).flatMap(g=>[...(g.userData.collider?[g.userData.collider]:[]),...(g.userData.rail_colliders||[])]);
    if (mode!=='orbit' && !canStand(camera.position.x,camera.position.z,width,length,obstacles)) {
      const point=spawnPoint(width,length,obstacles);
      if (point) camera.position.set(point.x,standingHeight(point.x,point.z),point.z);
      else resetOrbit('No clear walking space after this change. Using orbit mode.');
    }
    // Small diagnostic counters also make regressions observable without exposing
    // the renderer or camera as mutable globals.
    container.dataset.visibleElements=JSON.stringify([...new Set(groups.filter(g=>g.visible && g.userData.element_id).map(g=>g.userData.element_id))]);
  }
  setSelection(new Set(groups.map(g=>g.userData.element_id)));
  if (coarse || !renderer.domElement.requestPointerLock) resetOrbit(); else prepareWalk();
  const observer=new ResizeObserver(resize); observer.observe(container);
  let previous=performance.now();
  const gl=renderer.getContext();
  let gpuFence=null;
  const forward=new THREE.Vector3(), right=new THREE.Vector3();
  renderer.setAnimationLoop(now => {
    if (disposed) return;
    const dt=Math.min(.05,Math.max(0,(now-previous)/1000)); previous=now;
    try {
      if (mode==='walk' && pointer.isLocked) {
        camera.getWorldDirection(forward); forward.y=0; forward.normalize();
        right.crossVectors(forward,camera.up).normalize();
        const f=Number(keys.has('KeyW'))-Number(keys.has('KeyS'));
        const r=Number(keys.has('KeyD'))-Number(keys.has('KeyA'));
        const speed=1.45*dt/Math.max(1,Math.hypot(f,r));
        const next=moveWithCollision(camera.position,(forward.x*f+right.x*r)*speed,(forward.z*f+right.z*r)*speed,width,length,obstacles);
        if (!canStand(next.x,next.z,width,length,obstacles)) throw new Error('Invalid walk position');
        camera.position.set(next.x,standingHeight(next.x,next.z),next.z);
        if(f||r)needsRender=true;
      } else if (mode==='orbit') orbit.update();
    } catch { resetOrbit('Walk controls reset. Orbit mode is available.'); }
    container.dataset.camera=JSON.stringify(camera.position.toArray());
    if(needsRender){
      // Do not queue more expensive frames than the GPU can finish. Camera and
      // input still update every animation frame; render the newest pose next.
      if(gpuFence){
        const completion=gl.clientWaitSync(gpuFence,0,0);
        if(completion===gl.TIMEOUT_EXPIRED)return;
        gl.deleteSync(gpuFence);gpuFence=null;
      }
      const renderStarted=performance.now();
      try { if(effects)effects.render();else renderer.render(scene,camera); }
      catch { effects?.dispose();effects=null;container.dataset.effects='basic';renderer.render(scene,camera); }
      container.dataset.renderMs=String(Math.round(performance.now()-renderStarted));
      container.dataset.drawCalls=String(renderer.info.render.calls);
      gpuFence=gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE,0);gl.flush();
      needsRender=false;
    }
  });
  renderer.domElement.addEventListener('webglcontextlost',event => {
    event.preventDefault(); renderer.setAnimationLoop(null); if (pointer.isLocked) pointer.unlock(); onFailure();
  },{once:true});
  window.addEventListener('pagehide',() => {
    disposed=true; clearTimeout(lockTimer); observer.disconnect(); orbit.dispose(); pointer.dispose();
    if(gpuFence)gl.deleteSync(gpuFence);
    renderer.setAnimationLoop(null); renderer.dispose(); grass.dispose();
    effects?.dispose();materialQuality.dispose();disposeEnvironment();
    window.removeEventListener('keydown',keyDown); window.removeEventListener('keyup',keyUp); window.removeEventListener('blur',clearKeys);
    document.removeEventListener('visibilitychange',clearKeys); document.removeEventListener('pointerlockerror',lockError);
    scene.traverse(o=>{ o.geometry?.dispose(); if (o.material) for (const m of [o.material].flat()) m.dispose(); });
  },{once:true});
  container.dataset.ready='true';
  container.dataset.instancedBatches=String(groups.reduce((n,g)=>{g.traverse(o=>{if(o.isInstancedMesh)n++;});return n;},0));
  return { reset:() => resetOrbit(), setSelection };
}
