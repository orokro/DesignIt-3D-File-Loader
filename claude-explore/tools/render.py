"""Tiny z-buffered flat-shaded software renderer (numpy + PIL). Z is up."""
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from PIL import Image, ImageDraw
import d3d

BG = (235, 240, 248)

def look_at(eye, target, up=(0, 0, 1)):
    eye = np.array(eye, float); target = np.array(target, float); up = np.array(up, float)
    f = target - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s)
    u = np.cross(s, f)
    M = np.eye(4)
    M[0, :3], M[1, :3], M[2, :3] = s, u, -f
    M[:3, 3] = -M[:3, :3] @ eye
    return M

def render(meshes, size=(560, 440), azim=35.0, elev=22.0, dist=None, outline=True):
    W, H = size
    allv = np.vstack([m[0] for m in meshes]) if meshes else np.zeros((1, 3))
    # Scenes usually contain one enormous ground slab; framing on the raw
    # bounding box shrinks everything else to nothing. Frame on the bulk of the
    # geometry instead and let the slab run off the edges.
    lo, hi = np.percentile(allv, 2, axis=0), np.percentile(allv, 98, axis=0)
    if not np.all(hi - lo > 1e-6):
        lo, hi = allv.min(0), allv.max(0)
    ctr = (lo + hi) / 2
    rad = max(np.linalg.norm(hi - lo) / 2, 1e-3)
    if dist is None:
        dist = rad * 3.0
    a, e = math.radians(azim), math.radians(elev)
    eye = ctr + dist * np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    V = look_at(eye, ctr)
    fov = math.radians(35.0); fpx = (H / 2) / math.tan(fov / 2)

    zbuf = np.full((H, W), np.inf)
    img = np.zeros((H, W, 3), np.uint8); img[:] = BG
    light = np.array([0.45, 0.35, 0.82]); light /= np.linalg.norm(light)
    edges = []

    for verts, faces, rgb, poly in meshes:
        vh = np.hstack([verts, np.ones((len(verts), 1))])
        cam = (V @ vh.T).T[:, :3]
        z = -cam[:, 2]
        with np.errstate(divide='ignore', invalid='ignore'):
            sx = W / 2 + cam[:, 0] * fpx / z
            sy = H / 2 - cam[:, 1] * fpx / z
        base = np.array(rgb, float)
        for (i0, i1, i2) in faces:
            if z[i0] <= .01 or z[i1] <= .01 or z[i2] <= .01:
                continue
            p0, p1, p2 = verts[i0], verts[i1], verts[i2]
            nrm = np.cross(p1 - p0, p2 - p0)
            ln = np.linalg.norm(nrm)
            if ln < 1e-9:
                continue
            nrm = nrm / ln
            lam = abs(float(nrm @ light))
            shade = 0.32 + 0.68 * lam
            col = np.clip(base * shade, 0, 255)
            x = np.array([sx[i0], sx[i1], sx[i2]]); y = np.array([sy[i0], sy[i1], sy[i2]])
            zz = np.array([z[i0], z[i1], z[i2]])
            x0, x1 = int(max(0, np.floor(x.min()))), int(min(W - 1, np.ceil(x.max())))
            y0, y1 = int(max(0, np.floor(y.min()))), int(min(H - 1, np.ceil(y.max())))
            if x1 < x0 or y1 < y0:
                continue
            den = ((y[1]-y[2])*(x[0]-x[2]) + (x[2]-x[1])*(y[0]-y[2]))
            if abs(den) < 1e-9:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1+1)+.5, np.arange(y0, y1+1)+.5)
            l0 = ((y[1]-y[2])*(gx-x[2]) + (x[2]-x[1])*(gy-y[2])) / den
            l1 = ((y[2]-y[0])*(gx-x[2]) + (x[0]-x[2])*(gy-y[2])) / den
            l2 = 1 - l0 - l1
            m = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            if not m.any():
                continue
            zt = l0*zz[0] + l1*zz[1] + l2*zz[2]
            sub = zbuf[y0:y1+1, x0:x1+1]
            upd = m & (zt < sub)
            sub[upd] = zt[upd]
            img[y0:y1+1, x0:x1+1][upd] = col.astype(np.uint8)
        if outline:
            for (i0, i1, i2) in faces:
                for a_, b_ in ((i0, i1), (i1, i2), (i2, i0)):
                    if z[a_] > .01 and z[b_] > .01:
                        edges.append((sx[a_], sy[a_], sx[b_], sy[b_]))

    im = Image.fromarray(img)
    return im

def grid(items, cols=4, cell=(280, 230), **kw):
    """items = [(label, meshes)]"""
    rows = (len(items) + cols - 1) // cols
    W, H = cell
    sheet = Image.new('RGB', (W * cols, H * rows), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, (label, meshes) in enumerate(items):
        r, c = divmod(i, cols)
        if meshes:
            im = render(meshes, size=(W, H - 16), **kw)
            sheet.paste(im, (c * W, r * H))
        d.text((c * W + 5, r * H + H - 14), label[:38], fill=(0, 0, 0))
    return sheet
