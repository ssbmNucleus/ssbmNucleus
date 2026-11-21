"""Carry separately hosted website portraits into the original mod archive."""
import io
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image

MAX_EXPANDED = 512 * 1024 * 1024


def fetch_png(url, download):
    with tempfile.TemporaryDirectory(prefix='nucleus-art-') as directory:
        path = Path(directory) / 'image'
        download(url, path)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Website portrait exceeds the image size limit.')
        with Image.open(path) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError('Website portrait exceeds the image resolution limit.')
            output = io.BytesIO()
            image.convert('RGBA').save(output, format='PNG')
            return output.getvalue()


def hydrate_archive(path, rows, download):
    """Add CSP/stock alongside exact matching DAT filenames, including nested zips.

    Original files are preserved. Ambiguous basename matches are not guessed.
    The importer already pairs name_csp.png / name_stc.png with name.dat.
    """
    from .website_posts import _media
    rows = [r for r in rows if r.get('file_type') == 'character_dat' and r.get('filename')
            and (r.get('csp_url') or r.get('stock_url'))]
    if not rows:
        return []
    warnings, matched, cache = [], set(), {}
    expanded = 0

    def enrich(raw, depth=0):
        nonlocal expanded
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            infos = source.infolist()
            expanded += sum(i.file_size for i in infos)
            if expanded > MAX_EXPANDED or len(infos) > 10000:
                raise ValueError('Mod archive exceeds the chat extraction limit.')
            names = source.namelist()
            additions = {}
            for row in rows:
                filename = row['filename'].replace('\\', '/')
                exact = [n for n in names if n.replace('\\', '/').casefold() == filename.casefold()]
                candidates = exact or [n for n in names if PurePosixPath(n.replace('\\', '/')).name.casefold() == PurePosixPath(filename).name.casefold()]
                if len(candidates) != 1:
                    continue
                member = candidates[0]
                matched.add(row['id'])
                for field, suffix in [('csp_url', '_csp.png'), ('stock_url', '_stc.png')]:
                    value = row.get(field)
                    if not value:
                        continue
                    target = str(PurePosixPath(member.replace('\\', '/')).with_suffix('')) + suffix
                    if target in names or target in additions:
                        continue
                    try:
                        url = _media(value)
                        if not url:
                            raise ValueError('Website portrait has an unsupported URL.')
                        if url not in cache:
                            cache[url] = fetch_png(url, download)
                        additions[target] = cache[url]
                    except Exception:
                        warnings.append(f"Could not fetch {field.replace('_url', '')} for {filename}.")
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target_zip:
                for info in infos:
                    content = source.read(info)
                    if info.filename.lower().endswith('.zip') and depth < 2:
                        content = enrich(content, depth + 1)
                    target_zip.writestr(info, content)
                for name, content in additions.items():
                    target_zip.writestr(name, content)
            return output.getvalue()

    enriched = enrich(Path(path).read_bytes())
    Path(path).write_bytes(enriched)
    for row in rows:
        if row['id'] not in matched and row.get('csp_url'):
            warnings.append(f"Website portrait could not be matched to {row['filename']} in the archive.")
    return warnings
