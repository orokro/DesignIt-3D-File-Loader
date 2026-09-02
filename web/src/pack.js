/**
 * Shelf-pack items onto the ground by footprint.
 *
 * Items are laid out in rows sorted by depth, which keeps rows tidy and leaves
 * continuous aisles to walk down. Each item is placed so its bounding box sits
 * ON the ground (min z -> 0) and is centred in its cell, so nothing floats or
 * sinks through the floor.
 */
export function shelfPack(items, { gap = 24, aisle = 60, targetAspect = 1.0 } = {}) {
  const list = items.map((it, i) => ({
    i,
    w: Math.max(it.size[0], 1),
    d: Math.max(it.size[1], 1),
    h: Math.max(it.size[2], 1),
    ref: it,
  }));
  // rows read better when the tall/deep things are grouped
  list.sort((a, b) => b.d - a.d || b.w - a.w);

  const total = list.reduce((s, o) => s + (o.w + gap) * (o.d + aisle), 0);
  const rowWidth = Math.max(Math.sqrt(total * targetAspect), list[0].w * 1.2);

  const placed = [];
  let x = 0, y = 0, rowDepth = 0, rows = 0;
  for (const o of list) {
    if (x > 0 && x + o.w > rowWidth) {
      y += rowDepth + aisle;
      x = 0; rowDepth = 0; rows++;
    }
    placed.push({ ...o, x: x + o.w / 2, y: y + o.d / 2 });
    x += o.w + gap;
    rowDepth = Math.max(rowDepth, o.d);
  }
  const extent = [rowWidth, y + rowDepth];
  return { placed, extent, rows: rows + 1 };
}
