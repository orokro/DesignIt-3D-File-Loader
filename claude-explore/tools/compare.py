"""Side-by-side: the app's own VRIF preview vs our reconstructed geometry.

VRIF previews are 50x50 front elevations, so we render orthographically from
the same direction (looking along +Y with Z up).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from PIL import Image, ImageDraw
import wlb, vrif, d3d, render


def compare(path, filt=None, cols=6, scale=3, azim=-90.0, elev=0.0, out='out/cmp.png'):
    rows = []
    for name, it in wlb.items(path):
        if filt and filt.lower() not in name.lower():
            continue
        prev = vrif.decode(it.kid('VRIF').data) if it.kid('VRIF') else None
        ms = []
        d3d.collect(it, np.eye(4), ms)
        rows.append((name, prev, ms))
    S = 50 * scale
    n = len(rows)
    ncol = min(cols, max(1, n))
    nrow = (n + ncol - 1) // ncol
    W, H = S * 2 + 8, S + 16
    sheet = Image.new('RGB', (W * ncol, H * nrow), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, (name, prev, ms) in enumerate(rows):
        r, c = divmod(i, ncol)
        x0, y0 = c * W, r * H
        if prev:
            sheet.paste(prev.resize((S, S), Image.NEAREST), (x0, y0))
        if ms:
            im = render.render(ms, size=(S, S), azim=azim, elev=elev, ortho=True)
            sheet.paste(im, (x0 + S + 8, y0))
        d.text((x0 + 2, y0 + S + 2), name[:34], fill=(0, 0, 0))
    sheet.save(out)
    return out, len(rows)


if __name__ == '__main__':
    a = dict(x.split('=') for x in sys.argv[2:] if '=' in x)
    print(compare(sys.argv[1], filt=a.get('filt'), cols=int(a.get('cols', 6)),
                  out=a.get('out', 'out/cmp.png'),
                  azim=float(a.get('azim', -90)), elev=float(a.get('elev', 0))))
