"""Parse every file in the corpus strictly. Any error means the schema is wrong."""
import sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
import iff

root = sys.argv[1] if len(sys.argv) > 1 else '..'
ok = bad = 0
errs = []
tagcount = collections.Counter()
parent_of = collections.defaultdict(collections.Counter)
sizes = collections.defaultdict(collections.Counter)

def visit(c, parent):
    tagcount[c.tag] += 1
    parent_of[c.tag][parent] += 1
    if not c.children:
        sizes[c.tag][len(c.data)] += 1
    for k in c.children:
        visit(k, c.tag)

for p in iff.walk_files(root):
    try:
        r = iff.load(p)
        visit(r, '-')
        ok += 1
    except Exception as e:
        bad += 1
        errs.append((p, str(e)))

print(f'parsed OK: {ok}   FAILED: {bad}')
for p, e in errs[:20]:
    print('  FAIL', os.path.relpath(p, root), '::', e)
print()
print(f'{"TAG":6} {"COUNT":>7}  {"PARENTS":<34} SIZES')
for t, n in tagcount.most_common():
    if t == '$ROOT':
        continue
    par = ','.join(f'{k}' for k, _ in parent_of[t].most_common(3))
    sz = sizes[t]
    if sz:
        s = ','.join(str(k) for k, _ in sz.most_common(4))
        if len(sz) > 4:
            s += f',… ({len(sz)} distinct)'
    else:
        s = '(container)'
    print(f'{t:6} {n:7}  {par:<34} {s}')
