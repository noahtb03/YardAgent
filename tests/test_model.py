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


class ModelTests(unittest.TestCase):
    def test_quantities_static_bounds_and_untrusted_names(self):
        data = payload()
        chair = data['layout']['elements'][0]
        chair.update(type='Solar stake light', category='lighting', quantity=4)
        chair['sourced_product']['name'] = "'); __import__('os').system('bad'); #"
        bounds = [dict(name='Wooden shed at far right', position_x_ft=20, position_y_ft=22, width_ft=8, length_ft=6)]
        scene, notes = scene_data(data['analysis'], data['layout'], bounds)
        self.assertEqual(len(scene['objects']), 5)
        shed, *lights = scene['objects']
        self.assertTrue(shed['static'])
        self.assertEqual((shed['x'], shed['y'], shed['width'], shed['length']), (20,22,8,6))
        self.assertEqual(len(lights), 4)
        self.assertTrue(all(o['shape']=='cylinder' and o['width'] == .22 for o in lights))
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
        with TemporaryDirectory() as directory, patch('modeling.MODEL_ROOT', Path(directory)), \
                patch('main.MODEL_ROOT', Path(directory)), TestClient(app) as client:
            response = client.post('/model', json=data)
            self.assertFalse(response.json()['fallback'], response.text)
            url = response.json()['model_url']
            glb = client.get(url).content
            self.assertEqual(glb[:4], b'glTF')
            length = struct.unpack_from('<I', glb, 12)[0]
            document = json.loads(glb[20:20+length])
            nodes = document['nodes']
            chairs = [n for n in nodes if n.get('extras', {}).get('element_id')=='chair']
            self.assertEqual(len(chairs), 2)
            self.assertEqual(len([n for n in nodes if n.get('extras', {}).get('existing_feature')]), 1)
            ground = next(n for n in nodes if n['name']=='Yard ground')
            self.assertAlmostEqual(ground['scale'][0], 30*.3048, places=4)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(args=['--enable-unsafe-swiftshader'])
                try:
                    page = browser.new_page(viewport=dict(width=1200, height=900))
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    serve_ui(page)
                    page.route('**/model', lambda route: route.fulfill(json=response.json()))
                    page.route('**/models/**', lambda route: route.fulfill(body=glb, content_type='model/gltf-binary'))
                    page.goto('http://yard.test/')
                    page.evaluate('''async value => {
                      const { yardState } = await import('/static/storage.js');
                      await yardState({...value, budget: 500});
                    }''', data)
                    page.goto('http://yard.test/view')
                    page.wait_for_selector('#scene[data-ready="true"]', timeout=30000)
                    self.assertIn('$198.00', page.locator('#materials-total').inner_text())
                    canvas = page.locator('canvas')
                    before = canvas.screenshot()
                    bounds = canvas.bounding_box()
                    x, y = bounds['x']+bounds['width']/2, bounds['y']+bounds['height']/2
                    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x+120,y+50,steps=12); page.mouse.up()
                    page.wait_for_timeout(250)
                    self.assertNotEqual(canvas.screenshot(), before)
                    page.mouse.wheel(0, 250)
                    page.mouse.down(button='right'); page.mouse.move(x+160,y+70,steps=8); page.mouse.up(button='right')
                    page.get_by_role('button', name='Reset view').click()
                    page.set_viewport_size(dict(width=390, height=844))
                    self.assertLessEqual(canvas.bounding_box()['width'], 390)
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
