from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import struct
from fastapi.testclient import TestClient
from main import (app, ReconcileRequest, ImageReconciliation, reconciled_result,
                  DesignRequest, DesignLayout, validate_layout, RenderRequest, build_render_prompt)
from modeling import scene_data
from test_render import payload


def observation():
    return dict(elements=[dict(element_id='chair',depicted_type='Patio chair',product_matches=True,
        observation='One chair on the right.',instances=[dict(position_x_ft=12,position_y_ft=8,width_ft=3,length_ft=4)])],
        existing_features=[dict(feature='Wooden shed at far right',status='removed',observation='Shed removed in edited image.',bounds=[])],
        unexpected_elements=[],corrections=[],confidence='medium',limitations='Perspective estimate.')


def request():
    data=payload(); data['redesigned_photo']=data['original_photo']; data['layout']['budget']=150
    return data


def raw_response(value):
    raw={'status':'completed','output_text':json.dumps(value) if not isinstance(value,str) else value}
    return SimpleNamespace(**raw,model_dump=lambda **kwargs:raw)


class ReconcileTests(unittest.TestCase):
    def test_image_inputs_and_trusted_prices_corrected_quantities(self):
        with patch.dict('os.environ',OPENAI_API_KEY='test'), patch('main.OpenAI') as api, TestClient(app) as client:
            parse=api.return_value.__enter__.return_value.responses.create
            parse.return_value=raw_response(observation())
            response=client.post('/reconcile',json=request())
            self.assertEqual(response.status_code,200,response.text)
            args=parse.call_args.kwargs
            self.assertEqual(args['temperature'],0); self.assertFalse(args['store'])
            content=args['input'][0]['content']
            self.assertEqual(len([c for c in content if c['type']=='input_image']),2)
            self.assertIn('Hampton Bay',content[0]['text'])
            result=response.json(); item=result['layout']['elements'][0]
            self.assertEqual(item['quantity'],1); self.assertEqual(item['position_x_ft'],12)
            self.assertEqual(item['sourced_product']['price'],99)
            self.assertEqual(result['layout']['sourced_materials_total_usd'],99)
            self.assertIn('Within budget',result['layout']['budget_note'])
            self.assertEqual(result['layout']['existing_feature_decisions'][0]['action'],'remove')
            self.assertTrue(result['corrections'])

    def test_missing_mismatched_and_unexpected_objects_are_not_falsely_priced(self):
        obs=observation(); obs['elements'][0]['product_matches']=False
        obs['elements'][0]['depicted_type']='String light'
        obs['unexpected_elements']=[dict(id='extra',type='Planter',category='plant',quantity=1,
            position_x_ft=2,position_y_ft=2,width_ft=2,length_ft=2)]
        result=reconciled_result(ReconcileRequest.model_validate(request()),ImageReconciliation.model_validate(obs))
        self.assertEqual(result['layout']['sourced_materials_total_usd'],0)
        self.assertFalse(result['layout']['sourcing_complete'])
        self.assertEqual(result['layout']['elements'][0]['type'],'String light')
        self.assertIsNone(result['layout']['elements'][0]['sourced_product'])
        self.assertEqual(len(result['depicted_instances']),2)
        obs=observation(); obs['elements'][0]['instances']=[]
        result=reconciled_result(ReconcileRequest.model_validate(request()),ImageReconciliation.model_validate(obs))
        self.assertEqual(result['layout']['elements'],[])

    def test_missing_fields_are_filled_and_validation_is_logged(self):
        with TemporaryDirectory() as directory, patch('main.RECONCILIATION_LOG_ROOT',Path(directory)), patch.dict('os.environ',OPENAI_API_KEY='test'), patch('main.OpenAI') as api, TestClient(app) as client:
            raw={'elements':[{'element_id':'chair','instances':[{'position_x_ft':12}]}]}
            api.return_value.__enter__.return_value.responses.create.return_value=raw_response(raw)
            response=client.post('/reconcile',json=request())
            self.assertEqual(response.status_code,200,response.text)
            result=response.json()
            self.assertFalse(result['skipped'])
            self.assertEqual(result['layout']['elements'][0]['position_x_ft'],12)
            self.assertEqual(result['layout']['elements'][0]['sourced_product']['price'],99)
            self.assertEqual(result['layout']['existing_feature_decisions'][0]['action'],'keep')
            self.assertTrue(any('missing' in c for c in result['corrections']))
            log=json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertEqual(log['raw_response']['output_text'],json.dumps(raw))
            self.assertTrue(log['validation_failures'][0]['errors'])
            self.assertTrue(log['repairs'])
            fmt=api.return_value.__enter__.return_value.responses.create.call_args.kwargs['text']['format']
            self.assertTrue(fmt['strict']); self.assertEqual(fmt['type'],'json_schema')
            self.assertIn('existing_features',fmt['schema']['required'])

    def test_invalid_observations_and_api_failure_skip_without_changing_layout(self):
        invalid=observation(); invalid['elements'][0]['instances'][0]['position_x_ft']=10000
        with TemporaryDirectory() as directory, patch('main.RECONCILIATION_LOG_ROOT',Path(directory)), patch.dict('os.environ',OPENAI_API_KEY='test'), patch('main.OpenAI') as api, TestClient(app) as client:
            create=api.return_value.__enter__.return_value.responses.create
            for raw in (invalid, {'elements':'invalid'}, 'not-json'):
                create.return_value=raw_response(raw)
                response=client.post('/reconcile',json=request())
                result=response.json()
                self.assertEqual(response.status_code,200)
                self.assertTrue(result['skipped'])
                self.assertEqual(result['layout'],ReconcileRequest.model_validate(request()).layout.model_dump())
                self.assertIsNone(result['depicted_instances'])
                log=json.loads((Path(directory)/(result['diagnostic_id']+'.json')).read_text())
                self.assertTrue(log['validation_failures'])
                self.assertIsNotNone(log['raw_response'])
            create.side_effect=RuntimeError('Transport failed')
            self.assertTrue(client.post('/reconcile',json=request()).json()['skipped'])
            data=request(); data['redesigned_photo']='https://example.com/image.png'
            self.assertTrue(client.post('/reconcile',json=data).json()['skipped'])

    def test_missing_observations_preserve_quantity_but_explicit_absence_removes(self):
        with patch.dict('os.environ',OPENAI_API_KEY='test'), patch('main.OpenAI') as api, TestClient(app) as client:
            create=api.return_value.__enter__.return_value.responses.create
            create.return_value=raw_response({})
            result=client.post('/reconcile',json=request()).json()
            self.assertFalse(result['skipped'])
            self.assertEqual(result['layout']['elements'][0]['quantity'],2)
            self.assertEqual(result['layout']['elements'][0]['sourced_total_usd'],198)
            obs=observation(); obs['elements'][0]['instances']=[]
            create.return_value=raw_response(obs)
            self.assertEqual(client.post('/reconcile',json=request()).json()['layout']['elements'],[])

    def test_model_preserves_individual_footprints_and_removed_structures(self):
        data=request(); obs=observation()
        obs['elements'][0]['instances'].append(dict(position_x_ft=2,position_y_ft=18,width_ft=2.5,length_ft=3))
        result=reconciled_result(ReconcileRequest.model_validate(data),ImageReconciliation.model_validate(obs))
        scene,notes=scene_data(data['analysis'],result['layout'],result['existing_feature_bounds'],result['depicted_instances'])
        self.assertEqual(len(scene['objects']),2)  # No invented enclosure or removed shed.
        self.assertEqual([(o['x'],o['y'],o['width'],o['length']) for o in scene['objects']],[(12,8,3,4),(2,18,2.5,3)])
        self.assertEqual(scene['placement_changes'],[])
        result['depicted_instances'][1].update(position_x_ft=12,position_y_ft=8)
        adjusted,notes=scene_data(data['analysis'],result['layout'],[],result['depicted_instances'])
        self.assertEqual(len(adjusted['objects']),2)
        self.assertTrue(adjusted['placement_changes'])

    def test_model_rejects_unknown_ids_and_wrong_counts(self):
        data=payload(); data.pop('original_photo')
        data['depicted_instances']=[dict(element_id='unknown',position_x_ft=2,position_y_ft=2,width_ft=1,length_ft=1)]
        with TestClient(app) as client, patch('main.generate_model') as generate:
            self.assertEqual(client.post('/model',json=data).status_code,422)
            data['depicted_instances'][0]['element_id']='chair'
            self.assertEqual(client.post('/model',json=data).status_code,422)
            generate.assert_not_called()

    def test_reconciled_footprints_survive_real_blender_export(self):
        data=request(); obs=observation()
        result=reconciled_result(ReconcileRequest.model_validate(data),ImageReconciliation.model_validate(obs))
        with TemporaryDirectory() as directory, patch('modeling.MODEL_ROOT',Path(directory)), patch('main.MODEL_ROOT',Path(directory)), TestClient(app) as client:
            response=client.post('/model',json=dict(analysis=data['analysis'],layout=result['layout'],
                existing_feature_bounds=result['existing_feature_bounds'],depicted_instances=result['depicted_instances']))
            self.assertEqual(response.status_code,200,response.text)
            self.assertFalse(response.json()['fallback'],response.text)
            raw=client.get(response.json()['model_url']).content
            document=json.loads(raw[20:20+struct.unpack_from('<I',raw,12)[0]])
            items=[n for n in document['nodes'] if n.get('extras',{}).get('element_id')=='chair']
            self.assertEqual(len(items),1)
            envelope=items[0]['extras']['geometry_bounds_ft']
            self.assertGreaterEqual(envelope[0],12-.001); self.assertGreaterEqual(envelope[1],8-.001)
            self.assertLessEqual(envelope[2],15+.001); self.assertLessEqual(envelope[3],12+.001)
            self.assertFalse(any(n.get('extras',{}).get('existing_feature') for n in document['nodes']))
            self.assertEqual(response.json()['placement_changes'],[])

    def test_dense_scene_exports_every_instance_even_when_edge_placement_conflicts(self):
        data=payload(); data.pop('original_photo')
        data['analysis'].update(width_ft={'min':2,'max':2},length_ft={'min':2,'max':2},existing_features=[])
        data['layout']['elements'][0].update(quantity=4,position_x_ft=0,position_y_ft=0,width_ft=2,length_ft=2,sourced_total_usd=396)
        data['layout']['sourced_materials_total_usd']=396
        with TemporaryDirectory() as directory, patch('modeling.MODEL_ROOT',Path(directory)), patch('main.MODEL_ROOT',Path(directory)), TestClient(app) as client:
            response=client.post('/model',json=data)
            result=response.json()
            self.assertFalse(result['fallback'],response.text)
            self.assertEqual(result['omitted_element_ids'],[])
            self.assertEqual(result['adjusted_layout']['elements'][0]['quantity'],4)
            self.assertEqual(result['adjusted_layout']['sourced_materials_total_usd'],396)
            self.assertTrue(any(c['action']=='edge_fallback' for c in result['placement_changes']))
            raw=client.get(result['model_url']).content
            document=json.loads(raw[20:20+struct.unpack_from('<I',raw,12)[0]])
            self.assertEqual(sum(n.get('extras',{}).get('element_id')=='chair' for n in document['nodes']),4)

    def test_design_keep_remove_decisions_and_walkable_clearance(self):
        data=payload(); feature=data['analysis']['existing_features'][0]
        req=DesignRequest(analysis=data['analysis'],budget=500)
        item={k:v for k,v in data['layout']['elements'][0].items() if k in ('id','type','category','quantity','position_x_ft','position_y_ft','width_ft','length_ft')}
        second={**item,'id':'second','position_x_ft':4}
        layout=DesignLayout(elements=[item,second],notes=[],existing_feature_decisions=[dict(feature=feature,action='remove',reason='Open space for circulation.')])
        result=validate_layout(layout,req)
        self.assertEqual(result.existing_feature_decisions[0].action,'remove')
        self.assertEqual(len(result.elements),2)
        a,b=result.elements
        self.assertTrue(b.position_x_ft>=a.position_x_ft+a.width_ft+.3 or b.position_y_ft>=a.position_y_ft+a.length_ft+.3
                        or a.position_x_ft>=b.position_x_ft+b.width_ft+.3 or a.position_y_ft>=b.position_y_ft+b.length_ft+.3)
        data['layout']['existing_feature_decisions']=[d.model_dump() for d in result.existing_feature_decisions]
        prompt=build_render_prompt(RenderRequest.model_validate(data))
        self.assertIn('Remove ONLY',prompt)
        self.assertIn('"existing_features_to_preserve": []',prompt)
        fallback=validate_layout(DesignLayout(elements=[],notes=[]),req)
        self.assertEqual(fallback.existing_feature_decisions[0].action,'keep')
        self.assertTrue(fallback.existing_feature_decisions[0].reason)
