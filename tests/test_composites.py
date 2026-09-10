import json
import shutil
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
from modeling import blender_executable
from sourcing import estimate_feature
from test_render import payload


class CompositeTests(unittest.TestCase):
    def test_bar_grill_deck_dimensions_and_recorded_moves(self):
        executable=blender_executable()
        if not Path(executable).is_file() and not shutil.which(executable): self.skipTest('Blender not installed')
        data=payload();data.pop('original_photo');data['analysis']['existing_features']=[]
        data['analysis']['width_ft']=data['analysis']['length_ft']={'min':50,'max':50}
        template=data['layout']['elements'][0]
        data['layout']['elements']=[]
        for name,category,w,l in [('Outdoor bar','hardscape',8,5.5),('Gas grill','furniture',4.5,2.5),('Deck','hardscape',10,10)]:
            item={**template,'id':name,'type':name,'category':category,'quantity':1,'position_x_ft':10,'position_y_ft':10,'width_ft':w,'length_ft':l}
            if category=='hardscape':
                item.update(estimated_feature=estimate_feature(item,'bar' if name=='Outdoor bar' else 'deck'),sourced_product=None,sourcing_status='estimated')
            data['layout']['elements'].append(item)
        with TemporaryDirectory() as directory,patch('modeling.MODEL_ROOT',Path(directory)),patch('main.MODEL_ROOT',Path(directory)),TestClient(app) as client:
            result=client.post('/model',json=data).json()
            self.assertFalse(result['fallback'],result)
            self.assertGreaterEqual(len(result['placement_changes']),2)
            log=json.loads(next(Path(directory).glob('*/placement.json')).read_text())
            self.assertEqual(log['moves'],result['placement_changes'])
            glb=client.get(result['model_url']).content
            size=struct.unpack_from('<I',glb,12)[0]
            document=json.loads(glb[20:20+size]);nodes=document['nodes']
            for component in ['Bar base cabinet','Overhanging bar top','Bar cabinet door','Bar foot rail','Grill cart leg',
                              'Grill rounded lid','Grill control knob','Deck board','Deck baluster','Deck handrail','Deck step']:
                self.assertTrue(any(n['name'].startswith(component) for n in nodes),component)
            self.assertEqual(sum(n['name'].startswith('Stool seat') for n in nodes),3)
            bar=next(e for e in result['adjusted_layout']['elements'] if e['id']=='Outdoor bar')
            self.assertEqual((bar['width_ft'],bar['length_ft']),(8,5.5))
            bounds=[n['extras']['geometry_bounds_ft'] for n in nodes if 'geometry_bounds_ft' in n.get('extras',{})]
            for i,a in enumerate(bounds):
                for b in bounds[:i]:
                    self.assertFalse(a[0]<b[2]-.001 and b[0]<a[2]-.001 and a[1]<b[3]-.001 and b[1]<a[3]-.001,(a,b))

    def test_conflicting_existing_features_warn_and_still_attempt_blender(self):
        data=payload();data.pop('original_photo');data['analysis']['existing_features']=[]
        data['existing_feature_bounds']=[dict(name=name,position_x_ft=5,position_y_ft=5,width_ft=8,length_ft=8) for name in ['Deck','Shed']]
        with TestClient(app) as client,patch('modeling.subprocess.run') as run:
            response=client.post('/model',json=data)
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()['fallback'])
            self.assertIn('Existing structure bounds intersect',' '.join(response.json()['warnings']))
            run.assert_called_once()
