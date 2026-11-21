"""Resolve the second Ice Climbers costume without replacing a custom partner."""

from pathlib import Path
import zipfile


POPO_TO_NANA = {'Nr': 'Nr', 'Re': 'Wh', 'Or': 'Aq', 'Gr': 'Ye'}


def _member_from_zip(zip_path, output_dir, prefix, label):
    """Read one member DAT; flatten ZIP paths into the owned session folder."""
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist()
                 if Path(name.replace('\\', '/')).name.lower().startswith(prefix)
                 and Path(name).suffix.lower() in ('.dat', '.usd')]
        if len(names) != 1:
            raise ValueError(f'The paired {label} archive must contain exactly one {label} costume.')
        target = Path(output_dir) / Path(names[0].replace('\\', '/')).name
        target.write_bytes(archive.read(names[0]))
        return target


def nana_from_zip(zip_path, output_dir):
    return _member_from_zip(zip_path, output_dir, 'plnn', 'Nana')


def find_paint_partner(source_path, *, find_vanilla, storage_root,
                       costume_id=None, metadata=None, output_dir=None):
    """Resolve either climber's partner; explicit custom links never fall back."""
    source_path = Path(source_path)
    is_popo = source_path.name.lower().startswith('plpp')
    if not is_popo and not source_path.name.lower().startswith('plnn'):
        raise ValueError('An Ice Climbers pair requires a Popo or Nana costume.')
    label, prefix = ('Nana', 'PlNn') if is_popo else ('Popo', 'PlPp')
    key, reverse_key = ('paired_nana_id', 'paired_popo_id') if is_popo else ('paired_popo_id', 'paired_nana_id')
    characters = (metadata or {}).get('characters', {})
    # Legacy Nana records may live under either character name. Do not search
    # custom fighter libraries: sharing a donor skeleton does not make a pair.
    records = [(name, skin) for name in ('Ice Climbers', 'Nana')
               for skin in characters.get(name, {}).get('skins', [])]
    if costume_id:
        source = next((skin for _, skin in records if skin.get('id') == costume_id), None)
        pair_id = (source or {}).get(key)
        if not pair_id:
            reverse = [skin for _, skin in records if skin.get(reverse_key) == costume_id]
            if len(reverse) > 1:
                raise ValueError(f'Multiple {label} costumes link to this costume. Repair the pairing before opening it.')
            if reverse:
                pair_id = reverse[0].get('id')
        if pair_id:
            for char_name, partner in records:
                if partner.get('id') == pair_id and partner.get('filename'):
                    root = Path(storage_root).resolve()
                    archive = (root / char_name / partner['filename']).resolve()
                    if not archive.is_relative_to(root) or not archive.is_file():
                        break
                    return _member_from_zip(archive, output_dir, prefix.lower(), label)
            raise ValueError(f'The paired {label} costume is missing. Restore it before opening this pair.')

    colors = POPO_TO_NANA if is_popo else {nana: popo for popo, nana in POPO_TO_NANA.items()}
    partner_color = colors.get(source_path.stem[4:6])
    if partner_color:
        partner = find_vanilla('Nana' if is_popo else 'Ice Climbers', prefix + partner_color)
        if partner and Path(partner).is_file():
            return partner
    raise ValueError(f'No paired {label} costume is available. Restore the vanilla assets or import a complete pair.')
