"""Deterministic Blender scenes: layout data never becomes executable Python."""
import json
import logging
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import uuid
from copy import deepcopy
from placement import resolve_placement

MODEL_ROOT = Path(__file__).parent / '.yard-models'
SCENE_VERSION = 4
BLENDER_LOCK = threading.Lock()


def blender_executable():
    configured = os.environ.get('BLENDER_PATH')
    if configured:
        return configured
    found = shutil.which('blender')
    if found:
        return found
    candidates = sorted(Path(os.environ.get('ProgramFiles', 'C:/Program Files')).glob('Blender Foundation/Blender */blender.exe'))
    return str(candidates[-1]) if candidates else 'blender'


def scene_data(analysis, layout, existing_bounds, depicted_instances=None):
    width = analysis['width_ft']['min'] if analysis.get('width_ft') else 20
    length = analysis['length_ft']['min'] if analysis.get('length_ft') else 20
    notes = ['Detailed 3D assets approximate the selected products and footprints. Heights, materials and gentle ground relief are illustrative.']
    objects = []

    def add(name, kind, x, y, w, l, static=False, element_id='', index=0):
        kind = kind.lower()
        cylinder = any(word in kind for word in ('tree', 'plant', 'planter', 'shrub', 'light', 'fire pit'))
        height = 8 if 'tree' in kind else 2 if cylinder else 3
        color = [0.30, 0.48, 0.22, 1] if cylinder else [0.55, 0.35, 0.19, 1]
        if 'light' in kind:
            height, color = 1.5, [0.92, 0.77, 0.35, 1]
            w, l = min(w, .22), min(l, .22)
        if 'light' not in kind and any(word in kind for word in ('patio', 'deck', 'path', 'paver')):
            height, color = .18, [.65, .62, .56, 1]
        if 'pool' in kind:
            height, color = .3, [.10, .57, .78, 1]
        if 'shed' in kind:
            height = 7
        if 'fence' in kind:
            height = 6
        objects.append(dict(name=name, kind=kind, shape='cylinder' if cylinder else 'box', x=x, y=y,
                            width=w, length=l, height=height, color=color, static=static,
                            element_id=element_id, instance=index))

    removed = {d['feature'].casefold() for d in layout.get('existing_feature_decisions',[]) if d['action']=='remove'}
    existing_bounds = [b for b in existing_bounds if b['name'].casefold() not in removed]
    bound_names = {b['name'].casefold() for b in existing_bounds}
    for b in existing_bounds:
        add(b['name'], b['name'], b['position_x_ft'], b['position_y_ft'], b['width_ft'], b['length_ft'], True)
    for description in analysis['existing_features']:
        if description.casefold() in removed or depicted_instances is not None:
            continue  # Reconciliation supplies explicit observed geometry only.
        text = description.lower()
        if description.casefold() in bound_names or any(name in text for name in bound_names):
            continue
        if text.strip() in ('grass', 'lawn', 'grass lawn'):
            continue  # Already represented by the ground.
        notes.append(f"Existing feature '{description}': position and size approximated from its description; supply existing_feature_bounds for explicit placement.")
        if 'fence' in text:
            # A complete boundary enclosure is generated after placement, just
            # outside the usable ground footprint, rather than through objects.
            continue
        w, l = min(width, 8), min(length, 6)
        if 'bed' in text:
            w, l = min(width, 4), min(length, 8)
        x = width-w if 'right' in text else 0 if 'left' in text else (width-w)/2
        y = 0 if any(s in text for s in ('near', 'foreground', 'house')) else length-l
        add(description, text, x, y, w, l, True)
    for item in layout['elements']:
        if depicted_instances is not None:
            product = item.get('sourced_product')
            for i,b in enumerate(p for p in depicted_instances if p['element_id']==item['id']):
                add(product['name'] if product else item['type'],item['type']+' '+item['category'],
                    b['position_x_ft'],b['position_y_ft'],b['width_ft'],b['length_ft'],element_id=item['id'],index=i+1)
                objects[-1]['width'],objects[-1]['length'] = b['width_ft'],b['length_ft']
            continue
        if not item.get('sourced_product') and not item.get('estimated_feature'):
            notes.append(f"{item['type']}: unpriced item omitted from scene.")
            continue
        count = item['quantity']
        cols = min(count, max(1, math.ceil(math.sqrt(count * item['width_ft']/item['length_ft']))))
        rows = math.ceil(count/cols)
        w, l = item['width_ft']/cols, item['length_ft']/rows
        product = item.get('sourced_product')
        name = product['name'] if product else item['type']
        for i in range(count):
            add(name, item['type'] + ' ' + item['category'], item['position_x_ft']+(i%cols)*w,
                item['position_y_ft']+(i//cols)*l, w, l, element_id=item['id'], index=i+1)
    objects,moves,omitted,placement_notes = resolve_placement(objects,width,length,
        preserve_dimensions=depicted_instances is not None)
    if depicted_instances is not None and moves:
        notes.append('Image-derived placement adjusted to retain every item; review differences from the before/after image.')
    notes.extend(placement_notes)
    notes.append('Heights and composite details are approximate. Neighboring landscape is contextual geometry, not a purchase.' if depicted_instances is not None else
        'Object proportions use typical full-size dimensions where retailer measurements are unavailable. Boundary fencing and neighboring landscape are contextual geometry, not purchases.')
    for side,x,y,w,l in [('left',-.5,-.4,.4,length+.8),('right',width+.1,-.4,.4,length+.8),
                          ('near',0,-.5,width,.4),('far',0,length+.1,width,.4)]:
        if depicted_instances is not None or any('fence' in f for f in removed):
            continue
        add('Boundary fence '+side,'fence',x,y,w,l,True)
        objects[-1]['asset'] = 'fence'
    return dict(width=width, length=length, objects=objects, placement_changes=moves,
                omitted_element_ids=omitted), notes


def generate_model(analysis, layout, existing_bounds, depicted_instances=None):
    job_id = uuid.uuid4().hex
    directory = MODEL_ROOT / job_id
    notes = []
    try:
        scene, notes = scene_data(analysis, layout, existing_bounds, depicted_instances)
        directory.mkdir(parents=True)
        (directory / 'scene.json').write_text(json.dumps(scene), encoding='utf-8')
        (directory / 'placement.json').write_text(json.dumps({'moves':scene['placement_changes'],
            'omitted_element_ids':scene['omitted_element_ids']},indent=2),encoding='utf-8')
        script = directory / 'script.py'
        script.write_text(Path(__file__).with_name('blender_scene.py').read_text(encoding='utf-8'), encoding='utf-8')
        with BLENDER_LOCK, (directory / 'blender.log').open('w', encoding='utf-8') as log:
            subprocess.run([blender_executable(), '--background', '--factory-startup', '--python-exit-code', '1',
                            '--python', str(script.resolve())], stdout=log, stderr=subprocess.STDOUT,
                           timeout=120, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        model = directory / 'yard.glb'
        with model.open('rb') as result:
            if result.read(4) != b'glTF':
                raise ValueError('Invalid Blender export')
        adjusted = deepcopy(layout)
        for item in adjusted['elements']:
            instances = [o for o in scene['objects'] if o['element_id']==item['id'] and not o['static']]
            if instances:
                x,y = min(o['x'] for o in instances),min(o['y'] for o in instances)
                item.update(position_x_ft=x,position_y_ft=y,width_ft=max(o['x']+o['width'] for o in instances)-x,
                            length_ft=max(o['y']+o['length'] for o in instances)-y)
        return dict(model_url=f'/models/{job_id}/yard.glb', fallback=False, warnings=notes, scene_version=SCENE_VERSION,
                    adjusted_layout=adjusted, placement_changes=scene['placement_changes'], omitted_element_ids=scene['omitted_element_ids'])
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        logging.getLogger(__name__).warning('Blender job %s failed: %s. Diagnostics: %s', job_id, error, directory)
        return dict(model_url=None, fallback=True, warnings=notes + [str(error) if isinstance(error,ValueError) else '3D generation unavailable. Using the photo render instead.'])
