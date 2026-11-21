"""A ripped Brawl model made ready for the model importer.

Usage (cwd app/backend): python brawl_model.py <work> <fighter> <rip.zip> <out.zip>
<work> holds the extracted disc; <rip.zip> is the rip (a COLLADA file and its pictures in one folder). Writes <out.zip>,
the same with what the game does not draw at rest taken out and layered materials (an eye's white, iris and highlight)
named, ordered and drawn so that the importer lays them over each other and makes the eye blink
(echo_brawl.model says how and why).
"""
import io
import sys
import _where  # noqa: E402
import zipfile
from pathlib import Path

sys.path.insert(0, str(_where.BACKEND))
sys.path.insert(0, str(_where.PORT_REPO))
from PIL import Image  # noqa: E402
from echo_brawl import model  # noqa: E402

work, fighter, rip, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
with zipfile.ZipFile(rip) as z:
    files = {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
dae_name = next(n for n in files if n.lower().endswith('.dae'))
folder = dae_name.rsplit('/', 1)[0] + '/' if '/' in dae_name else ''
pictures = {n[len(folder):]: Image.open(io.BytesIO(b)) for n, b in files.items() if n.startswith(folder) and n.lower().endswith('.png')}
parts = model.parts(work, fighter)
print('the model:', len(parts['objects']), 'objects;', sum(1 for d in parts['draws'] if not d[3]), 'not drawn at rest; layered materials',
      {m: [t for t, _u, _v in refs] for m, refs in parts['layers'].items() if len(refs) > 1})
dae, new, notes = model.prepare(files[dae_name].decode('utf-8'), pictures, parts)
for line in notes:
    print('  ', line)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for n, b in files.items():
        z.writestr(n, dae.encode('utf-8') if n == dae_name else b)
    for name, picture in new.items():
        data = io.BytesIO()
        picture.save(data, 'PNG')
        z.writestr(folder + name, data.getvalue())
print('written:', out, out.stat().st_size, 'bytes;', len(new), 'pictures added')
