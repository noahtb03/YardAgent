import base64
import unittest
from playwright.sync_api import sync_playwright
from browser_helpers import serve_ui
from test_render import payload, png


class PipelineTests(unittest.TestCase):
    def test_reconciliation_failures_always_proceed_to_model_with_original_layout(self):
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            try:
                for failure in ('http','malformed','network','skipped'):
                    with self.subTest(failure=failure):
                        page=browser.new_page(); serve_ui(page); calls=[]; requests={}; errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        data=payload()
                        def render(route):
                            calls.append('render'); requests['render']=route.request.post_data_json
                            route.fulfill(json={'image_url':data['original_photo']})
                        def reconcile(route):
                            calls.append('reconcile')
                            if failure=='http': route.fulfill(status=502,json={'detail':'Invalid observations'})
                            elif failure=='network': route.abort()
                            elif failure=='malformed': route.fulfill(json={'layout':{'elements':[]}})
                            else: route.fulfill(json=dict(layout=requests['render']['layout'],skipped=True,
                                corrections=['Reconciliation skipped.'],depicted_instances=None,existing_feature_bounds=[]))
                        def model(route):
                            calls.append('model'); requests['model']=route.request.post_data_json
                            route.fulfill(json={'model_url':None,'fallback':True,'warnings':[]})
                        page.route('**/render',render); page.route('**/reconcile',reconcile); page.route('**/model',model)
                        page.goto('http://yard.test/')
                        page.evaluate('''async data => {
                          const {yardState}=await import('/static/storage.js');
                          const originalPhoto=new File([await (await fetch(data.original_photo)).blob()],'yard.png',{type:'image/png'});
                          await yardState({...data,originalPhoto,budget:500});
                        }''',data)
                        page.goto('http://yard.test/view'); page.wait_for_selector('#fallback')
                        self.assertEqual(calls,['render','reconcile','model'])
                        self.assertEqual(requests['model']['layout'],requests['render']['layout'])
                        self.assertNotIn('depicted_instances',requests['model'])
                        self.assertIn('skipped',page.locator('#reconcile-status').inner_text())
                        self.assertEqual(page.locator('[data-stage="model"]').get_attribute('data-state'),'failed')
                        self.assertTrue(page.locator('#render-results').is_visible())
                        page.reload(); page.wait_for_selector('#fallback')
                        self.assertEqual(calls.count('reconcile'),1)
                        self.assertEqual(errors,[])
                        page.close()
            finally: browser.close()

    def test_single_action_sequence_progress_selection_and_fallback_retry(self):
        data = payload()
        data['layout']['budget'] = 250
        extra = {**data['layout']['elements'][0], 'id': 'extra', 'type': 'Extra chair'}
        data['layout']['elements'].append(extra)
        data['layout']['sourced_materials_total_usd'] = 396
        design = {key:data['layout'][key] for key in ('elements','notes')}
        calls, requests, errors = [], {}, []
        renders, reconciles = [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport=dict(width=1200,height=900))
                serve_ui(page)
                page.on('pageerror',lambda error:errors.append(str(error)))
                def stage_route(route):
                    name=route.request.url.rsplit('/',1)[1]
                    calls.append(name)
                    self.assertEqual(page.locator(f'[data-stage="{name}"]').get_attribute('data-state'),'running')
                    self.assertTrue(page.locator('#inputs').evaluate('(el) => el.disabled'))
                    if name!='analyze': requests[name]=route.request.post_data_json
                    route.fulfill(json={'analyze':data['analysis'],'design':design,'source':data['layout']}[name])
                for name in ('analyze','design','source'): page.route('**/'+name,stage_route)
                def render_route(route):
                    calls.append('render'); renders.append(route.request.post_data_json)
                    self.assertEqual(page.locator('[data-stage="render"]').get_attribute('data-state'),'running')
                    if len(renders)==1: route.fulfill(status=504,json={'detail':'Rendering timed out. Please retry.'})
                    else: route.fulfill(json={'image_url':data['original_photo'],'prompt':'fixture'})
                def reconcile_route(route):
                    calls.append('reconcile'); reconciles.append(route.request.post_data_json)
                    self.assertTrue(page.locator('#render-results').is_visible())
                    self.assertEqual(page.locator('[data-stage="reconcile"]').get_attribute('data-state'),'running')
                    corrected=route.request.post_data_json['layout']
                    corrected['elements'][0]['position_x_ft']=12
                    corrected['elements'][0]['quantity']=1
                    corrected['elements'][0]['sourced_total_usd']=99
                    route.fulfill(json=dict(layout=corrected,depicted_instances=[dict(element_id='chair',position_x_ft=12,position_y_ft=8,width_ft=4,length_ft=5)],
                        existing_feature_bounds=[],corrections=['Chair moved to right; quantity corrected to one.'],confidence='medium',limitations='Approximate perspective'))
                def model_route(route):
                    calls.append('model'); requests['model']=route.request.post_data_json
                    self.assertEqual(page.locator('[data-stage="reconcile"]').get_attribute('data-state'),'done')
                    self.assertEqual(page.locator('[data-stage="model"]').get_attribute('data-state'),'running')
                    route.fulfill(json={'fallback':True,'model_url':None,'warnings':['Blender failed']})
                page.route('**/render',render_route); page.route('**/reconcile',reconcile_route); page.route('**/model',model_route)
                page.goto('http://yard.test/')
                page.locator('#photo').set_input_files(dict(name='yard.png',mimeType='image/png',buffer=png()))
                page.locator('#budget').fill('250'); page.locator('#area').fill('850')
                page.locator('#user-intent').fill('I want a pool and a fire pit')
                page.get_by_role('button',name='Modern',exact=True).click()
                self.assertEqual(calls,[])
                page.get_by_role('button',name='Design my yard').click(); page.wait_for_url('**/view')
                page.wait_for_function("document.querySelector('#render-status').textContent.includes('timed out')")
                self.assertEqual(calls,['analyze','design','source','render'])
                self.assertEqual(requests['design']['area_sq_ft'],850)
                self.assertEqual(requests['design']['user_intent'],'I want a pool and a fire pit. Modern style')
                self.assertEqual(renders[0]['original_photo'],data['original_photo'])
                self.assertIn('Over budget',page.locator('#budget-note').inner_text())
                page.locator('input[data-element-id="extra"]').uncheck()
                self.assertIn('$198.00',page.locator('#materials-total').inner_text())
                page.get_by_role('button',name='Update preview').click()
                page.wait_for_selector('#fallback')
                self.assertEqual(len(renders),2)
                self.assertEqual(reconciles[-1]['redesigned_photo'],data['original_photo'])
                self.assertEqual(requests['model']['layout']['elements'][0]['position_x_ft'],12)
                self.assertEqual(requests['model']['depicted_instances'][0]['element_id'],'chair')
                self.assertIn('Chair moved',page.locator('#corrections').inner_text())
                self.assertIn('$99.00',page.locator('#materials-total').inner_text())
                self.assertTrue(page.locator('#render-results').is_visible())
                page.reload(); page.wait_for_selector('#fallback')
                self.assertEqual(len(renders),2); self.assertEqual(len(reconciles),1)
                page.locator('input[data-element-id="chair"]').uncheck()
                self.assertTrue(page.locator('#render-results').is_hidden())
                self.assertIn('$0.00',page.locator('#materials-total').inner_text())
                page.get_by_role('link',name='Edit inputs').click()
                page.wait_for_function("document.querySelector('#budget').value === '250'")
                self.assertEqual(page.locator('#area').input_value(),'850')
                self.assertFalse(page.locator('#photo').evaluate('(el) => el.required'))
                self.assertEqual(errors,[])
            finally: browser.close()

    def test_failed_design_stops_pipeline_and_allows_retry(self):
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            try:
                page=browser.new_page(); serve_ui(page)
                calls=[]
                page.route('**/analyze',lambda r:r.fulfill(json=payload()['analysis']))
                page.route('**/design',lambda r:r.fulfill(status=503,json={'detail':'Service unavailable. Please retry.'}))
                page.route('**/source',lambda r:(calls.append('source'),r.fulfill(json={})))
                page.goto('http://yard.test/')
                page.locator('#photo').set_input_files(dict(name='yard.png',mimeType='image/png',buffer=png()))
                page.locator('#budget').fill('500')
                page.get_by_role('button',name='Design my yard').click()
                page.wait_for_function("document.querySelector('[data-stage=design]').dataset.state === 'failed'")
                self.assertEqual(calls,[])
                self.assertTrue(page.get_by_role('button',name='Design my yard').is_enabled())
                self.assertEqual(page.locator('[data-stage=source]').get_attribute('data-state'),'waiting')
            finally: browser.close()

    def test_collision_sliding_yard_edges_and_spawn(self):
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            try:
                page=browser.new_page(); serve_ui(page); page.goto('http://yard.test/')
                result=page.evaluate('''async () => {
                  const m=await import('/static/walking.js');
                  const wall=[[4,-10,4.02,0]];
                  return {
                    blocked:m.moveWithCollision({x:2,z:-5},6,0,10,10,wall),
                    slide:m.moveWithCollision({x:3.7,z:-5},1,1,10,10,wall),
                    free:m.moveWithCollision({x:2,z:-5},6,0,10,10,[]),
                    edge:m.moveWithCollision({x:1,z:-5},-5,0,10,10,[]),
                    trapped:m.spawnPoint(10,10,[[0,-10,10,0]]),
                    eye:m.EYE_HEIGHT
                  };
                }''')
                self.assertLess(result['blocked']['x'],3.8)
                self.assertGreater(result['slide']['z'],-4.1)
                self.assertAlmostEqual(result['free']['x'],8)
                self.assertGreaterEqual(result['edge']['x'],.23)
                self.assertIsNone(result['trapped'])
                self.assertAlmostEqual(result['eye'],1.6764)
            finally: browser.close()
