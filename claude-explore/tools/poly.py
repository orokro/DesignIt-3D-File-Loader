import sys, os, glob
sys.path.insert(0, os.path.dirname(__file__))
import iff

def show(path):
    r = iff.load(path)
    for prsm in r.find_all('PRSM'):
        po = prsm.kid('POLY')
        if not po: continue
        b = po.data
        n = iff.u32(b, 28)
        verts = [(iff.fp(b, 32+i*8), iff.fp(b, 36+i*8)) for i in range(n)]
        head = ' '.join(f'{x:02x}' for x in b[0:6])
        f6, f10 = iff.fp(b, 6), iff.fp(b, 10)
        mid = ' '.join(f'{x:02x}' for x in b[14:28])
        po_ = prsm.kid('POSN'); P = [iff.fp(po_.data, i*4) for i in range(12)]
        name = os.path.basename(path).replace('.VVR','')
        print(f'{name:22} hdr[{head}] b6={f6:8.3f} b10={f10:8.3f} n={n:2} '
              f'len={len(b):3} mid={mid}')
        print(f'{"":22} verts={[(round(x,3),round(y,3)) for x,y in verts][:6]}')
        print(f'{"":22} POSN pos={[round(v,3) for v in P[0:3]]} rot={[round(v,4) for v in P[3:6]]} '
              f'mid={[round(v,4) for v in P[6:9]]} scl={[round(v,4) for v in P[9:12]]}')
        c = prsm.kid('COLR')
        if c: print(f'{"":22} COLR={c.data.hex(" ")}  extra={[k.tag for k in prsm.children]}')
        print()

for p in sys.argv[1:]:
    for f in sorted(glob.glob(p)):
        show(f)
