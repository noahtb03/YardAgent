"""Conservative, deterministic footprint packing in feet before mesh generation.

Clearance bounds contain the complete composite, including canopies, roof eaves
and bar stools. Static measured structures never move. A failed fit is explicit:
retain every addition, with explicit warnings for unavoidable edge conflicts.
"""
from copy import deepcopy
import logging
import math
import re

LOG = logging.getLogger(__name__)


def asset_kind(text):
    text = text.lower()
    for name, words in (
        ('light', ('light', 'lamp')), ('fence', ('fence',)),
        ('bar', ('outdoor bar', 'bar counter', 'bar hardscape')),
        ('grill', ('grill', 'barbecue', 'bbq')),
        ('planter', ('planter', 'raised bed', 'garden bed')),
        ('shed', ('shed',)), ('dining_set', ('dining set','bistro set','patio furniture set')),
        ('tree', ('tree',)), ('chair', ('chair', 'bench', 'sofa', 'loveseat','lounger','seating')),
        ('table', ('table',)), ('pool', ('pool',)), ('patio', ('patio', 'paver', 'walkway', 'path')),
        ('plant', ('plant', 'shrub', 'bush', 'flower')), ('fire_pit', ('fire pit', 'fire_pit')),
        ('pergola', ('pergola', 'gazebo', 'pavilion')),
    ):
        if any(word in text for word in words):
            return name
    if re.search(r'\bdeck\b',text): return 'deck'
    if re.search(r'\bbar\b',text): return 'bar'
    return 'feature'


def proportion_object(obj):
    """Never stretch a chair to occupy its whole allocation or shrink a bar.

Retail feeds currently lack verified dimensions. These are explicit typical
full-size envelopes, in feet; site-sized hardscape uses its layout dimensions.
"""
    kind = obj['asset'] = asset_kind(obj['kind'])
    if obj.get('static'):
        obj['clearance'] = .15 if kind=='tree' else 0
        return
    defaults = {'chair': (2.6, 3, 3.4), 'table': (3.5, 3.5, 2.5), 'dining_set':(8,8,3.4),
                'bar': (8, 5.5, 3.5), 'grill': (4.5, 2.5, 4),
                'planter': (2, 2, 2), 'light': (.6, .6, 2),
                'tree': (6, 6, 12), 'plant': (2, 2, 2.5), 'fire_pit': (3,3,1.5)}
    if kind in defaults:
        w,l,h = defaults[kind]
        # Accommodate explicitly larger canopy/planter allocations, while a
        # dining chair retains credible human proportions.
        if kind in ('tree','planter','plant'):
            w,l = max(w,obj['width']),max(l,obj['length'])
        if kind == 'tree':
            w = l = max(w,l)  # Full circular canopy gets a conservative square.
            h = max(h, min(25, w*1.7))
        text = obj['kind']
        if kind == 'chair' and any(word in text for word in ('bench','sofa','loveseat')):
            w = 6
        obj['x'] += (obj['width']-w)/2
        obj['y'] += (obj['length']-l)/2
        obj['width'],obj['length'],obj['height'] = w,l,h
        obj['dimension_basis'] = 'Typical full-size proportions; retailer dimensions are not provided.'
    obj['clearance'] = clearance_for(kind)


def bounds(obj):
    margin = obj.get('clearance', 0)
    return (obj['x']-margin, obj['y']-margin,
            obj['x']+obj['width']+margin, obj['y']+obj['length']+margin)


def intersects(a, b):
    a,b = bounds(a),bounds(b)
    return a[0] < b[2]-1e-7 and b[0] < a[2]-1e-7 and a[1] < b[3]-1e-7 and b[1] < a[3]-1e-7


def within(obj, width, length):
    x,y,xx,yy = bounds(obj)
    return x>=-1e-7 and y>=-1e-7 and xx<=width+1e-7 and yy<=length+1e-7


def relocate(obj, placed, width, length):
    margin = obj.get('clearance',0)
    xmax,ymax = width-obj['width']-margin,length-obj['length']-margin
    if xmax<margin or ymax<margin:
        return None
    original = (obj['x'],obj['y'])
    candidate = deepcopy(obj)
    seen = set()
    # Repeated minimum separating translations, with a bounded fallback search
    # over obstacle edges. Previously placed high-priority items remain stable.
    for _ in range(160):
        candidate['x'] = min(xmax,max(margin,candidate['x']))
        candidate['y'] = min(ymax,max(margin,candidate['y']))
        point = (round(candidate['x'],6),round(candidate['y'],6))
        if point in seen:
            break
        seen.add(point)
        conflict = next((p for p in placed if intersects(candidate,p)),None)
        if conflict is None:
            return candidate
        left,near,right,far = bounds(conflict)
        options = [(left-obj['width']-margin,candidate['y']), (right+margin,candidate['y']),
                   (candidate['x'],near-obj['length']-margin), (candidate['x'],far+margin)]
        valid = [(x,y) for x,y in options if margin<=x<=xmax and margin<=y<=ymax and (round(x,6),round(y,6)) not in seen]
        if not valid:
            break
        candidate['x'],candidate['y'] = min(valid,key=lambda p: math.dist(p,original))
    xs = {margin,xmax,min(xmax,max(margin,original[0]))}
    ys = {margin,ymax,min(ymax,max(margin,original[1]))}
    for p in placed:
        a,b,c,d = bounds(p)
        xs.update(x for x in (a-obj['width']-margin,c+margin) if margin<=x<=xmax)
        ys.update(y for y in (b-obj['length']-margin,d+margin) if margin<=y<=ymax)
    # Nearest edges first; cap pathological API scenes rather than hanging.
    xs = sorted(xs,key=lambda x:abs(x-original[0]))[:128]
    ys = sorted(ys,key=lambda y:abs(y-original[1]))[:128]
    options = sorted(((x,y) for x in xs for y in ys),key=lambda p:math.dist(p,original))
    for x,y in options[:30000]:
        candidate['x'],candidate['y'] = x,y
        if not any(intersects(candidate,p) for p in placed):
            return candidate
    return None


def clearance_for(kind):
    # Small placement buffers, not a mandatory walking aisle around every item.
    return .25 if kind == 'tree' else .15 if kind in ('bar','grill','chair','table') else .05 if kind == 'light' else .1


MINIMUM_FOOTPRINTS = {
    'chair':(1.8,2), 'table':(2,2), 'dining_set':(5,5), 'bar':(4,3),
    'grill':(2.5,2), 'planter':(1,1), 'light':(.2,.2), 'tree':(3,3),
    'plant':(.5,.5), 'fire_pit':(2,2), 'pool':(6,8), 'patio':(3,3),
    'deck':(4,4), 'pergola':(4,4), 'shed':(3,3), 'feature':(1,1),
}


def minimum_footprint(obj):
    kind = obj.get('asset') or asset_kind(obj['kind'])
    w,l = MINIMUM_FOOTPRINTS.get(kind,(1,1))
    # Group footprints preserve quantity, including when design precedes sourcing.
    count = obj.get('quantity',1)
    cols = min(count,max(1,math.ceil(math.sqrt(count*obj['width']/obj['length']))))
    rows = math.ceil(count/cols)
    return min(obj['width'],w*cols),min(obj['length'],l*rows)


def resolve_placement(objects, width, length, preserve_dimensions=False, area_limit=None):
    objects = deepcopy(objects)
    moves,notes = [],[]

    def record(before, after, action, reason):
        change = dict(element_id=after.get('element_id',''),instance=after.get('instance',1),name=after['name'],
            action=action,from_ft=[before['x'],before['y']],to_ft=[after['x'],after['y']],
            from_size_ft=[before['width'],before['length']],to_size_ft=[after['width'],after['length']],reason=reason)
        change.update(from_clearance_ft=before.get('clearance',0),to_clearance_ft=after.get('clearance',0))
        moves.append(change)
        message = (f"{action}: '{after['name']}' #{change['instance']} "
            f"({before['x']:.2f}, {before['y']:.2f}), {before['width']:.2f} x {before['length']:.2f} ft -> "
            f"({after['x']:.2f}, {after['y']:.2f}), {after['width']:.2f} x {after['length']:.2f} ft. {reason}")
        notes.append(message)
        LOG.warning(message) if action in ('edge_fallback','static_conflict') else LOG.info(message)

    for obj in objects:
        before = deepcopy(obj)
        obj['requested_position'] = [obj['x'],obj['y']]
        proportion_object(obj)
        if preserve_dimensions:
            obj.update({k:before[k] for k in ('x','y','width','length')})
        if any(obj[k]!=before[k] for k in ('x','y','width','length')):
            record(before,obj,'proportions','Applied typical object proportions before checking fit.')
    fixed = [o for o in objects if o.get('static')]
    for i,obj in enumerate(fixed):
        if any(intersects(obj,other) for other in fixed[:i]):
            record(obj,obj,'static_conflict','Existing structure bounds intersect; retained their original positions.')
    additions = [o for o in objects if not o.get('static')]
    placed = list(fixed)
    for obj in additions:
        before = deepcopy(obj)
        result = relocate(obj,placed,width,length)
        reason = 'Moved to available space with a small clearance buffer.'
        action = 'move'
        if result is None:
            # Physical fit is enough when only optional padding conflicts.
            tight = {**obj,'clearance':0}
            obstacles = [{**p,'clearance':0} for p in placed]
            result = relocate(tight,obstacles,width,length)
            if result is not None:
                action,reason = 'clearance_relaxed','Relaxed optional clearance; physical footprints fit without intersections.'
            else:
                mw,ml = minimum_footprint(obj)
                for fraction in (.8,.6,.4,.2,0):
                    candidate = {**tight,'width':mw+(obj['width']-mw)*fraction,
                                 'length':ml+(obj['length']-ml)*fraction}
                    result = relocate(candidate,obstacles,width,length)
                    if result is not None:
                        action,reason = 'resize','Moved and reduced footprint toward minimum viable size; quantity retained. Verify product dimensions before purchasing.'
                        break
                if result is None:
                    result = {**tight,'width':mw,'length':ml}
                    xmax,ymax = max(0,width-mw),max(0,length-ml)
                    x,y = min(xmax,max(0,obj['x'])),min(ymax,max(0,obj['y']))
                    edge = min([(0,y),(xmax,y),(x,0),(x,ymax)],key=lambda p:math.dist(p,(obj['x'],obj['y'])))
                    result['x'],result['y'] = edge
                    result['edge_fallback'] = True
                    conflicts = [p['name'] for p in placed if intersects(result,{**p,'clearance':0})]
                    action = 'edge_fallback'
                    reason = 'No conflict-free fit at minimum viable size. Retained at nearest edge; layout needs manual adjustment.'
                    if conflicts: reason += ' Overlaps: '+', '.join(conflicts)+'.'
                    if mw>width or ml>length: reason += ' Minimum viable footprint extends beyond the yard boundary.'
        if action!='move' or any(result[k]!=before[k] for k in ('x','y','width','length')):
            record(before,result,action,reason)
        placed.append(result)
    additions = [o for o in placed if not o.get('static')]
    # Area cannot be improved by translation. Reduce lower-priority groups only
    # as far as viable dimensions; remaining excess is a warning, never a deletion.
    if area_limit is not None:
        total = sum(o['width']*o['length'] for o in additions)
        if total > area_limit:
            notes.append(f'Layout footprints total {total:g} sq ft, exceeding available area by {total-area_limit:g} sq ft.')
        for obj in reversed(additions):
            if total <= area_limit+1e-7: break
            before = deepcopy(obj)
            mw,ml = minimum_footprint(obj)
            target = max(mw*ml,obj['width']*obj['length']-(total-area_limit))
            low,high = 0.0,1.0
            for _ in range(40):
                scale = (low+high)/2
                if max(mw,obj['width']*scale)*max(ml,obj['length']*scale) <= target:
                    low = scale
                else:
                    high = scale
            scale = low
            obj['width'],obj['length'] = max(mw,obj['width']*scale),max(ml,obj['length']*scale)
            total -= before['width']*before['length']-obj['width']*obj['length']
            if (obj['width'],obj['length'])!=(before['width'],before['length']):
                record(before,obj,'resize','Reduced footprint toward its minimum viable size for the area allowance; quantity retained.')
        if total > area_limit+1e-7:
            message=f'Area remains over by {total-area_limit:g} sq ft at minimum viable sizes; all elements retained.'
            notes.append(message); LOG.warning(message)
    return placed,moves,[],notes
