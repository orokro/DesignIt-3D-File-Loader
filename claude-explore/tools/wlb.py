import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import iff

def items(path):
    r = iff.load(path)
    out = []
    for cat in r.children:
        for it in cat.children:
            if it.tag != 'FORM' or it.formtype != 'VCLP':
                continue
            nm = it.kid('NAME')
            name = iff.pstring(nm.data, 0)[0] if nm else '?'
            out.append((name, it))
    return out

def brief(prsm, depth=0):
    ind = '  ' * depth
    po = prsm.kid('POLY')
    if po:
        b = po.data
        n = iff.u32(b, 28)
        v = [(round(iff.fp(b,32+i*8),3), round(iff.fp(b,36+i*8),3)) for i in range(n)]
        z0, z1 = iff.fp(b,6), iff.fp(b,10)
        hdr = ' '.join(f'{x:02x}' for x in b[0:6])
        print(f'{ind}POLY [{hdr}] z=({z0:g},{z1:g}) n={n} {v[:4]}{"…" if n>4 else ""}')
    ps = prsm.kid('POSN')
    if ps:
        P = [round(iff.fp(ps.data,i*4),4) for i in range(12)]
        print(f'{ind}POSN pos={P[0:3]} rot={P[3:6]} mid={P[6:9]} scl={P[9:12]}')
    c = prsm.kid('COLR')
    if c: print(f'{ind}COLR {c.data.hex(" ")}')
    for k in prsm.children:
        if k.tag in ('PRSM','PGRP'):
            print(f'{ind}> {k.tag}')
            brief(k, depth+1)
        elif k.tag in ('SLIC','ESLC','SURF','PLGR','CONN','PLTX'):
            print(f'{ind}. {k.tag} {len(k.data)} {k.data[:24].hex(" ")}')

if __name__ == '__main__':
    for name, it in items(sys.argv[1]):
        if len(sys.argv) > 2 and sys.argv[2].lower() not in name.lower():
            continue
        print(f'=== {name}   [{it.subtype}]  chunks={[c.tag for c in it.children]}')
        for k in it.children:
            if k.tag in ('PRSM','PGRP'):
                brief(k, 1)
        print()
