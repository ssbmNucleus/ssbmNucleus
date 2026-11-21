"""
Custom character audio (vault editing): the victory theme, the announcer
name-call, and the fighter's own sound bank (fighter.zip -> sound.zip -> .ssm),
with per-sound replace/revert. The bank is cached decoded under audio_cache/,
and an edit publishes fighter.zip, the cached bank and its manifest together.

Registers on `custom_characters_bp` (vault/routes/custom_characters/__init__.py).
"""

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
from flask import request, jsonify, send_file

import file_retry
from core.config import CUSTOM_CHARACTERS_PATH
import mexcli.commands

from . import custom_characters_bp


def _extract_fighter_ssm(char_dir):
    """Materialize the fighter's sound bank (.ssm from sound.zip inside
    fighter.zip) into audio_cache/bank.ssm. Returns the path or None."""
    cache_dir = char_dir / 'audio_cache'
    bank = cache_dir / 'bank.ssm'
    if bank.exists():
        return bank
    fighter_zip = char_dir / 'fighter.zip'
    if not fighter_zip.exists():
        return None
    import io
    try:
        with zipfile.ZipFile(fighter_zip) as zf:
            sound_entry = next((n for n in zf.namelist()
                                if n.split('/')[-1].lower() == 'sound.zip'), None)
            if sound_entry is None:
                return None
            with zipfile.ZipFile(io.BytesIO(zf.read(sound_entry))) as sz:
                ssm_entry = next((n for n in sz.namelist()
                                  if n.lower().endswith('.ssm')), None)
                if ssm_entry is None:
                    return None
                cache_dir.mkdir(exist_ok=True)
                bank.write_bytes(sz.read(ssm_entry))
                return bank
    except (zipfile.BadZipFile, KeyError):
        return None


def _replace_zip_entry(zip_path, entry_name, new_bytes):
    """Rewrite a zip in place with one entry's bytes replaced; every other
    entry (and all entry names) is preserved verbatim."""
    tmp = zip_path.with_suffix('.tmp')
    with zipfile.ZipFile(zip_path) as zin, \
            zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = new_bytes if item.filename == entry_name else zin.read(item.filename)
            zout.writestr(item, data)
    file_retry.replace(tmp, zip_path)


def _write_fighter_ssm(char_dir, new_ssm_bytes):
    """Push modified sound bank bytes back into fighter.zip -> sound.zip.
    Entry names are preserved — mexLib's FromPackage looks the .ssm up by
    the FileName recorded in group.json, so renaming it would break install.
    Returns True on success."""
    import io
    fighter_zip = char_dir / 'fighter.zip'
    if not fighter_zip.exists():
        return False
    with zipfile.ZipFile(fighter_zip) as zf:
        sound_entry = next((n for n in zf.namelist()
                            if n.split('/')[-1].lower() == 'sound.zip'), None)
        if sound_entry is None:
            return False
        sound_bytes = zf.read(sound_entry)

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(sound_bytes)) as sin, \
            zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as sout:
        ssm_entry = next((n for n in sin.namelist()
                          if n.lower().endswith('.ssm')), None)
        if ssm_entry is None:
            return False
        for item in sin.infolist():
            data = new_ssm_bytes if item.filename == ssm_entry else sin.read(item.filename)
            sout.writestr(item, data)

    _replace_zip_entry(fighter_zip, sound_entry, buf.getvalue())
    return True


def _sound_mods(char_dir):
    """Per-sound modification manifest: {"<index>": {"source": ..., "date": ...}}."""
    p = char_dir / 'sound_mods.json'
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_sound_mods(char_dir, mods):
    p = char_dir / 'sound_mods.json'
    if mods:
        file_retry.retry_locked(p.write_text, json.dumps(mods, indent=2), encoding='utf-8')
    elif p.exists():
        file_retry.retry_locked(p.unlink, missing_ok=True)


def _commit_fighter_sound_bank(char_dir, new_ssm_bytes, mods, keep_original=False):
    """Publish fighter.zip, cached SSM, manifest, and pristine backup together.

    The nested ZIP is rebuilt in a staging directory first. Every destination
    is backed up before replacement and restored if a later publish step fails,
    so an SSM edit cannot leave the install ZIP and browser cache disagreeing.
    """
    fighter_zip = char_dir / 'fighter.zip'
    bank = char_dir / 'audio_cache' / 'bank.ssm'
    mods_path = char_dir / 'sound_mods.json'
    original = char_dir / 'sound_original.ssm'
    if not fighter_zip.exists() or not bank.exists():
        return False

    with tempfile.TemporaryDirectory(dir=char_dir, prefix='.fighter_sound_commit_') as td:
        td = Path(td)
        staged_char = td / 'staged'
        staged_char.mkdir()
        staged_zip = staged_char / 'fighter.zip'
        shutil.copy2(fighter_zip, staged_zip)
        if not _write_fighter_ssm(staged_char, new_ssm_bytes):
            return False

        staged_bank = td / 'bank.ssm'
        staged_bank.write_bytes(new_ssm_bytes)
        staged_mods = td / 'sound_mods.json'
        if mods:
            staged_mods.write_text(json.dumps(mods, indent=2), encoding='utf-8')
        staged_original = td / 'sound_original.ssm'
        create_original = keep_original and not original.exists()
        if create_original:
            shutil.copy2(bank, staged_original)

        targets = [fighter_zip, bank, mods_path]
        if create_original:
            targets.append(original)
        backups = {}
        for i, target in enumerate(targets):
            if target.exists():
                backup = td / f'backup_{i}'
                shutil.copy2(target, backup)
                backups[target] = backup
            else:
                backups[target] = None

        try:
            file_retry.replace(staged_zip, fighter_zip)
            file_retry.replace(staged_bank, bank)
            if mods:
                file_retry.replace(staged_mods, mods_path)
            else:
                mods_path.unlink(missing_ok=True)
            if create_original:
                file_retry.replace(staged_original, original)
        except Exception:
            for target in reversed(targets):
                backup = backups[target]
                if backup is not None and backup.exists():
                    file_retry.replace(backup, target)
                elif backup is None:
                    target.unlink(missing_ok=True)
            raise

    return True


def _invalidate_sound_cache(char_dir, index=None):
    """Drop decoded wav(s) so the next GET re-decodes from the new bank."""
    cache_dir = char_dir / 'audio_cache'
    if not cache_dir.exists():
        return
    pattern = f'sound_{index}.wav' if index is not None else 'sound_*.wav'
    for f in cache_dir.glob(pattern):
        f.unlink(missing_ok=True)


# ============= Audio (victory theme / announcer / sound bank) =============

@custom_characters_bp.route('/api/mex/custom-characters/<slug>/audio/victory-theme', methods=['GET'])
def get_victory_theme_audio(slug):
    """Decode the character's victory theme (extracted at scan) to WAV."""
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    cache = char_dir / 'audio_cache' / 'victory_theme.wav'
    if not cache.exists():
        hps = char_dir / 'victory_theme.hps'
        if not hps.exists():
            return jsonify({'success': False, 'error': 'No victory theme extracted — rescan the source ISO'}), 404
        cache.parent.mkdir(exist_ok=True)
        out = mexcli.commands.run_json(['hps-to-wav', hps, cache])
        if not out.get('success') or not cache.exists():
            return jsonify({'success': False, 'error': out.get('error', 'HPS decode failed')}), 500
    return send_file(cache, mimetype='audio/wav')


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/audio/announcer', methods=['GET'])
def get_announcer_audio(slug):
    """Serve the character's announcer call (decoded at scan time)."""
    wav = CUSTOM_CHARACTERS_PATH / slug / 'announcer.wav'
    if not wav.exists():
        return jsonify({'success': False, 'error': 'No announcer call extracted — rescan the source ISO'}), 404
    return send_file(wav, mimetype='audio/wav')


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/audio/sounds', methods=['GET'])
def list_fighter_sounds(slug):
    """List the fighter's sound bank (groundwork for a future sounds menu)."""
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    bank = _extract_fighter_ssm(char_dir)
    if bank is None:
        return jsonify({'success': False, 'error': 'No sound bank in fighter.zip'}), 404
    info = mexcli.commands.run_json(['ssm-info', bank])
    if not info.get('success'):
        return jsonify({'success': False, 'error': info.get('error', 'SSM read failed')}), 500

    # sound names live in the packed group.json
    names = []
    import io
    try:
        with zipfile.ZipFile(char_dir / 'fighter.zip') as zf:
            sound_entry = next((n for n in zf.namelist()
                                if n.split('/')[-1].lower() == 'sound.zip'), None)
            if sound_entry:
                with zipfile.ZipFile(io.BytesIO(zf.read(sound_entry))) as sz:
                    group_entry = next((n for n in sz.namelist()
                                        if n.split('/')[-1].lower() == 'group.json'), None)
                    if group_entry:
                        names = [s.get('name') for s in json.loads(sz.read(group_entry)).get('sounds', [])]
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError):
        pass

    # placeholder names ("New_Script", "Untitled", blank — what MexManager
    # and ISO scans leave behind) carry no information; index-name those
    placeholders = {'', 'untitled', 'new_script'}
    names = [n if n and n.strip().lower() not in placeholders else None
             for n in names]

    mods = _sound_mods(char_dir)
    sounds = []
    for s in info.get('sounds', []):
        i = s['index']
        sounds.append({
            'index': i,
            'name': (names[i] if i < len(names) and names[i] else f'sound_{i}'),
            'durationMs': s.get('durationMs'),
            'frequency': s.get('frequency'),
            'modified': str(i) in mods,
            'source': (mods.get(str(i)) or {}).get('source'),
            'url': f"/api/mex/custom-characters/{slug}/audio/sound/{i}",
        })
    return jsonify({
        'success': True,
        'count': len(sounds),
        'sounds': sounds,
        'has_original_backup': (char_dir / 'sound_original.ssm').exists(),
    })


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/audio/sound/<int:index>', methods=['GET'])
def get_fighter_sound(slug, index):
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    cache = char_dir / 'audio_cache' / f'sound_{index}.wav'
    if not cache.exists():
        bank = _extract_fighter_ssm(char_dir)
        if bank is None:
            return jsonify({'success': False, 'error': 'No sound bank in fighter.zip'}), 404
        out = mexcli.commands.run_json(['ssm-to-wav', bank, index, cache])
        if not out.get('success') or not cache.exists():
            return jsonify({'success': False, 'error': out.get('error', 'SSM decode failed')}), 500
    return send_file(cache, mimetype='audio/wav')


# Formats MexCLI ssm-replace decodes directly. Originals are uploaded without
# browser transcoding and validated while the replacement bank is rebuilt.
SOUND_IMPORT_EXTS = {
    '.wav', '.mp3', '.ogg', '.m4a', '.flac', '.hps', '.brstm', '.dsp',
}


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/audio/sound/<int:index>/replace', methods=['POST'])
def replace_fighter_sound(slug, index):
    """Replace one sound in the fighter's bank with an uploaded audio file.
    The bank is patched via MexCLI and folded back into fighter.zip, so the
    edit survives export and installs into future builds. The pristine bank
    is kept as sound_original.ssm for per-sound revert."""
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    if not (char_dir / 'fighter.zip').exists():
        return jsonify({'success': False, 'error': 'Character not found'}), 404

    file = request.files.get('file')
    if file is None or not file.filename:
        return jsonify({'success': False, 'error': 'No audio file uploaded'}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in SOUND_IMPORT_EXTS:
        return jsonify({'success': False,
                        'error': f"Unsupported format '{ext}' — use one of: "
                                 + ', '.join(sorted(SOUND_IMPORT_EXTS))}), 400

    bank = _extract_fighter_ssm(char_dir)
    if bank is None:
        return jsonify({'success': False, 'error': 'No sound bank in fighter.zip'}), 404

    with tempfile.TemporaryDirectory(dir=char_dir, prefix='.fighter_sound_replace_') as td:
        upload = Path(td) / f'upload{ext}'
        file.save(upload)
        new_bank = Path(td) / 'bank_new.ssm'
        out = mexcli.commands.run_json(['ssm-replace', bank, index, upload, new_bank])
        if not out.get('success') or not new_bank.exists():
            return jsonify({'success': False, 'error': out.get('error', 'SSM replace failed')}), 400
        new_bytes = new_bank.read_bytes()

    mods = _sound_mods(char_dir)
    mods[str(index)] = {'source': file.filename, 'date': datetime.now().isoformat()}
    if not _commit_fighter_sound_bank(char_dir, new_bytes, mods, keep_original=True):
        return jsonify({'success': False, 'error': 'Failed to repack fighter.zip'}), 500
    _invalidate_sound_cache(char_dir, index)

    return jsonify({'success': True, 'index': index,
                    'durationMs': out.get('durationMs'),
                    'frequency': out.get('frequency')})


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/audio/sound/<int:index>/revert', methods=['POST'])
def revert_fighter_sound(slug, index):
    """Restore one sound from the pristine bank backup (lossless copy)."""
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    original = char_dir / 'sound_original.ssm'
    if not original.exists():
        return jsonify({'success': False, 'error': 'No original backup — nothing to revert'}), 404
    bank = _extract_fighter_ssm(char_dir)
    if bank is None:
        return jsonify({'success': False, 'error': 'No sound bank in fighter.zip'}), 404

    with tempfile.TemporaryDirectory(dir=char_dir, prefix='.fighter_sound_revert_') as td:
        new_bank = Path(td) / 'bank_new.ssm'
        out = mexcli.commands.run_json(['ssm-copy', original, index, bank, index, new_bank])
        if not out.get('success') or not new_bank.exists():
            return jsonify({'success': False, 'error': out.get('error', 'SSM copy failed')}), 500
        new_bytes = new_bank.read_bytes()

    mods = _sound_mods(char_dir)
    mods.pop(str(index), None)
    if not _commit_fighter_sound_bank(char_dir, new_bytes, mods):
        return jsonify({'success': False, 'error': 'Failed to repack fighter.zip'}), 500
    _invalidate_sound_cache(char_dir, index)

    return jsonify({'success': True, 'index': index,
                    'durationMs': out.get('durationMs'),
                    'frequency': out.get('frequency')})


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/audio/sounds/revert-all', methods=['POST'])
def revert_all_fighter_sounds(slug):
    """Restore the entire pristine sound bank."""
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    original = char_dir / 'sound_original.ssm'
    if not original.exists():
        return jsonify({'success': False, 'error': 'No original backup — nothing to revert'}), 404

    bank = _extract_fighter_ssm(char_dir)
    if bank is None:
        return jsonify({'success': False, 'error': 'No sound bank in fighter.zip'}), 404
    new_bytes = original.read_bytes()
    if not _commit_fighter_sound_bank(char_dir, new_bytes, {}):
        return jsonify({'success': False, 'error': 'Failed to repack fighter.zip'}), 500
    _invalidate_sound_cache(char_dir)

    return jsonify({'success': True})
