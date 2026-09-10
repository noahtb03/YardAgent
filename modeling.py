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

MODEL_ROOT = Path(__file__).parent / '.yard-models'
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


def scene_data(analysis, layout, existing_bounds):
    width = analysis['width_ft']['min'] if analysis.get('width_ft') else 20
    length = analysis['length_ft']['min'] if analysis.get('length_ft') else 20
    notes = ['3D primitives show approximate footprints, not detailed product models. Heights are illustrative; terrain is shown level.']
    objects = []

    def add(name, kind, x, y, w, l, static=False, element_id='', index=0):
        kind = kind.lower()
        cylinder = any(word in kind for word in ('tree', 'plant', 'planter', 'shrub', 'light', 'fire pit'))
        height = 8 if 'tree' in kind else 2 if cylinder else 3
        color = [0.30, 0.48, 0.22, 1] if cylinder else [0.55, 0.35, 0.19, 1]
        if 'light' in kind:
            height, color = 1.5, [0.92, 0.77, 0.35, 1]
            w, l = min(w, .22), min(l, .22)
        if any(word in kind for word in ('patio', 'deck', 'path', 'paver')):
            height, color = .18, [.65, .62, .56, 1]
        if 'pool' in kind:
            height, color = .3, [.10, .57, .78, 1]
        if 'shed' in kind:
            height = 7
        if 'fence' in kind:
            height = 6
        objects.append(dict(name=name, shape='cylinder' if cylinder else 'box', x=x, y=y,
                            width=w, length=l, height=height, color=color, static=static,
                            element_id=element_id, instance=index))

    bound_names = {b['name'].casefold() for b in existing_bounds}
    for b in existing_bounds:
        add(b['name'], b['name'], b['position_x_ft'], b['position_y_ft'], b['width_ft'], b['length_ft'], True)
    for description in analysis['existing_features']:
        text = description.lower()
        if description.casefold() in bound_names or any(name in text for name in bound_names):
            continue
        if text.strip() in ('grass', 'lawn', 'grass lawn'):
            continue  # Already represented by the ground.
        notes.append(f"Existing feature '{description}': position and size approximated from its description; supply existing_feature_bounds for explicit placement.")
        if 'fence' in text:
            sides = [s for s in ('left', 'right', 'far') if s in text]
            if not sides:
                sides = ['left', 'right', 'far']
            for side in sides:
                add(description + ' (' + side + ')', 'fence', width-.15 if side=='right' else 0,
                    length-.15 if side=='far' else 0, width if side=='far' else .15,
                    .15 if side=='far' else length, True)
            continue
        w, l = min(width, 8), min(length, 6)
        if 'bed' in text:
            w, l = min(width, 4), min(length, 8)
        x = width-w if 'right' in text else 0 if 'left' in text else (width-w)/2
        y = 0 if any(s in text for s in ('near', 'foreground', 'house')) else length-l
        add(description, text, x, y, w, l, True)
    for item in layout['elements']:
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
    return dict(width=width, length=length, objects=objects), notes


BLENDER_SCRIPT = '''import bpy, json
from pathlib import Path
root = Path(__file__).resolve().parent
data = json.loads((root / 'scene.json').read_text(encoding='utf-8'))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
FT = 0.3048
def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = color
    return mat
bpy.ops.mesh.primitive_plane_add(size=1, location=(data['width']*FT/2, data['length']*FT/2, 0))
ground = bpy.context.object
ground.name = 'Yard ground'
ground.dimensions = (data['width']*FT, data['length']*FT, 0)
ground.data.materials.append(material('Grass', (0.25, .39, .18, 1)))
for item in data['objects']:
    location = ((item['x']+item['width']/2)*FT, (item['y']+item['length']/2)*FT, item['height']*FT/2)
    if item['shape'] == 'cylinder':
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=.5, depth=1, location=location)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = item['name']
    obj.dimensions = (item['width']*FT, item['length']*FT, item['height']*FT)
    obj['existing_feature'] = item['static']
    obj['element_id'] = item['element_id']
    obj['instance'] = item['instance']
    obj.data.materials.append(material(item['name'], item['color']))
bpy.ops.export_scene.gltf(filepath=str(root / 'yard.glb'), export_format='GLB', export_extras=True)
'''


def generate_model(analysis, layout, existing_bounds):
    scene, notes = scene_data(analysis, layout, existing_bounds)
    job_id = uuid.uuid4().hex
    directory = MODEL_ROOT / job_id
    try:
        directory.mkdir(parents=True)
        (directory / 'scene.json').write_text(json.dumps(scene), encoding='utf-8')
        script = directory / 'script.py'
        script.write_text(BLENDER_SCRIPT, encoding='utf-8')
        with BLENDER_LOCK, (directory / 'blender.log').open('w', encoding='utf-8') as log:
            subprocess.run([blender_executable(), '--background', '--factory-startup', '--python-exit-code', '1',
                            '--python', str(script.resolve())], stdout=log, stderr=subprocess.STDOUT,
                           timeout=120, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        model = directory / 'yard.glb'
        with model.open('rb') as result:
            if result.read(4) != b'glTF':
                raise ValueError('Invalid Blender export')
        return dict(model_url=f'/models/{job_id}/yard.glb', fallback=False, warnings=notes)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        logging.getLogger(__name__).warning('Blender job %s failed: %s. Diagnostics: %s', job_id, error, directory)
        return dict(model_url=None, fallback=True, warnings=notes + ['3D generation unavailable. Using the photo render instead.'])
