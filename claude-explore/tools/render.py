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

def render(meshes, size=(560, 440), azim=35.0, elev=22.0, dist=None, outline=True, ortho=False, margin=1.12):
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
    if ortho:
        # fit the framing box to the viewport
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        cc = (V @ np.hstack([corners, np.ones((8, 1))]).T).T[:, :3]
        ex = max(cc[:, 0].max() - cc[:, 0].min(), 1e-6) * margin
        ey = max(cc[:, 1].max() - cc[:, 1].min(), 1e-6) * margin
        fpx = min(W / ex, H / ey)
    else:
        fov = math.radians(35.0); fpx = (H / 2) / math.tan(fov / 2)

    zbuf = np.full((H, W), np.inf)
    img = np.zeros((H, W, 3), np.uint8); img[:] = BG
    light = np.array([0.45, 0.35, 0.82]); light /= np.linalg.norm(light)
    edges = []

    for _m in meshes:
        verts, faces, rgb, poly = _m[0], _m[1], _m[2], _m[3]
        tex = _m[4] if len(_m) > 4 else None
        alpha = _m[5] if len(_m) > 5 and _m[5] is not None else 255
        mask = _m[6] if len(_m) > 6 else None
        vh = np.hstack([verts, np.ones((len(verts), 1))])
        cam = (V @ vh.T).T[:, :3]
        z = -cam[:, 2]
        with np.errstate(divide='ignore', invalid='ignore'):
            if ortho:
                sx = W / 2 + cam[:, 0] * fpx
                sy = H / 2 - cam[:, 1] * fpx
            else:
                sx = W / 2 + cam[:, 0] * fpx / z
                sy = H / 2 - cam[:, 1] * fpx / z
        base = np.array(rgb, float)
        for fi, (i0, i1, i2) in enumerate(faces):
            if not ortho and (z[i0] <= .01 or z[i1] <= .01 or z[i2] <= .01):
                continue
            p0, p1, p2 = verts[i0], verts[i1], verts[i2]
            nrm = np.cross(p1 - p0, p2 - p0)
            ln = np.linalg.norm(nrm)
            if ln < 1e-9:
                continue
            nrm = nrm / ln
            lam = abs(float(nrm @ light))
            # The APPLICATION's own split, read off its VRML exporter: all
            # 3,184 materials in the Virtus exports write `ambientColor` at
            # exactly 0.25 x `diffuseColor`.
            shade = 0.25 + 0.75 * lam
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
            if mask is not None and mask['uv'][fi] is not None:
                # The OPENING stencil. The face keeps all of its geometry and
                # the pixels inside a hole are simply never painted -- which is
                # how a renderer with no boolean geometry cuts a hole, and how
                # this one almost certainly did it.
                q = mask['uv'][fi]
                mu = l0*q[0][0] + l1*q[1][0] + l2*q[2][0]
                mv = l0*q[0][1] + l1*q[1][1] + l2*q[2][1]
                mw, mh = mask['w'], mask['h']
                mx = np.clip((mu*mw).astype(np.int32), 0, mw-1)
                my = np.clip((mv*mh).astype(np.int32), 0, mh-1)
                flatm = np.frombuffer(mask['a'], np.uint8).reshape(mh, mw)
                upd = upd & (flatm[my, mx] >= 128)
            sub[upd] = zt[upd]
            if tex is not None and tex.get('uv') is not None and tex['uv'][fi] is not None:
                # per-pixel texture sample: interpolate UV barycentrically, wrap,
                # and shade with the same lambert term the flat path uses
                q = tex['uv'][fi]
                uu = l0*q[0][0] + l1*q[1][0] + l2*q[2][0]
                vv = l0*q[0][1] + l1*q[1][1] + l2*q[2][1]
                tw, th_ = tex['w'], tex['h']
                wu, wv = tex.get('wrap', (True, True))
                # a backdrop is fitted once to the face and must CLAMP, not wrap
                px = (np.mod((uu*tw).astype(np.int32), tw) if wu
                      else np.clip((uu*tw).astype(np.int32), 0, tw-1))
                py = (np.mod((vv*th_).astype(np.int32), th_) if wv
                      else np.clip((vv*th_).astype(np.int32), 0, th_-1))
                flat = np.frombuffer(tex['rgb'], np.uint8).reshape(th_, tw, 3)
                samp = flat[py, px].astype(float) * shade
                img[y0:y1+1, x0:x1+1][upd] = np.clip(samp, 0, 255).astype(np.uint8)[upd]
            elif alpha >= 250:
                img[y0:y1+1, x0:x1+1][upd] = col.astype(np.uint8)
            else:
                # Translucent. The original dithered on a checkerboard; a real
                # blend is the same idea without the 8-bit palette constraint.
                a = alpha / 255.0
                dst = img[y0:y1+1, x0:x1+1].astype(float)
                blend = dst*(1-a) + col*a
                img[y0:y1+1, x0:x1+1][upd] = np.clip(blend, 0, 255).astype(np.uint8)[upd]
                sub[upd] = np.inf          # do not occlude what is behind it
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
