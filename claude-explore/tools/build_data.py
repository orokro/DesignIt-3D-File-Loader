"""Assemble every source file into one deduplicated `data/` tree + manifest.

Sources are copied, never moved -- the original D3D/ tree is left untouched.
Identical files that ship with both applications are stored once and the
manifest lists every place they came from.
"""
import os, sys, json, shutil, hashlib, collections
sys.path.insert(0, os.path.dirname(__file__))
import iff, d3d, wlb
import numpy as np

SRC = '..'
DST = '../data'

# where each source directory lands, and what it holds
ROUTES = [
    ('2026_New_Exports/DESIGNIT/SCENES',   'scenes',      'designit'),
    ('2026_New_Exports/KESIGN3D/SCENES',   'scenes',      'kesign3d'),
    ('2026_New_Exports/DESIGNIT/MODELS',   'models',      'designit'),
    ('2026_New_Exports/KESIGN3D/MODELS',   'models',      'kesign3d'),
    ('2026_New_Exports/DESIGNIT/3GALLERY', 'galleries3d', 'designit'),
    ('2026_New_Exports/KESIGN3D/3GALLERY', 'galleries3d', 'kesign3d'),
    ('2026_New_Exports/DESIGNIT/2GALLERY', 'galleries2d', 'designit'),
    ('2026_New_Exports/KESIGN3D/2GALLERY', 'galleries2d', 'kesign3d'),
    ('2026_New_Exports/KESIGN3D/BTEXTURE', 'textures',    'kesign3d'),
    ('2026_New_Exports/KESIGN3D/TEXTURES', 'textures',    'kesign3d'),
    ('2026_New_Exports/DESIGNIT/G',        'misc',        'designit'),
    ('MiscVVR',                            'misc',        'designit'),
    # Virtus VRML -- the same engine one product generation later, and the only
    # build in which textures actually render. Its content is largely NEW:
    # the Archaeology and Cyberspace/Temple/Corporate model sets, the Dealey
    # Plaza and Hindenburg scenes, and 31 texture libraries.
    ('2026_New_Exports/VirVRML/2GALLERY',        'galleries2d', 'virvrml'),
    ('2026_New_Exports/VirVRML/3GALLERY',        'galleries3d', 'virvrml'),
    ('2026_New_Exports/VirVRML/Scenes',          'scenes',      'virvrml'),
    ('2026_New_Exports/VirVRML/Archlogy/ARCHSCN', 'scenes',     'virvrml'),
    ('2026_New_Exports/VirVRML/Homerem/HOMESCN', 'scenes',      'virvrml'),
    ('2026_New_Exports/VirVRML/Homerem/HOMEMOD', 'scenes',      'virvrml'),
    ('2026_New_Exports/VirVRML/Models/Corp',     'models',      'virvrml'),
    ('2026_New_Exports/VirVRML/Models/Cspace',   'models',      'virvrml'),
    ('2026_New_Exports/VirVRML/Models/Cspace/Library', 'models', 'virvrml'),
    ('2026_New_Exports/VirVRML/Models/Cspace/Logon',   'models', 'virvrml'),
    ('2026_New_Exports/VirVRML/Models/Temple',   'models',      'virvrml'),
    ('2026_New_Exports/VirVRML/Tutorial',        'misc',        'virvrml'),
    ('2026_New_Exports/VirVRML/Tutorial/WRLS',   'misc',        'virvrml'),
    ('2026_New_Exports/VirVRML/Textures',           'textures', 'virvrml'),
    ('2026_New_Exports/VirVRML/Archlogy/Textures',  'textures', 'virvrml'),
    ('2026_New_Exports/VirVRML/Homerem/Textures',   'textures', 'virvrml'),
    ('2026_New_Exports/VirVRML/BTexture/Art',       'textures', 'virvrml'),
    ('2026_New_Exports/VirVRML/BTexture/Metal',     'textures', 'virvrml'),
    ('2026_New_Exports/VirVRML/BTexture/Nature',    'textures', 'virvrml'),
    ('2026_New_Exports/VirVRML/BTexture/Pattern',   'textures', 'virvrml'),
    ('2026_New_Exports/VirVRML/BTexture/Stone',     'textures', 'virvrml'),
    ('2026_New_Exports/VirVRML/BTexture/Wood',      'textures', 'virvrml'),
]
EXTS = ('.VVR', '.WLB', '.TLB')


def md5(p):
    with open(p, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def collect_sources():
    by_hash = collections.OrderedDict()
    for sub, bucket, app in ROUTES:
        d = os.path.join(SRC, 'D3D', sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.upper().endswith(EXTS):
                continue
            p = os.path.join(d, f)
            h = md5(p)
            e = by_hash.setdefault(h, {'bucket': bucket, 'name': f, 'apps': [], 'sources': [], 'size': os.path.getsize(p)})
            if app not in e['apps']:
                e['apps'].append(app)
            e['sources'].append(os.path.relpath(p, SRC).replace('\\', '/'))
    # the user's own single-object exports, kept per gallery
    a = os.path.join(SRC, 'D3D', '2026_New_Exports', 'A')
    for g in sorted(os.listdir(a)) if os.path.isdir(a) else []:
        gd = os.path.join(a, g)
        if not os.path.isdir(gd):
            continue
        for f in sorted(os.listdir(gd)):
            p = os.path.join(gd, f)
            if f.upper().endswith(EXTS + ('.PNG',)):
                h = md5(p)
                e = by_hash.setdefault(h, {'bucket': 'exports/' + g, 'name': f, 'apps': ['designit'],
                                           'sources': [], 'size': os.path.getsize(p)})
                e['sources'].append(os.path.relpath(p, SRC).replace('\\', '/'))
    # loose test files at the repo root
    for f in sorted(os.listdir(SRC)):
        if f.upper().endswith(EXTS):
            p = os.path.join(SRC, f)
            h = md5(p)
            e = by_hash.setdefault(h, {'bucket': 'misc', 'name': f, 'apps': ['designit'],
                                       'sources': [], 'size': os.path.getsize(p)})
            e['sources'].append(f)
    return by_hash


def prism_stats(node):
    prisms = node.find_all('PRSM')
    prof = collections.Counter()
    slic = surf = feat = 0
    for p in prisms:
        po = p.kid('POLY')
        if po and len(po.data) >= 32:
            prof[d3d.PROFILE_NAME.get(d3d.Poly(po).profile, '?')] += 1
        s = p.kid('SLIC')
        if s and len(s.data) > 2:
            slic += 1
        for sf in p.kids('SURF'):
            surf += 1
            feat += len(sf.kids('FEAT'))
    return {'prisms': len(prisms), 'groups': len(node.find_all('PGRP')),
            'profiles': dict(prof), 'slicedPrisms': slic,
            'decoratedFaces': surf, 'features': feat}


def scene_bbox(path):
    try:
        ms = d3d.scene_meshes(path)
    except Exception:
        return None
    ms = [m for m in ms if len(m[0])]
    if not ms:
        return None
    v = np.vstack([m[0] for m in ms])
    return {'min': [round(float(x), 2) for x in v.min(0)],
            'max': [round(float(x), 2) for x in v.max(0)],
            'meshes': len(ms),
            'triangles': int(sum(len(m[1]) for m in ms))}


def main(do_bbox=True):
    by_hash = collect_sources()
    entries = []
    for h, e in by_hash.items():
        outdir = os.path.join(DST, e['bucket'])
        os.makedirs(outdir, exist_ok=True)
        name = e['name']
        dest = os.path.join(outdir, name)
        # same filename, different content -> disambiguate by app
        if os.path.exists(dest) and md5(dest) != h:
            stem, ext = os.path.splitext(name)
            name = f'{stem}__{e["apps"][0]}{ext}'
            dest = os.path.join(outdir, name)
        shutil.copy2(os.path.join(SRC, e['sources'][0]), dest)
        rec = {'path': os.path.relpath(dest, DST).replace('\\', '/'),
               'bucket': e['bucket'], 'apps': e['apps'], 'bytes': e['size'],
               'sources': e['sources']}
        up = name.upper()
        try:
            if up.endswith('.WLB'):
                clips = []
                for cname, it in wlb.items(dest):
                    st = prism_stats(it)
                    st['name'] = cname
                    st['kind'] = it.subtype
                    clips.append(st)
                rec['clips'] = clips
                rec['clipCount'] = len(clips)
            elif up.endswith(('.VVR', '.TLB')):
                r = iff.load(dest)
                rec.update(prism_stats(r))
                if do_bbox and up.endswith('.VVR'):
                    bb = scene_bbox(dest)
                    if bb:
                        rec['bounds'] = bb
        except Exception as ex:
            rec['parseError'] = f'{type(ex).__name__}: {ex}'
        entries.append(rec)
    entries.sort(key=lambda r: (r['bucket'], r['path']))
    man = {
        'generatedBy': 'claude-explore/tools/build_data.py',
        'units': 'inch', 'upAxis': 'Z',
        'buckets': {
            'scenes': 'complete .VVR scenes shipped with the applications',
            'models': 'single-subject .VVR models shipped with the applications',
            'galleries3d': '.WLB libraries of 3D objects (PRSM clips)',
            'galleries2d': '.WLB libraries of 2D surface features (FEAT clips)',
            'textures': '.TLB texture libraries (Key Design 3-D only)',
            'exports': "the user's own single-object .VVR exports, one folder per gallery, with the app screenshot",
            'misc': 'loose test and probe files',
        },
        'fileCount': len(entries),
        'files': entries,
    }
    os.makedirs(DST, exist_ok=True)
    with open(os.path.join(DST, 'manifest.json'), 'w') as f:
        json.dump(man, f, indent=1)
    return man


if __name__ == '__main__':
    m = main(do_bbox='--nobbox' not in sys.argv)
    print(f"{m['fileCount']} files written to data/")
