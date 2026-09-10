import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { SSAOPass } from 'three/addons/postprocessing/SSAOPass.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

function texture(kind, color = false) {
  const canvas=document.createElement('canvas');canvas.width=canvas.height=512;
  const ctx=canvas.getContext('2d');
  let seed=831;
  const rand=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296;};
  const pixels=ctx.createImageData(512,512);
  for(let y=0;y<512;y++)for(let x=0;x<512;x++){
    const grain=Math.sin(x*.47+Math.sin(y*.009)*.6+Math.sin(y*.031)*.15);
    const fine=Math.sin(x*1.9+Math.sin(y*.02));
    const base=kind==='wood'? .70+grain*.035+fine*.015+(rand()-.5)*.06
      :kind==='bark'? .47+grain*.12+fine*.055+(rand()-.5)*.12
      :kind==='water'? .5+.16*Math.sin(x*.17+Math.sin(y*.13))+.16*Math.cos(y*.19+Math.sin(x*.12))
      : .66+(rand()-.5)*.26;
    const i=(y*512+x)*4;
    const tint=color?(kind==='wood'?[1,.91,.75]:kind==='bark'?[.81,.65,.48]:[1,1,1]):[1,1,1];
    for(let c=0;c<3;c++) pixels.data[i+c]=Math.max(0,Math.min(255,base*255*tint[c]));
    pixels.data[i+3]=255;
  }
  ctx.putImageData(pixels,0,0);
  const result=new THREE.CanvasTexture(canvas);
  result.wrapS=result.wrapT=THREE.RepeatWrapping;
  if(color)result.colorSpace=THREE.SRGBColorSpace;
  return result;
}

export function upgradeMaterials(root, renderer) {
  const maps={wood:texture('wood',true),woodBump:texture('wood'),bark:texture('bark',true),barkBump:texture('bark'),stone:texture('stone'),water:texture('water')};
  for(const map of Object.values(maps))map.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());
  const seen=new Set(),waters=[];
  root.traverse(object=>{
    if(!object.isMesh||Array.isArray(object.material))return;
    let mat=object.material;
    if(mat.name==='Water'){
      if(!mat.isMeshPhysicalMaterial){
        mat=new THREE.MeshPhysicalMaterial({name:'Water',color:0x75c6cf});object.material=mat;
      }
      Object.assign(mat,{transmission:.85,ior:1.333,thickness:1.1,roughness:.095,metalness:0,transparent:false,opacity:1,
        attenuationDistance:2.8,attenuationColor:new THREE.Color('#58b6be'),clearcoat:1,clearcoatRoughness:.08,
        bumpMap:maps.water,bumpScale:.027,envMapIntensity:1.2,depthWrite:true});
      waters.push(mat);return;
    }
    if(seen.has(mat))return;seen.add(mat);
    if(mat.name==='Cedar')Object.assign(mat,{map:maps.wood,bumpMap:maps.woodBump,bumpScale:.008,roughness:.84,metalness:0,color:new THREE.Color('#aaa08a')});
    if(mat.name==='Bark')Object.assign(mat,{map:maps.bark,bumpMap:maps.barkBump,bumpScale:.025,roughness:.98,metalness:0,color:new THREE.Color('#958374')});
    if(['Paver','Concrete','Coping','Terracotta','Soil'].includes(mat.name))Object.assign(mat,{bumpMap:maps.stone,bumpScale:mat.name==='Soil'?.03:.006,roughness:mat.name==='Coping'?.78:.95,metalness:0});
    if(mat.name==='Metal')Object.assign(mat,{roughness:.27,metalness:.25,envMapIntensity:.8}); // painted, not bare steel
    if(mat.name==='Steel')Object.assign(mat,{roughness:.24,metalness:.95,envMapIntensity:1.1});
    if(mat.name.startsWith('Leaves'))Object.assign(mat,{roughness:.89,metalness:0,side:THREE.DoubleSide});
    if(mat.name==='Cushion')Object.assign(mat,{bumpMap:maps.stone,bumpScale:.0015,roughness:.96});
  });
  return {dispose:()=>Object.values(maps).forEach(map=>map.dispose()),waters};
}

export function addEnvironment(scene, center, span, renderer) {
  const radius=Math.max(span,12)*30;
  const sky=new THREE.Mesh(new THREE.SphereGeometry(radius,32,20),new THREE.ShaderMaterial({
    side:THREE.BackSide,depthWrite:false,
    vertexShader:'varying vec3 direction;void main(){direction=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
    fragmentShader:`varying vec3 direction;
      float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
      float fbm(vec2 p){return .55*noise(p)+.27*noise(p*2.07)+.13*noise(p*4.11)+.05*noise(p*8.2);}
      void main(){vec3 d=normalize(direction);float h=max(d.y,0.);
        vec3 color=mix(vec3(.77,.80,.76),vec3(.20,.43,.68),pow(h,.45));
        vec2 p=d.xz/max(.12,d.y)*2.4;float cloud=smoothstep(.51,.72,fbm(p));
        cloud*=smoothstep(.01,.20,d.y);color=mix(color,vec3(.98,.94,.86),cloud*.86);
        float sun=pow(max(dot(d,normalize(vec3(-1.,.52,.6))),0.),180.);
        color+=vec3(1.,.69,.28)*sun*.6;gl_FragColor=vec4(color,1.);}`,
  }));
  sky.position.copy(center);scene.add(sky);
  scene.fog=new THREE.FogExp2('#bfcac3',1/(Math.max(span,12)*9));
  // Capture the sky once for PBR reflections/refraction; no six-face capture per frame.
  const environmentScene=new THREE.Scene();environmentScene.add(sky.clone());
  const pmrem=new THREE.PMREMGenerator(renderer);
  const env=pmrem.fromScene(environmentScene,.06,.1,radius*2);
  scene.environment=env.texture;scene.environmentIntensity=.55;
  pmrem.dispose();
  return ()=>env.dispose();
}

export function postProcessing(renderer, scene, camera, width, height) {
  const composer=new EffectComposer(renderer);
  composer.setPixelRatio(Math.min(renderer.getPixelRatio(),1));
  const ao=new SSAOPass(scene,camera,Math.ceil(width/2),Math.ceil(height/2),8);
  // Refractive meshes must not trigger the renderer's transmission prepass
  // while SSAO is rendering its override normal/depth material.
  const renderNormals=ao._renderOverride.bind(ao);
  ao._renderOverride=(...args)=>{
    const hidden=[];
    scene.traverse(o=>{if(o.visible&&o.isMesh&&(o.material.transmission>0||o.material.isShaderMaterial)){hidden.push(o);o.visible=false;}});
    try{return renderNormals(...args);}finally{for(const o of hidden)o.visible=true;}
  };
  const setAOSize=ao.setSize.bind(ao);
  ao.setSize=(w,h)=>setAOSize(Math.ceil(w/2),Math.ceil(h/2));
  ao.kernelRadius=.35;ao.minDistance=.002;ao.maxDistance=.035;
  const bloom=new UnrealBloomPass(new THREE.Vector2(width,height),.16,.35,1.7);
  // A single non-finite HDR sample can otherwise spread across every blur mip
  // on some drivers (especially refractive edges). Keep the bloom input finite.
  bloom.materialHighPassFilter.fragmentShader=bloom.materialHighPassFilter.fragmentShader.replace(
    'vec4 texel = texture2D( tDiffuse, vUv );',
    'vec4 texel = texture2D( tDiffuse, vUv ); if(any(isnan(texel)) || any(isinf(texel))) texel=vec4(0.0); texel.rgb=clamp(texel.rgb,vec3(0.0),vec3(32.0));');
  const beauty=new RenderPass(scene,camera);
  composer.addPass(beauty);composer.addPass(ao);composer.addPass(bloom);composer.addPass(new OutputPass());
  return {
    render:()=>composer.render(),
    resize:(w,h)=>composer.setSize(w,h),
    dispose:()=>{ao.dispose();bloom.dispose();composer.passes.at(-1).dispose();composer.dispose();},
  };
}
