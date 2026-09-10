import json
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from browser_helpers import serve_ui
from main import app
from modeling import blender_executable, scene_data
from test_render import payload
from sourcing import estimate_feature
from PIL import Image
from io import BytesIO


class ModelTests(unittest.TestCase):
    def test_quantities_static_bounds_and_untrusted_names(self):
        data = payload()
        chair = data['layout']['elements'][0]
        chair.update(type='Solar stake light', category='lighting', quantity=4)
        chair['sourced_product']['name'] = "'); __import__('os').system('bad'); #"
        bounds = [dict(name='Wooden shed at far right', position_x_ft=20, position_y_ft=22, width_ft=8, length_ft=6)]
        scene, notes = scene_data(data['analysis'], data['layout'], bounds)
        self.assertEqual(len(scene['objects']), 9)
        shed, *lights = scene['objects'][:5]
        self.assertTrue(shed['static'])
        self.assertEqual((shed['x'], shed['y'], shed['width'], shed['length']), (20,22,8,6))
        self.assertEqual(len(lights), 4)
        self.assertTrue(all(o['shape']=='cylinder' and o['width'] == .6 for o in lights))
        self.assertTrue(all(not o['static'] and o['element_id']=='chair' for o in lights))
        self.assertEqual([o['instance'] for o in lights], [1,2,3,4])

    def test_failure_returns_fallback_and_private_files_are_not_served(self):
        data = payload(); data.pop('original_photo')
        with TemporaryDirectory() as directory, patch('modeling.MODEL_ROOT', Path(directory)), TestClient(app) as client:
            for error in (FileNotFoundError(), subprocess.TimeoutExpired('blender', 120), subprocess.CalledProcessError(1, 'blender')):
                with patch('modeling.subprocess.run', side_effect=error):
                    response = client.post('/model', json=data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['fallback'])
                self.assertIsNone(response.json()['model_url'])
            self.assertEqual(client.get('/models/not-a-job/yard.glb').status_code, 404)
            self.assertEqual(client.get('/models/' + 'a'*32 + '/script.py').status_code, 404)
            self.assertEqual(client.get('/view').status_code, 200)

    def test_real_blender_export_and_threejs_orbit_view(self):
        executable = blender_executable()
        if not Path(executable).is_file():
            import shutil
            if not shutil.which(executable):
                self.skipTest('Blender not installed')
        data = payload(); data.pop('original_photo')
        data['analysis']['existing_features'].append('Fence along left, right and far boundaries')
        for kind, category, x,y,w,l,quantity in [
            ('Pool','hardscape',10,12,10,10,1), ('Patio','hardscape',0,14,8,8,1),
            ('Oak tree','plant',2,23,4,4,1), ('Tapered planter','plant',2,10,2,3,1),
            ('Solar path light','lighting',8,2,1,8,4)]:
            item = {**data['layout']['elements'][0], 'id':kind, 'type':kind, 'category':category,
                    'position_x_ft':x,'position_y_ft':y,'width_ft':w,'length_ft':l,'quantity':quantity}
            if category=='hardscape':
                item.update(sourced_product=None,estimated_feature=estimate_feature(item,kind.lower()),sourcing_status='estimated',sourced_total_usd=None)
            else:
                item['sourced_product']={**item['sourced_product'],'name':kind}
            data['layout']['elements'].append(item)
        with TemporaryDirectory() as directory, patch('modeling.MODEL_ROOT', Path(directory)), \
                patch('main.MODEL_ROOT', Path(directory)), TestClient(app) as client:
            response = client.post('/model', json=data)
            self.assertFalse(response.json()['fallback'], response.text)
            url = response.json()['model_url']
            glb = client.get(url).content
            artifacts=Path(__file__).parents[1]/'.yard-models'
            artifacts.mkdir(exist_ok=True)
            (artifacts/'quality-fixture.glb').write_bytes(glb)
            (artifacts/'quality-fixture.json').write_text(json.dumps({'request':data,'model':response.json()}))
            self.assertEqual(glb[:4], b'glTF')
            length = struct.unpack_from('<I', glb, 12)[0]
            document = json.loads(glb[20:20+length])
            nodes = document['nodes']
            chairs = [n for n in nodes if n.get('extras', {}).get('element_id')=='chair']
            self.assertEqual(len(chairs), 2)
            self.assertEqual(len([n for n in nodes if n.get('extras', {}).get('existing_feature')]), 5)
            for name in ('Fence picket','Fence post','Fence rail','Tapered tree trunk','Irregular canopy cluster','Tapered planter',
                         'Planter soil','Patio paver','Pool bottom','Pool water','Pool coping','Light post','Lamp glow'):
                self.assertTrue(any(n['name'].startswith(name) for n in nodes), name)
            water = next(m for m in document['materials'] if m['name']=='Water')
            self.assertGreater(water['extensions']['KHR_materials_transmission']['transmissionFactor'],.8)
            envelopes=[n['extras']['geometry_bounds_ft'] for n in nodes if 'geometry_bounds_ft' in n.get('extras',{})]
            for i,a in enumerate(envelopes):
                for b in envelopes[:i]:
                    self.assertFalse(a[0]<b[2]-.001 and b[0]<a[2]-.001 and a[1]<b[3]-.001 and b[1]<a[3]-.001,(a,b))
            ground = next(n for n in nodes if n['name']=='Yard ground')
            self.assertAlmostEqual(ground['extras']['yard_width_m'], 30*.3048, places=4)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(args=['--enable-unsafe-swiftshader'])
                try:
                    page = browser.new_page(viewport=dict(width=1200, height=900))
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('console',lambda message: errors.append(message.text) if message.type=='error' and ('WebGL' in message.text or 'Shader' in message.text) else None)
                    serve_ui(page)
                    page.route('**/model', lambda route: route.fulfill(json=response.json()))
                    page.route('**/models/**', lambda route: route.fulfill(body=glb, content_type='model/gltf-binary'))
                    page.goto('http://yard.test/')
                    page.evaluate('''async value => {
                      const { yardState } = await import('/static/storage.js');
                      const originalPhoto = new File([await (await fetch(value.photo)).blob()], 'yard.png', {type:'image/png'});
                      await yardState({...value, budget: 500, previewVersion:1, originalPhoto,
                        renderImage:value.photo, renderLayout:value.layout,
                        reconciliation:{layout:value.layout,depicted_instances:[],existing_feature_bounds:[],
                          corrections:['Fixture placement confirmed.'],confidence:'medium',limitations:'Fixture'}});
                    }''', {**data,'photo':payload()['original_photo'],'model':response.json()})
                    page.goto('http://yard.test/view')
                    page.wait_for_selector('#scene[data-ready="true"]', timeout=30000)
                    self.assertEqual(page.locator('#scene').get_attribute('data-effects'),'ao+bloom')
                    page.get_by_role('button', name='Reset view').click(no_wait_after=True)
                    self.assertIn('$792.00', page.locator('#materials-total').inner_text())
                    self.assertGreater(int(page.locator('#scene').get_attribute('data-instanced-batches')),5)
                    page.locator('input[data-element-id="chair"]').uncheck()
                    self.assertNotIn('chair',json.loads(page.locator('#scene').get_attribute('data-visible-elements')))
                    self.assertIn('$594.00',page.locator('#materials-total').inner_text())
                    page.locator('input[data-element-id="chair"]').check()
                    self.assertIn('chair',json.loads(page.locator('#scene').get_attribute('data-visible-elements')))
                    page.locator('input[data-element-id="Pool"]').uncheck()
                    self.assertIn('$512.00',page.locator('#features-total').inner_text())
                    self.assertNotIn('Pool',json.loads(page.locator('#scene').get_attribute('data-visible-elements')))
                    page.locator('input[data-element-id="Pool"]').check()
                    canvas = page.locator('canvas')
                    before = canvas.screenshot()
                    with Image.open(BytesIO(before)) as screenshot:
                        black=sum(1 for p in screenshot.convert('RGB').getdata() if p==(0,0,0))
                        self.assertLess(black/(screenshot.width*screenshot.height),.15,'Postprocessing must not black out the scene')
                    (Path(__file__).parents[1]/'.yard-models'/'quality-before.png').write_bytes(before)
                    bounds = canvas.bounding_box()
                    x, y = bounds['x']+bounds['width']/2, bounds['y']+bounds['height']/2
                    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x+120,y+50,steps=12); page.mouse.up()
                    page.wait_for_timeout(250)
                    after=canvas.screenshot()
                    (Path(__file__).parents[1]/'.yard-models'/'quality-after.png').write_bytes(after)
                    self.assertFalse(after==before, f'Rotation did not change the image. Errors: {errors}')
                    page.mouse.wheel(0, 250)
                    page.mouse.down(button='right'); page.mouse.move(x+160,y+70,steps=8); page.mouse.up(button='right')
                    page.get_by_role('button', name='Reset view').click()
                    page.get_by_role('button', name='Walk mode', exact=True).click()
                    page.wait_for_function("document.querySelector('#scene').dataset.mode === 'walk'")
                    position=json.loads(page.locator('#scene').get_attribute('data-camera'))
                    self.assertAlmostEqual(position[1],1.6764,delta=.07)
                    page.keyboard.down('w'); page.wait_for_timeout(400); page.keyboard.up('w')
                    moved=json.loads(page.locator('#scene').get_attribute('data-camera'))
                    self.assertLess(moved[2],position[2])
                    page.keyboard.press('Escape')
                    page.wait_for_function("document.querySelector('#scene').dataset.mode === 'orbit'")
                    page.evaluate("document.dispatchEvent(new Event('pointerlockerror'))")
                    self.assertEqual(page.locator('#scene').get_attribute('data-mode'),'orbit')
                    self.assertIn('Using orbit',page.locator('#walk-status').inner_text())
                    page.evaluate("() => { document.querySelector('canvas').requestPointerLock = () => Promise.reject(new Error('Blocked by browser')); }")
                    page.get_by_role('button',name='Walk mode',exact=True).click()
                    page.wait_for_function("document.querySelector('#walk-status').textContent.includes('unavailable')")
                    self.assertEqual(page.locator('#scene').get_attribute('data-mode'),'orbit')
                    # Capture the detailed scene for visual review.
                    preview=Path(__file__).parents[1]/'.yard-models'/'preview.png'
                    preview.parent.mkdir(exist_ok=True)
                    page.screenshot(path=str(preview))
                    page.set_viewport_size(dict(width=390, height=844))
                    self.assertLessEqual(canvas.bounding_box()['width'], 390)
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
