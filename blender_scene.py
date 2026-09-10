"""Executed only by Blender in a private job directory. Scene JSON is data.

Linked meshes export shared glTF geometry; the browser batches them into GPU
instances per selectable group. No product text is evaluated as code.
"""
import bpy
import json
import math
import random
from pathlib import Path
from mathutils import Vector

root = Path(__file__).resolve().parent
data = json.loads((root / 'scene.json').read_text(encoding='utf-8'))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
FT = .3048


def material(name, color, roughness=.8, metallic=0, alpha=1, emission=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, alpha)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, alpha)
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Alpha'].default_value = alpha
    if alpha < 1:
        mat.surface_render_method = 'DITHERED'
    if emission:
        bsdf.inputs['Emission Color'].default_value = (*color, 1)
        bsdf.inputs['Emission Strength'].default_value = emission
    return mat


mats = {
    'Grass': material('Grass', (.34,.43,.19), .97),
    'Cedar': material('Cedar', (.42,.25,.12), .82),
    'Bark': material('Bark', (.20,.095,.035), .96),
    'Leaves': material('Leaves', (.13,.29,.065), .91),
    'Leaves light': material('Leaves light', (.22,.37,.08), .88),
    'Soil': material('Soil', (.075,.04,.018), 1),
    'Terracotta': material('Terracotta', (.52,.23,.12), .88),
    'Paver': material('Paver', (.57,.53,.44), .9),
    'Grout': material('Grout', (.23,.22,.18), 1),
    'Pool lining': material('Pool lining', (.43,.65,.68), .35),
    'Water': material('Water', (.055,.42,.61), .1, .05, .65),
    'Coping': material('Coping', (.73,.69,.57), .75),
    'Metal': material('Metal', (.045,.05,.045), .34, .8),
    'Lamp': material('Lamp', (1,.68,.28), .3, 0, 1, 3),
    'Cushion': material('Cushion', (.74,.69,.56), .95),
    'Roof': material('Roof', (.13,.15,.14), .85),
    'Steel': material('Steel', (.5,.53,.55), .26, .95),
    'Concrete': material('Concrete', (.48,.46,.41), .96),
    'Glass': material('Glass', (.30,.45,.48), .12, 0, .5),
}
water = mats['Water'].node_tree.nodes.get('Principled BSDF')
water.inputs['Transmission Weight'].default_value = .85
water.inputs['IOR'].default_value = 1.333
water.inputs['Alpha'].default_value = 1
mats['Water'].diffuse_color = (.055,.42,.61,1)
meshes = {}
part_count = 0


def unit_mesh(shape, mat):
    key = (shape, mat)
    if key not in meshes:
        if shape.startswith('foliage'):
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=.5)
            for vertex in bpy.context.object.data.vertices:
                p = vertex.co
                p *= .85 + .18*math.sin(p.x*29+p.z*13) + .12*math.cos(p.y*37-p.x*15)
        elif shape == 'leaf':
            mesh = bpy.data.meshes.new('Curved leaf')
            mesh.from_pydata([(0,-.5,0),(-.32,-.18,.06),(-.24,.24,.04),(0,.5,0),(.24,.24,.04),(.32,-.18,.06),(0,0,.12)],[],
                             [(0,1,6),(1,2,6),(2,3,6),(3,4,6),(4,5,6),(5,0,6)])
            mesh.materials.append(mats[mat]); meshes[key]=mesh
            return mesh
        elif shape == 'hollow_planter':
            mesh=bpy.data.meshes.new('Tapered planter walls')
            vertices=[]
            for radius,z in ((.5,.5),(.39,-.5),(.43,.5),(.32,-.38)):
                vertices.extend([(x*radius,y*radius,z) for x,y in ((-1,-1),(1,-1),(1,1),(-1,1))])
            faces=[]
            for i in range(4):
                j=(i+1)%4
                faces.extend([(i,j,j+4,i+4),(i+8,i+12,j+12,j+8),(i,i+8,j+8,j),(i+4,j+4,j+12,i+12)])
            faces.append((12,13,14,15))
            mesh.from_pydata(vertices,[],faces);mesh.materials.append(mats[mat]);meshes[key]=mesh
            return mesh
        elif shape == 'trunk':
            bpy.ops.mesh.primitive_cone_add(vertices=12,radius1=.5,radius2=.22,depth=1)
        elif shape == 'sphere':
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=.5)
        elif shape == 'cylinder':
            bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=.5, depth=1)
        elif shape == 'taper':
            bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=.5, radius2=.7, depth=1, rotation=(0,0,math.pi/4))
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        else:
            bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.object
        mesh = obj.data
        mesh.materials.append(mats[mat])
        if shape in ('sphere', 'cylinder','trunk'):
            for polygon in mesh.polygons:
                polygon.use_smooth = True
        meshes[key] = mesh
        bpy.data.objects.remove(obj, do_unlink=True)
    return meshes[key]


def part(parent, name, position, size, mat, shape='box'):
    global part_count
    part_count += 1
    if part_count > 60000:
        raise RuntimeError('Detailed scene exceeds preview geometry limit')
    obj = bpy.data.objects.new(name, unit_mesh(shape, mat))
    bpy.context.collection.objects.link(obj)
    obj.parent = parent
    obj.location = position
    obj.scale = size
    return obj


def beam(parent,name,a,b,diameter,mat='Bark',taper=False):
    a,b=Vector(a),Vector(b)
    obj=part(parent,name,(a+b)/2,(diameter,diameter,(b-a).length),mat,'trunk' if taper else 'cylinder')
    obj.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler()
    return obj


def chair(parent,x,y,w,l,seat=.46,stool=False):
    mat='Metal' if stool else 'Cedar'
    part(parent,'Stool seat' if stool else 'Seat cushion',(x+w/2,y+l/2,seat+.04),(w*.90,l*.85,.08),'Cushion')
    for xx in (.1*w,.9*w):
        for yy in (.12*l,.88*l):
            part(parent,'Stool leg' if stool else 'Chair leg',(x+xx,y+yy,seat/2),(.045,.045,seat),mat)
    if stool:
        for yy in (.12*l,.88*l):
            beam(parent,'Stool rung',(x+.1*w,y+yy,.22),(x+.9*w,y+yy,.22),.022,'Metal')
    else:
        for xx in (.04*w,.96*w):
            part(parent,'Chair armrest',(x+xx,y+l*.48,seat+.23),(.045,l*.92,.05),'Cedar')
            part(parent,'Arm support',(x+xx,y+l*.2,seat+.10),(.035,.035,.20),'Cedar')
        for i in range(5):
            back=part(parent,'Chair back slat',(x+w*(.12+i*.19),y+l*.91,seat+.27),(w*.14,.045,.58),'Cedar')
            back.rotation_euler[0]=-.10
        part(parent,'Seat frame',(x+w/2,y+l/2,seat-.04),(w,l,.07),'Cedar')


def table(parent,x,y,w,l,h=.76):
    for i in range(7):
        part(parent,'Table top slat',(x+w/2,y+(i+.5)*l/7,h),(w,l/7*.96,.055),'Cedar')
    for xx in (.08*w,.92*w):
        for yy in (.1*l,.9*l):
            part(parent,'Table leg',(x+xx,y+yy,h/2),(.06,.06,h),'Metal')
    part(parent,'Table apron',(x+w/2,y+l/2,h-.12),(w*.9,l*.86,.10),'Cedar')


def tree(parent,w,l,h,seed=1,small=False):
    rng=random.Random(seed)
    trunk=min(.24,w*.13,l*.13)
    beam(parent,'Tapered tree trunk',(w/2,l/2,0),(w*.51,l*.49,h*.72),trunk,taper=True)
    for i in range(9 if not small else 5):
        angle=i*2.39996
        level=.47+.36*(i%4)/3
        end=(w*(.5+.22*math.cos(angle)),l*(.5+.22*math.sin(angle)),h*level)
        start=(w/2,l/2,h*(level-.18))
        beam(parent,'Tree branch',start,end,trunk*.35,taper=True)
        for j in range(2):
            tip=(end[0]+w*.05*math.cos(angle+j),end[1]+l*.05*math.sin(angle+j),end[2]+h*.10)
            beam(parent,'Tree twig',end,tip,trunk*.12,taper=True)
        canopy=part(parent,'Irregular canopy cluster',(end[0],end[1],end[2]+h*.10),(w*.32,l*.32,h*.28),
                    'Leaves' if i%2 else 'Leaves light','foliage')
        canopy.rotation_euler[2]=angle
        for j in range(0 if small else 18):
            a=rng.random()*math.tau
            radius=.08+.08*rng.random()
            leaf=part(parent,'Canopy leaves',(end[0]+w*radius*math.cos(a),end[1]+l*radius*math.sin(a),end[2]+h*(.05+.14*rng.random())),
                      (min(.12,w*.08),min(.22,l*.15),.10),'Leaves light' if j%3 else 'Leaves','leaf')
            leaf.rotation_euler=(rng.uniform(-.5,.5),rng.uniform(-.5,.5),a)


def terrain_height(x, y):
    return .012 * math.sin(x*1.3) * math.sin(y*1.7)


width, length = data['width']*FT, data['length']*FT
pools = [o for o in data['objects'] if 'pool' in o['kind']]
holes = [(o['x']*FT, o['y']*FT, (o['x']+o['width'])*FT, (o['y']+o['length'])*FT) for o in pools]


def ground_mesh(name, xs, ys, skip_holes=False):
    if len(xs)*len(ys) > 150000:
        raise RuntimeError('Terrain exceeds preview geometry limit')
    vertices = [(x,y,terrain_height(x,y)) for y in ys for x in xs]
    faces = []
    for j in range(len(ys)-1):
        for i in range(len(xs)-1):
            x,y = (xs[i]+xs[i+1])/2, (ys[j]+ys[j+1])/2
            if skip_holes and any(a<x<c and b<y<d for a,b,c,d in holes):
                continue
            if name=='Neighboring lawn' and 0<x<width and 0<y<length:
                continue
            k = j*len(xs)+i
            faces.append((k,k+1,k+1+len(xs),k+len(xs)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mats['Grass'])
    uv = mesh.uv_layers.new()
    for loop in mesh.loops:
        x,y,_ = vertices[loop.vertex_index]
        uv.data[loop.index].uv = (x,y)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


# Include pool boundaries in the grid, leaving actual recesses instead of putting
# blue boxes over grass. A separate grass patch fills each deselected pool.
nx, ny = min(100, max(2, math.ceil(width/.3))), min(100, max(2, math.ceil(length/.3)))
xs = sorted(set([width*i/nx for i in range(nx+1)] + [max(0,min(width,v)) for h in holes for v in (h[0],h[2])]))
ys = sorted(set([length*i/ny for i in range(ny+1)] + [max(0,min(length,v)) for h in holes for v in (h[1],h[3])]))
ground = ground_mesh('Yard ground', xs, ys, True)
ground['yard_width_m'], ground['yard_length_m'] = width, length
extent=max(width,length,12)*5
neighbor=ground_mesh('Neighboring lawn',[-extent,0,width,width+extent],[-extent,0,length,length+extent])
neighbor['environment_geometry']=True
for o, (x,y,xx,yy) in zip(pools, holes):
    if o['element_id']:
        patch = ground_mesh('Pool grass fill', [x+(xx-x)*i/8 for i in range(9)], [y+(yy-y)*i/8 for i in range(9)])
        patch['fill_for'] = o['element_id']

for item in data['objects']:
    kind = item['asset']
    w,l,h = item['width']*FT,item['length']*FT,item['height']*FT
    group = bpy.data.objects.new(item['name'], None)
    bpy.context.collection.objects.link(group)
    group.location = (item['x']*FT, item['y']*FT, 0)
    group['existing_feature'] = item['static']
    group['element_id'] = item['element_id']
    group['instance'] = item['instance']
    group['asset_kind'] = kind
    # XZ collision bounds in browser coordinates; Y in Blender becomes -Z.
    group['collider'] = [item['x']*FT, -(item['y']+item['length'])*FT,
                         (item['x']+item['width'])*FT, -item['y']*FT]
    if 'light' in kind:
        part(group,'Light post',(w/2,l/2,.23),(.028,.028,.46),'Metal','cylinder')
        part(group,'Lamp glow',(w/2,l/2,.48),(.065,.065,.07),'Lamp','cylinder')
        part(group,'Lamp shade',(w/2,l/2,.53),(.14,.14,.04),'Metal','cylinder')
    elif 'fence' in kind:
        along_x = w >= l
        run = w if along_x else l
        thickness = max(.045, l if along_x else w)
        def fence_part(name, distance, z, size, mat='Cedar'):
            a,b,c = size
            return part(group,name,(distance if along_x else thickness/2, thickness/2 if along_x else distance,z),
                        (a,b,c) if along_x else (b,a,c),mat)
        count = min(1500, max(1, math.ceil(run/.145)))
        pitch = run/count
        for i in range(count):
            fence_part('Fence picket',(i+.5)*pitch,h/2,(pitch*.9,.025,h))
        posts = min(200, max(1, math.ceil(run/1.8)))
        for i in range(posts+1):
            fence_part('Fence post',.05+i*(run-.10)/posts,h/2,(.10,.10,h+.06))
        for z in (.25,h-.30):
            fence_part('Fence rail',run/2,z,(run,.065,.09))
    elif kind == 'planter':
        pot_h = min(.65,h*.7)
        part(group,'Tapered planter walls',(w/2,l/2,pot_h/2),(w,l,pot_h),'Terracotta','hollow_planter')
        part(group,'Planter soil',(w/2,l/2,pot_h*.82),(w*.78,l*.78,.035),'Soil')
        for i in range(5):
            x,y=w*(.23+(i%3)*.26),l*(.3+(i%2)*.35)
            beam(group,'Plant stem',(x,y,pot_h*.82),(x,y,pot_h+.28),.012,'Leaves')
            for j in range(6):
                angle=j*math.tau/6
                leaf=part(group,'Planter leaf',(x+.07*math.cos(angle),y+.07*math.sin(angle),pot_h+.08+j*.03),(.08,.19,.08),'Leaves','leaf')
                leaf.rotation_euler=(.4,0,angle)
    elif kind in ('tree','plant'):
        tree(group,w,l,h,item['instance'],kind=='plant')
        if kind == 'tree':
            trunk=min(.24,w*.13,l*.13)
            x,y = (item['x']+item['width']/2)*FT, -(item['y']+item['length']/2)*FT
            group['collider'] = [x-trunk/2,y-trunk/2,x+trunk/2,y+trunk/2]
    elif 'pool' in kind:
        depth,edge = 1.2, min(.18,w/8,l/8)
        part(group,'Pool bottom',(w/2,l/2,-depth),(w,l,.1),'Pool lining')
        for x in (edge/2,w-edge/2):
            part(group,'Pool wall',(x,l/2,-depth/2),(edge,l,depth),'Pool lining')
            part(group,'Pool coping',(x,l/2,.04),(edge,l,.10),'Coping')
        for y in (edge/2,l-edge/2):
            part(group,'Pool wall',(w/2,y,-depth/2),(w,edge,depth),'Pool lining')
            part(group,'Pool coping',(w/2,y,.04),(w,edge,.10),'Coping')
        part(group,'Pool water',(w/2,l/2,-.14),(w-edge*2,l-edge*2,.02),'Water')
    elif kind == 'deck':
        deck_h=.45
        group['walk_surface']=deck_h
        # Deck rails remain collidable; a stair-width opening is left at front.
        del group['collider']
        group['rail_colliders']=[[item['x']*FT,-(item['y']+item['length'])*FT,item['x']*FT+.09,-item['y']*FT],
            [(item['x']+item['width'])*FT-.09,-(item['y']+item['length'])*FT,(item['x']+item['width'])*FT,-item['y']*FT],
            [item['x']*FT,-(item['y']+item['length'])*FT,(item['x']+item['width'])*FT,-(item['y']+item['length'])*FT+.09]]
        for xx in (.06,w-.06):
            for yy in (.3,l-.08):
                part(group,'Deck support post',(xx,yy,deck_h/2),(.10,.10,deck_h),'Cedar')
        count=min(150,max(2,math.ceil(w/.14)))
        for i in range(count):
            part(group,'Deck board',((i+.5)*w/count,l*.56,deck_h-.025),(w/count*.97,l*.88,.05),'Cedar')
        for side in ('left','right','back'):
            run=l*.88 if side!='back' else w
            n=max(2,min(150,math.ceil(run/.14)))
            for i in range(n):
                x=(.045 if side=='left' else w-.045) if side!='back' else (i+.5)*w/n
                y=l*.12+(i+.5)*l*.88/n if side!='back' else l-.045
                part(group,'Deck baluster',(x,y,deck_h+.45),(.035,.035,.9),'Cedar')
            part(group,'Deck handrail',(.045 if side=='left' else w-.045 if side=='right' else w/2,l*.56 if side!='back' else l-.045,deck_h+.92),
                 (.08,l*.88,.07) if side!='back' else (w,.08,.07),'Cedar')
        for i in range(3):
            part(group,'Deck step',(w/2,l*.02+i*l*.035,(i+1)*.15/2),(min(w*.7,1.2),l*.04,(i+1)*.15),'Cedar')
    elif kind == 'patio':
        group['walk_surface'] = .055
        del group['collider']
        part(group,'Paver grout',(w/2,l/2,.015),(w,l,.03),'Grout')
        cols, rows = min(70,max(1,math.ceil(w/.5))), min(70,max(1,math.ceil(l/.5)))
        for j in range(rows):
            for i in range(cols):
                part(group,'Patio paver',((i+.5)*w/cols,(j+.5)*l/rows,.04),
                     (w/cols*.975,l/rows*.975,.03),'Paver')
    elif 'shed' in kind:
        part(group,'Shed walls',(w/2,l/2,h*.45),(w*.91,l*.93,h*.9),'Cedar')
        # Roof eaves fit inside the reserved footprint. Ridge slopes meet.
        rise=min(w*.20,.6)
        angle=math.atan2(rise,w/2)
        for side in (-1,1):
            roof = part(group,'Shed pitched roof',(w*(.25 if side<0 else .75),l/2,h*.9+rise/2),(math.hypot(w/2,rise),l,.06),'Roof')
            roof.rotation_euler[1] = side*angle
        gable=bpy.data.meshes.new('Shed gable')
        gable.from_pydata([(w*.045,0,h*.9),(w*.955,0,h*.9),(w/2,0,h*.9+rise*.91)],[],[(0,1,2)])
        gable.materials.append(mats['Cedar'])
        for y in (l*.035,l*.965):
            end=bpy.data.objects.new('Shed gable end',gable);bpy.context.collection.objects.link(end);end.parent=group;end.location.y=y
        part(group,'Shed door',(w/2,l*.032,h*.4),(min(w*.4,.9),.045,h*.8),'Bark')
        part(group,'Shed door handle',(w*.64,l*.016,h*.42),(.025,.03,.13),'Steel')
        part(group,'Shed window trim',(w*.19,l*.023,h*.63),(w*.2,.03,h*.25),'Cedar')
        part(group,'Shed window',(w*.19,l*.014,h*.63),(w*.17,.012,h*.22),'Glass')
    elif kind == 'chair':
        chair(group,0,0,w,l)
    elif kind == 'table':
        table(group,0,0,w,l,h)
    elif kind == 'dining_set':
        table(group,w*.3,l*.3,w*.4,l*.4,.76)
        chair(group,w*.36,.02,w*.28,l*.26)
        rear=bpy.data.objects.new('Dining chair rear',None);bpy.context.collection.objects.link(rear);rear.parent=group
        rear.location=(w*.64,l-.02,0);rear.rotation_euler[2]=math.pi
        chair(rear,0,0,w*.28,l*.26)
    elif kind == 'bar':
        counter_l=min(.78,l*.48)
        cabinet_y=l-counter_l*.55-.05
        part(group,'Bar base cabinet',(w/2,cabinet_y,(h-.08)/2),(w-.18,counter_l-.15,h-.08),'Cedar')
        part(group,'Overhanging bar top',(w/2,cabinet_y,h-.035),(w,counter_l,.07),'Concrete')
        for i in range(4):
            part(group,'Bar cabinet door',((i+.5)*(w-.2)/4+.1,cabinet_y-counter_l*.5+.055,h*.45),((w-.2)/4-.025,.025,h*.75),'Cedar')
            part(group,'Cabinet pull',((i+.75)*(w-.2)/4+.1,cabinet_y-counter_l*.5+.035,h*.62),(.06,.018,.02),'Steel')
        beam(group,'Bar foot rail',(.10,cabinet_y-counter_l*.5-.1,.20),(w-.10,cabinet_y-counter_l*.5-.1,.20),.035,'Steel')
        stools=3 if w>=2.1 else 2
        for i in range(stools):
            stool_w=min(.44,w/(stools+1))
            chair(group,(i+.5)*w/stools-stool_w/2,.06,stool_w,.44,.76,True)
    elif kind == 'grill':
        body_w=w*.58; body_y=l*.53
        for xx in (w*.24,w*.76):
            for yy in (l*.23,l*.78):
                part(group,'Grill cart leg',(xx,yy,.40),(.045,.045,.80),'Metal')
                wheel=part(group,'Grill wheel',(xx,yy,.10),(.14,.05,.14),'Metal','cylinder')
                wheel.rotation_euler[0]=math.pi/2
        part(group,'Grill lower shelf',(w/2,body_y,.23),(body_w,l*.60,.035),'Steel')
        part(group,'Grill cook box',(w/2,body_y,.84),(body_w,l*.62,.18),'Metal')
        lid=part(group,'Grill rounded lid',(w/2,body_y,1.04),(body_w,l*.64,.35),'Metal','sphere')
        beam(group,'Grill lid handle',(w*.33,l*.17,1.03),(w*.67,l*.17,1.03),.03,'Steel')
        for xx in (w*.10,w*.90):
            part(group,'Grill side shelf',(xx,body_y,.85),(w*.19,l*.58,.035),'Steel')
        for i in range(4):
            knob=part(group,'Grill control knob',(w*(.34+i*.105),l*.20,.82),(.035,.035,.028),'Steel','cylinder')
            knob.rotation_euler[0]=math.pi/2
    elif kind == 'fire_pit':
        part(group,'Fire pit base',(w/2,l/2,h*.3),(w*.9,l*.9,h*.6),'Concrete','cylinder')
        part(group,'Fire pit bowl',(w/2,l/2,h*.7),(w,l,h*.35),'Metal','cylinder')
        part(group,'Fire pit fuel',(w/2,l/2,h*.9),(w*.75,l*.75,.025),'Soil','cylinder')
    elif kind == 'pergola':
        for xx in (.08,w-.08):
            for yy in (.08,l-.08):
                part(group,'Pergola post',(xx,yy,1.2),(.12,.12,2.4),'Cedar')
        for i in range(8):
            part(group,'Pergola rafter',((i+.5)*w/8,l/2,2.4),(.08,l,.15),'Cedar')
        for yy in (.08,l-.08):
            part(group,'Pergola beam',(w/2,yy,2.28),(w,.13,.15),'Cedar')
    else:
        # An explicit fitted composite for an unrecognized site feature.
        part(group,'Feature plinth',(w/2,l/2,.08),(w,l,.16),'Concrete')
        part(group,'Feature frame',(w/2,l/2,h/2),(w*.92,l*.92,h*.85),'Cedar')
        part(group,'Feature cap',(w/2,l/2,h),(w,l,.06),'Concrete')

    # Audit the REAL generated vertices (eaves, leaves and handles included),
    # then fit any small protrusions within the envelope the packing pass used.
    # This is independent of the primitive's nominal dimensions or origin.
    bpy.context.view_layer.update()
    points=[child.matrix_local @ vertex.co for child in group.children if child.type=='MESH' for vertex in child.data.vertices]
    if points:
        lo=[min(p[i] for p in points) for i in range(2)]
        hi=[max(p[i] for p in points) for i in range(2)]
        for axis,size in enumerate((w,l)):
            if lo[axis]<-1e-5 or hi[axis]>size+1e-5:
                factor=min(1,size/(hi[axis]-lo[axis]))
                offset=-lo[axis]*factor if lo[axis]<0 else min(0,size-hi[axis]*factor)
                # An empty carrier transforms all components together, including
                # rotated branches. Their relative construction stays intact.
                carrier=bpy.data.objects.new('Envelope fit',None)
                bpy.context.collection.objects.link(carrier)
                carrier.parent=group
                for child in list(group.children):
                    if child!=carrier: child.parent=carrier
                carrier.scale[axis]=factor
                carrier.location[axis]=offset
    bpy.context.view_layer.update()
    inverse=group.matrix_world.inverted()
    actual=[inverse @ child.matrix_world @ vertex.co for child in group.children_recursive if child.type=='MESH' for vertex in child.data.vertices]
    if actual:
        limits=[min(p.x for p in actual),min(p.y for p in actual),max(p.x for p in actual),max(p.y for p in actual)]
        if limits[0]<-.002 or limits[1]<-.002 or limits[2]>w+.002 or limits[3]>l+.002:
            raise RuntimeError('Generated composite escaped its collision envelope: '+item['name'])
        group['geometry_bounds_ft']=[item['x']+limits[0]/FT,item['y']+limits[1]/FT,item['x']+limits[2]/FT,item['y']+limits[3]/FT]

# Context only: a distant grove outside the fence, never included in purchasing
# or collision bounds. Shared leaf/branch geometry remains instanceable.
background=bpy.data.objects.new('Distant tree grove',None)
bpy.context.collection.objects.link(background)
background['environment_geometry']=True
rng=random.Random(742)
for i in range(20):
    angle=i*math.tau/20
    radius=max(width,length)*1.4+10+rng.random()*8
    grove=bpy.data.objects.new('Neighbor tree',None)
    bpy.context.collection.objects.link(grove)
    grove.parent=background
    grove.location=(width/2+math.cos(angle)*radius,length/2+math.sin(angle)*radius,-.05)
    tree(grove,3.5,3.5,5+rng.random()*4,i,True)

bpy.ops.export_scene.gltf(filepath=str(root / 'yard.glb'), export_format='GLB', export_extras=True)
