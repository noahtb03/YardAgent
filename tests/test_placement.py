import random
import unittest
from copy import deepcopy
from placement import resolve_placement, intersects, within, asset_kind


def obj(id, kind='chair furniture', x=2,y=2,w=2,l=3,static=False,instance=1):
    return dict(name=id,element_id='' if static else id,kind=kind,x=x,y=y,width=w,length=l,height=3,
                static=static,instance=instance)


class PlacementTests(unittest.TestCase):
    def test_canopies_chairs_and_structures_are_separated_and_moves_logged(self):
        objects=[obj('shed','shed',10,10,8,8,True),obj('oak','oak tree plant',10,10,2,2),
                 obj('maple','maple tree plant',10,10,2,2),obj('chair',x=10,y=10)]
        original=deepcopy(objects)
        with self.assertLogs('placement',level='INFO') as logs:
            placed,moves,omitted,notes=resolve_placement(objects,40,40)
        self.assertEqual(objects,original)
        self.assertEqual(omitted,[])
        self.assertEqual((placed[0]['x'],placed[0]['y']),(10,10))
        self.assertGreaterEqual(len(moves),3)
        self.assertEqual(len(logs.output),len(moves))
        for i,a in enumerate(placed):
            self.assertTrue(within(a,40,40))
            for b in placed[:i]: self.assertFalse(intersects(a,b))
        tree=next(o for o in placed if o['element_id']=='oak')
        self.assertEqual(tree['width'],tree['length'])
        self.assertGreaterEqual(tree['width'],6)
        self.assertEqual(tree['clearance'],.25)

    def test_dense_fit_retains_every_quantity_and_warns_at_nearest_edge(self):
        objects=[obj('chairs',x=0,y=0,instance=i) for i in range(1,5)]
        placed,moves,omitted,notes=resolve_placement(objects,2,2)
        self.assertEqual(len(placed),4)
        self.assertEqual(omitted,[])
        self.assertTrue(any(m['action']=='edge_fallback' for m in moves))
        self.assertTrue(any('nearest edge' in n for n in notes))
        self.assertTrue(all(o['width']>=1.8 and o['length']>=2 for o in placed))

    def test_moves_before_shrinking_and_shrinks_before_edge_fallback(self):
        placed,moves,_,_=resolve_placement([obj('chair',x=2,y=2),obj('other',x=2,y=2)],20,20)
        self.assertTrue(all(o['width']==2.6 and o['length']==3 for o in placed))
        self.assertFalse(any(m['action'] in ('resize','edge_fallback') for m in moves))
        placed,moves,_,_=resolve_placement([obj('chair',x=0,y=0)],2,2.5)
        self.assertEqual(len(placed),1)
        self.assertTrue(any(m['action']=='resize' for m in moves))
        self.assertFalse(any(m['action']=='edge_fallback' for m in moves))
        self.assertTrue(within(placed[0],2,2.5))

    def test_optional_clearance_does_not_reject_physically_fitting_items(self):
        placed,moves,_,_=resolve_placement([obj('chair',x=0,y=0)],2.6,3)
        self.assertEqual((placed[0]['width'],placed[0]['length']),(2.6,3))
        self.assertTrue(any(m['action']=='clearance_relaxed' for m in moves))

    def test_priorities_and_repeated_deterministic_packing(self):
        rng=random.Random(34)
        objects=[obj(str(i),'oak tree' if i%5==0 else 'chair',rng.uniform(0,15),rng.uniform(0,15)) for i in range(30)]
        first=resolve_placement(objects,35,35)
        self.assertEqual(first,resolve_placement(objects,35,35))
        placed,_,omitted,_=first
        self.assertGreater(len(placed),15)
        self.assertNotIn('0',omitted)
        for i,a in enumerate(placed):
            self.assertTrue(within(a,35,35))
            self.assertTrue(all(not intersects(a,b) for b in placed[:i]))

    def test_static_intersections_warn_without_removing_or_moving_features(self):
        placed,moves,omitted,notes=resolve_placement([obj('deck','deck',0,0,10,10,True),obj('shed','shed',5,5,8,8,True)],30,30)
        self.assertEqual(len(placed),2)
        self.assertEqual((placed[1]['x'],placed[1]['y']),(5,5))
        self.assertEqual(omitted,[])
        self.assertTrue(any('Existing structure bounds intersect' in n for n in notes))

    def test_recognizable_asset_classification_and_human_scale(self):
        for text,expected in [('Deck near house','deck'),('Patio chair furniture','chair'),
                              ('Outdoor bar hardscape','bar'),('Gas barbecue furniture','grill'),
                              ('Patio furniture set','dining_set')]:
            self.assertEqual(asset_kind(text),expected)
        placed,_,_,_=resolve_placement([obj('bar','Outdoor bar',w=2,l=2),obj('chair',x=20,y=20,w=12,l=12)],50,50)
        bar=next(o for o in placed if o['element_id']=='bar')
        chair=next(o for o in placed if o['element_id']=='chair')
        self.assertEqual((bar['width'],bar['length'],bar['height']),(8,5.5,3.5))
        self.assertEqual((chair['width'],chair['length']),(2.6,3))
