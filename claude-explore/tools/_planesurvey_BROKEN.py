"""BROKEN -- DO NOT TRUST. Kept only so the next attempt does not repeat it.

Intent: ask which SLIC planes the APPLICATION actually applied, by evaluating
n.p + d over the app's own vertices for that solid.
    all >= 0  -> applied, positive side kept
    all <= 0  -> applied, negative side kept
    mixed     -> not applied

THE CONTROL FAILS. `Computer Desk` matches the app 12/12 exactly with clipping
ON, so its planes are demonstrably applied -- and this reports 100% "not
applied" for it. Any conclusion drawn from it is worthless, including the
tempting "Brutus ignores 90% of its planes".

Four fixes attempted, none of which moved the control:
  1. pair on clipped rather than unclipped solids     (pairing was not the fault)
  2. apply the object's UNIT scale                    (unit_scale is None here)
  3. verify the world spaces agree                    (they do, exactly:
     collect, hand-rolled POSN@local and the app all give [48, 30, 54.4])
  4. use wrlfit.align instead of a hardcoded perm/sign (moved Brutus 90%->67%,
     left the control at 100%)

Our own clipped geometry passes its own planes cleanly (s from 0 upward), so the
plane data and the clipper are fine; the fault is somewhere in mapping the app's
vertices into the prism's object space. Next idea: stop going through POSN
inverse entirely -- compare our clipped solid to the app's solid directly as
point clouds (nearest-point / Hausdorff), which needs no space inversion.
"""

import sys, os, glob, collections
sys.path.insert(0, os.path.expanduser('~/mnt/DesignIt-3D-File-Loader/claude-explore/tools'))
os.chdir(os.path.expanduser('~/mnt/DesignIt-3D-File-Loader'))
import numpy as np, iff, wlb, d3d, wrlfit
PERM, S = (0, 2, 1), np.array([1., -1., 1.])

def clip_item(item, wrl):
    prisms = []
    def walk(n):
        for k in n.children:
            if k.tag == 'PRSM': prisms.append(k)
            if k.tag in ('PRSM', 'PGRP'): walk(k)
    walk(item)
    app = [v/0.0254 for v in wrlfit.parse_wrl(wrl)]
    # Pair on the CLIPPED solids -- those are the ones whose centres match the
    # app. Pairing on unclipped solids mismatches them and the plane test then
    # reports nonsense: `Computer Desk` matches the app 12/12 with clipping ON,
    # yet came out "100% of planes not applied".
    # The object's UNIT scale. collect() applies it; a hand-rolled POSN @ local
    # does NOT, and that mismatch is what made this test report that `Computer
    # Desk` ignores planes it demonstrably respects.
    U = d3d.unit_scale(item) or 1.0
    ours = []
    for k in prisms:
        d3d.SLIC_MODE = 'clip'
        mc = d3d.prsm_mesh(k)
        if mc is None or not len(mc[0]): continue
        ps = k.kid('POSN')
        M = d3d.posn_matrix(ps)[0] if ps is not None else np.eye(4)
        vh = np.hstack([mc[0], np.ones((len(mc[0]), 1))])
        ours.append((k, (M @ vh.T).T[:, :3] * U, M, U))
    if not ours or not app: return None
    # Use the SAME alignment wrlfit computes -- hardcoding perm/signs here was
    # the bug: a wrong sign mirrors an axis, every plane with a component on it
    # comes out straddled, and the test reports "not applied" for planes the
    # object demonstrably respects.
    got = wrlfit.align(app, [V for _, V, _, _ in ours])
    if got is None: return None
    _, PERM_, S_, t = got
    xf = lambda V: V[:, PERM_]*S_ + t
    cnt = collections.Counter()
    for k, V, M, U in ours:
        c = (V.max(0)+V.min(0))/2
        bA = min(app, key=lambda A: np.linalg.norm(c - (xf(A).max(0)+xf(A).min(0))/2))
        Ax = xf(bA)
        obj = (np.linalg.inv(M) @ np.hstack([Ax / U, np.ones((len(Ax),1))]).T).T[:, :3]
        sl = k.kid('SLIC')
        n = iff.u16(sl.data, 0) if sl is not None and len(sl.data) >= 2 else 0
        for i in range(n):
            o = 2 + i*16
            nn = np.array([iff.fp(sl.data, o), iff.fp(sl.data, o+4), iff.fp(sl.data, o+8)])
            dd = iff.fp(sl.data, o+12)
            if not np.any(np.abs(nn) > 1e-9): continue
            s = obj @ nn + dd
            tol = 0.02*max(1.0, np.abs(s).max())
            if s.min() >= -tol: cnt['applied+'] += 1
            elif s.max() <= tol: cnt['applied-'] += 1
            else: cnt['NOT'] += 1
    return cnt

def gal(sub):
    for p in sorted(glob.glob('data/galleries3d/*.WLB')):
        if os.path.basename(p).startswith('ID'): continue
        for name, it in wlb.items(p):
            if sub in name.lower(): return it
E = 'D3D/2026_New_Exports/WRL Exports'
for label, item, wrl in [
    ('Brutus de Milo', gal('brutus de milo'), f'{E}/BrutusDeMilo.WRL'),
    ('Bar Sink',       gal('bar sink'),       f'{E}/BarSink.WRL'),
    ('Computer Desk',  gal('computer desk'),  f'{E}/ComputerDesk.WRL'),
    ('Tractor',        gal('tractor'),        f'{E}/FarmTractor.WRL'),
    ('Printer w/stand',gal('printer w/stand'),f'{E}/Printer with Stand.WRL'),
]:
    if item is None: print(f'{label}: not found'); continue
    c = clip_item(item, wrl)
    tot = sum(c.values()) if c else 0
    if not tot: print(f'{label}: no planes'); continue
    print(f'{label:18s} planes {tot:4d}   applied+ {c["applied+"]:4d}  applied- {c["applied-"]:3d}  '
          f'NOT applied {c["NOT"]:4d}  ({100*c["NOT"]/tot:.0f}%)')
