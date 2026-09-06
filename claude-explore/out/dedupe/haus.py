import json, collections, numpy as np, os, itertools
os.chdir(os.path.join(os.environ['HOME'],'dd'))
clips=json.load(open('clips.json'))
Z=np.load('verts.npz'); V={}
for k in Z.files:
    f,i=k.rsplit('|',1); V[(f,int(i))]=Z[k]
recs=[r for r in clips if 'exact' in r]
for r in recs: r['V']=V[(r['file'],r['idx'])]

def forms(A):
    out=[]
    for m in (0,1):
        B0=A.copy()
        if m: B0[:,0]=-B0[:,0]
        for rot in range(4):
            B=B0.copy()
            for _ in range(rot): B=np.column_stack([-B[:,1],B[:,0],B[:,2]])
            out.append((B-B.min(0), rot, m))
    return out

def hausdorff(A,B):
    d=np.abs(A[:,None,:]-B[None,:,:]).max(2)      # Chebyshev
    return max(d.min(1).max(), d.min(0).max())

TOL=0.30
buck=collections.defaultdict(list)
for r in recs: buck[(r['tris'], r['meshes'])].append(r)
same=[]; mirror=[]
for k,v in sorted(buck.items()):
    if len(v)<2: continue
    if len(v)>60: continue
    for a,b in itertools.combinations(v,2):
        if a['exact']==b['exact']: continue
        if abs(a['area']-b['area'])>max(2.0,0.002*a['area']): continue
        best=None
        for B,rot,m in forms(b['V']):
            if len(a['V'])!=len(B): continue
            d=hausdorff(a['V'],B)
            if best is None or d<best[0]: best=(d,rot,m)
        if best and best[0]<=TOL:
            (same if not best[2] else mirror).append((a,b,best))
print(f'--- congruent pairs (same shape up to translation/90° rotation), tol {TOL}" ---')
for a,b,(d,rot,m) in same:
    print(f'  {a["path"].replace("galleries3d/",""):46} == {b["path"].replace("galleries3d/",""):46} rot={rot*90}')
print(f'  total {len(same)}')
print(f'\n--- MIRRORED pairs (left/right handed variants -- NOT duplicates) ---')
for a,b,(d,rot,m) in mirror:
    print(f'  {a["path"].replace("galleries3d/",""):46} <M> {b["path"].replace("galleries3d/",""):46} rot={rot*90}')
print(f'  total {len(mirror)}')
json.dump({'same':[[a['path'],b['path'],p[1]*90] for a,b,p in same],
           'mirror':[[a['path'],b['path'],p[1]*90] for a,b,p in mirror]}, open('congruent.json','w'))
