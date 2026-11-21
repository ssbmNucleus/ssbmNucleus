"""
Music Playlists Blueprint - weighted music playlists for the open project.

Two kinds of playlist, one editing model:

- Stage music: each of the six tournament (DAS) stages has its own
  weighted playlist in the project. An EMPTY playlist is exactly the
  vanilla state (the game falls back to the stage DAT's BGM table), so
  "restore vanilla" = clear the playlist. Reads synthesize the stage's
  actual vanilla songs (VANILLA_STAGE_BGM) when it is empty, so the UI
  always shows - and edits build on - what really plays.
- Menu music: ONE global weighted playlist shared by every menu
  (vanilla = "Menu" @75% + "Menu (Alternate)" @25%). It must never be
  empty - menus have no vanilla fallback.

Playlists are edited directly in the open project (no vault packs).
Play chances are integer percentages that always sum to 100: every
write renormalizes (largest-remainder rounding), and adding a song
gives it an equal share while the rest shrink proportionally.

Reads parse the workspace JSON directly; writes go through MexCLI under
mexcli_lock. Existing playlists use set-stage-playlist/set-menu-playlist;
uploads use add-playlist-music so pooling the normalized HPS and publishing
its playlist happen in one workspace save.

Adding a song is one file per request, and it is a read-modify-write of the
whole playlist: the current entries are read, the upload is appended at an
equal share, and the renormalized list is republished. mexcli_lock serializes
the write but NOT the preceding read, so overlapping add requests both build
on the same pre-upload entries and the last one wins. Clients adding several
songs must send them sequentially (the viewer's bulk picker does).
"""

import json
import subprocess
import tempfile
import logging
import hashlib
import math
import wave
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file

import file_retry
from core.config import MEXCLI_PATH, PROJECT_ROOT, get_subprocess_args
import mexcli.commands
from core.state import get_current_project_path, mexcli_lock
from core.stages import LEGAL_STAGE_CODES, STAGES_BY_CODE

logger = logging.getLogger(__name__)

music_playlists_bp = Blueprint('music_playlists', __name__)

# DAS stage code -> (vault folder, project stage name for set-stage-playlist),
# derived from core/stages.py (project_name is the m-ex stage name).
DAS_SONG_STAGES = {
    code: (STAGES_BY_CODE[code]['folder'], STAGES_BY_CODE[code]['project_name'])
    for code in LEGAL_STAGE_CODES
}

# Formats MexCLI audio-to-hps decodes directly. The frontend uploads the
# original file; every format takes the same validation/normalization path.
MUSIC_IMPORT_EXTS = {
    '.wav', '.mp3', '.ogg', '.m4a', '.flac', '.hps', '.brstm', '.dsp',
}

# What each stage plays in vanilla VS mode: (musicId, weight) read from the
# stage DAT's grGroundParam BGM table (VS-mode grKind entry). The 12%
# entries are the unlock-gated alternate tracks (SongBehaviorFlag 6,
# ChanceToPlayAltSong 12 - see decomp ground.c Ground_801C24F8). Shown -
# and used as the seed - when the project playlist is empty (= vanilla).
VANILLA_STAGE_BGM = {
    'GrNBa': [(81, 88), (38, 12)],   # Battlefield / Multi-Man Melee
    'GrNLa': [(78, 88), (39, 12)],   # Final Destination / Multi-Man Melee (Alt)
    'GrSt': [(96, 100)],             # Yoshi's Story
    'GrOp': [(58, 100)],             # N64 Dream Land
    'GrPs': [(64, 88), (63, 12)],    # Pokemon Stadium / Battle Theme
    'GrIz': [(49, 100)],             # Fountain of Dreams
}


def resolve_stage(stage):
    """Map a DAS stage code (or vault folder name) to (code, folder,
    project stage name). Returns (None, None, None) for unknown stages."""
    for code, (folder, name) in DAS_SONG_STAGES.items():
        if stage == code or stage == folder:
            return code, folder, name
    return None, None, None


# ============= Playlist plumbing =============

def _normalize_chances(entries):
    """Rescale play chances in-place to integers summing to exactly 100,
    preserving ratios (largest-remainder rounding). Works on any dicts
    with a 'chance' key; no-op when empty."""
    if not entries:
        return entries
    weights = [max(0, int(e.get('chance', 0))) for e in entries]
    total = sum(weights)
    if total <= 0:
        weights = [1] * len(entries)
        total = len(entries)
    exact = [w * 100 / total for w in weights]
    floors = [int(x) for x in exact]
    by_remainder = sorted(range(len(exact)),
                          key=lambda i: exact[i] - floors[i], reverse=True)
    for i in by_remainder[:100 - sum(floors)]:
        floors[i] += 1
    for entry, chance in zip(entries, floors):
        entry['chance'] = chance
    return entries


def _appended_entries(tracks, music_id):
    """Current playlist entries plus a new track at an equal share of 100
    (adding a 4th song gives it ~25% and shrinks the rest to fit)."""
    entries = [{'musicId': t['music_id'], 'chance': t['chance']} for t in tracks]
    total = sum(max(0, e['chance']) for e in entries)
    if entries and total <= 0:
        for e in entries:
            e['chance'] = 1
        total = len(entries)
    share = max(1, round(total / len(entries))) if entries else 100
    entries.append({'musicId': music_id, 'chance': share})
    return _normalize_chances(entries)


def _tracks_from_entries(project_file, entries):
    """Resolve raw playlist entries ({musicID, chanceToPlay}) against the
    project's music pool: [{index, music_id, name, chance, has_file,
    _hps_path}]."""
    project_file = Path(project_file)
    try:
        music = json.loads((project_file.parent / 'data' / 'music.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, json.JSONDecodeError):
        music = []

    tracks = []
    for i, entry in enumerate(entries):
        music_id = entry.get('musicID')
        name = f'Music {music_id}'
        hps_path = None
        if isinstance(music_id, int) and 0 <= music_id < len(music):
            item = music[music_id]
            file_name = item.get('fileName') or ''
            name = item.get('name') or Path(file_name).stem or name
            if file_name:
                hps_path = project_file.parent / 'files' / 'audio' / file_name
        tracks.append({
            'index': i,
            'music_id': music_id,
            'name': name,
            'chance': entry.get('chanceToPlay', 50),
            'has_file': hps_path is not None and hps_path.is_file(),
            '_hps_path': hps_path,
        })
    return tracks


def _public_tracks(tracks):
    return [{k: v for k, v in t.items() if not k.startswith('_')} for t in tracks]


def _get_menu_playlist(project_file):
    """Read the project-wide menu playlist from workspace JSON."""
    try:
        project = json.loads(Path(project_file).read_text(encoding='utf-8'))
        entries = ((project.get('menuPlaylist') or {}).get('entries')) or []
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []
    return _tracks_from_entries(project_file, entries)


def _find_stage_data(project_file, stage_name):
    """Locate a stage's json in the project workspace by display name.
    LAST name match wins, mirroring MexCLI set-stage-playlist. Returns
    the parsed stage json or None."""
    project_file = Path(project_file)
    try:
        project = json.loads(project_file.read_text(encoding='utf-8'))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    found = None
    for file_path in (project.get('stageSaveMap') or {}).get('filePaths') or []:
        p = project_file.parent / 'data' / 'stages' / file_path
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (data.get('name') or '').strip().lower() == stage_name.lower():
            found = data
    return found


def _get_stage_playlist(project_file, stage_name):
    """Read a stage's playlist from workspace JSON. Returns a track list
    (possibly empty = vanilla) or None when the stage isn't in the
    project."""
    data = _find_stage_data(project_file, stage_name)
    if data is None:
        return None
    entries = ((data.get('playlist') or {}).get('entries')) or []
    return _tracks_from_entries(project_file, entries)


def _stage_tracks(project_file, stage_name, code):
    """The stage's effective tracks: its project playlist, or - when that
    is empty (= vanilla) - the stage's actual vanilla songs synthesized
    from VANILLA_STAGE_BGM so the UI can show and build on what really
    plays. Returns (tracks, vanilla) or (None, False) when the stage
    isn't in the project."""
    tracks = _get_stage_playlist(project_file, stage_name)
    if tracks is None:
        return None, False
    if tracks:
        return _normalize_chances(tracks), False
    entries = [{'musicID': music_id, 'chanceToPlay': chance}
               for music_id, chance in VANILLA_STAGE_BGM.get(code, [])]
    return _tracks_from_entries(project_file, entries), True


def _set_stage_playlist(project_file, stage_name, entries):
    """Run set-stage-playlist (entries JSON on stdin). An empty list
    clears the playlist, restoring vanilla default music."""
    # Workspace-mutating MexCLI call -- hold the project lock (shared with the
    # background costume reorder / export) so two MexCLI processes can't run at once.
    with mexcli_lock:
        result = subprocess.run(
            [str(MEXCLI_PATH), 'set-stage-playlist', str(project_file), stage_name],
            input=json.dumps(entries),
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), **get_subprocess_args()
        )
    out = mexcli.commands.parse_json(result.stdout)
    out['_returncode'] = result.returncode
    return out


def _set_menu_playlist(project_file, entries):
    """Run set-menu-playlist (entries JSON on stdin). Entries must be
    non-empty: an empty menu playlist has no vanilla fallback."""
    with mexcli_lock:
        result = subprocess.run(
            [str(MEXCLI_PATH), 'set-menu-playlist', str(project_file)],
            input=json.dumps(entries),
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), **get_subprocess_args()
        )
    out = mexcli.commands.parse_json(result.stdout)
    out['_returncode'] = result.returncode
    return out


def _add_playlist_music(project_file, hps, name, target, entries, stage_name=None):
    """Add/reuse one track and publish its playlist in one workspace Save.

    ``entries`` contains exactly one musicId:-1 placeholder, which MexCLI
    replaces with the added/reused track id before saving.
    """
    args = [str(MEXCLI_PATH), 'add-playlist-music', str(project_file),
            str(hps), name, target]
    if target == 'stage':
        args.append(stage_name)
    with mexcli_lock:
        result = subprocess.run(
            args, input=json.dumps(entries), capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), **get_subprocess_args()
        )
    out = mexcli.commands.parse_json(result.stdout)
    out['_returncode'] = result.returncode
    return out


def _add_uploaded_music(project_file, target, entries, stage_name=None):
    """Validate and normalize an upload, then atomically add it and publish
    the supplied stage/menu playlist. Returns (CLI output, name, None) on
    success or (None, None, (response, status)) on failure."""
    file = request.files.get('file')
    if file is None or not file.filename:
        return None, None, (jsonify({'success': False, 'error': 'No audio file uploaded'}), 400)
    ext = Path(file.filename).suffix.lower()
    if ext not in MUSIC_IMPORT_EXTS:
        return None, None, (jsonify({
            'success': False,
            'error': f"Unsupported format '{ext}' — use one of: "
                     + ', '.join(sorted(MUSIC_IMPORT_EXTS))}), 400)
    name = (request.form.get('name') or '').strip() or Path(file.filename).stem

    with tempfile.TemporaryDirectory() as td:
        upload = Path(td) / f'upload{ext}'
        file.save(upload)
        # Always round-trip through the converter, including native HPS.
        # Besides rejecting corrupt/truncated HPS files, this normalizes the
        # channel layout and forces the loop flag used by in-game music.
        hps = Path(td) / 'track.hps'
        converted = mexcli.commands.run_json(['audio-to-hps', upload, hps])
        if not converted.get('success') or not hps.exists():
            return None, None, (jsonify({
                'success': False,
                'error': converted.get('error', 'Audio conversion failed')}), 400)
        music_out = _add_playlist_music(
            project_file, hps, name, target, entries, stage_name=stage_name)

    if not music_out.get('success') or 'musicId' not in music_out:
        return None, None, (jsonify({
            'success': False,
            'error': music_out.get('error', 'Failed to add music and update playlist')}), 500)
    return music_out, name, None


def _parse_set_entries(data):
    """Parse a bulk-set body ({entries: [{music_id, chance}]}) into CLI
    entries. Returns (entries, None) or (None, (response, status))."""
    raw = (data or {}).get('entries')
    if not isinstance(raw, list):
        return None, (jsonify({'success': False,
                               'error': 'entries must be a list of {music_id, chance}'}), 400)
    entries = []
    for e in raw:
        try:
            entries.append({'musicId': int(e['music_id']),
                            'chance': max(0, min(100, int(e['chance'])))})
        except (KeyError, TypeError, ValueError):
            return None, (jsonify({'success': False,
                                   'error': 'entries must be a list of {music_id, chance}'}), 400)
    return _normalize_chances(entries), None


def _preview_version(project_file, hps):
    # Older unversioned WAVs may contain output from a broken decoder. Bind
    # previews to source bytes and the decoder build, not filesystem mtimes.
    digest = hashlib.sha256(('pcm-preview-v1:' + _loop_version(project_file, hps)).encode())
    cli = Path(mexcli.commands.MEXCLI)
    for path in (cli, *(cli.parent / name for name in ('mexcli.dll', 'MeleeMedia.dll', 'mexLib.dll'))):
        if path.is_file():
            stat = path.stat()
            digest.update(f'{path.name}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
    return digest.hexdigest()


def _complete_preview(path):
    """A successful converter exit alone does not prove the PCM was written."""
    try:
        with wave.open(str(path), 'rb') as wav:
            frames = wav.getnframes()
            if frames <= 0:
                return False
            wav.setpos(frames - 1)
            return len(wav.readframes(1)) == wav.getnchannels() * wav.getsampwidth()
    except (OSError, EOFError, wave.Error):
        return False


def _track_preview(project_file, track):
    """Publish complete decoded PCM only, shared by playlist and loop previews."""
    hps = track['_hps_path']
    if hps is None or not hps.is_file():
        return jsonify({'success': False, 'error': 'Music file not found'}), 404
    directory = Path(project_file).parent / 'cache' / 'music_previews'
    prefix = f"track_{track['music_id']}"
    # Playlist previews also use this path, outside their playlist-read lock.
    with mexcli_lock:
        version = _preview_version(project_file, hps)
        # An earlier response can still be streaming on Windows. A new source
        # gets its own immutable file instead of replacing that open handle.
        cache = directory / f'{prefix}_{version}.wav'
        if not _complete_preview(cache):
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.music-preview-', dir=directory) as td:
                staged = Path(td) / 'preview.wav'
                out = mexcli.commands.run_json(['hps-to-wav', hps, staged])
                if not out.get('success') or not _complete_preview(staged):
                    return jsonify({'success': False,
                                    'error': out.get('error') or 'HPS decode failed: incomplete audio preview'}), 500
                file_retry.replace(staged, cache)
        # Keep in-use older previews alive; a subsequent request retries their
        # retirement after consumers release them. Never block playback on it.
        for stale in (directory / f'{prefix}.wav', *directory.glob(f'{prefix}_*.wav')):
            if stale != cache:
                try:
                    stale.unlink(missing_ok=True)
                except OSError:
                    logger.debug('Music preview still in use: %s', stale)
        return send_file(cache, mimetype='audio/wav')


def _loop_track(project_file, music_id):
    """Resolve a pool id, never a client path or a mutable playlist index."""
    track = _tracks_from_entries(project_file, [{'musicID': music_id}])[0]
    hps = track['_hps_path']
    root = (Path(project_file).parent / 'files' / 'audio').resolve()
    if hps is None or not hps.resolve().is_relative_to(root) or not hps.is_file():
        return None
    return track


def _loop_version(project_file, hps):
    # Bind the editor to both its project and exact source bytes. Switching
    # projects or editing a shared track elsewhere cannot overwrite stale data.
    digest = hashlib.sha256(str(Path(project_file).resolve()).encode('utf-8'))
    digest.update(str(hps.resolve()).encode('utf-8'))
    digest.update(hps.read_bytes())
    return digest.hexdigest()


@music_playlists_bp.route('/api/mex/music/<int:music_id>/loop', methods=['GET', 'POST'])
def music_loop(music_id):
    """Inspect/edit the loop of a project music-pool track, shared by playlists."""
    with mexcli_lock:
        project = get_current_project_path()
        if project is None:
            return jsonify(success=False, error='No project open'), 409
        track = _loop_track(project, music_id)
        if track is None:
            return jsonify(success=False, error='Music file not found'), 404
        hps = track['_hps_path']
        version = _loop_version(project, hps)
        if request.method == 'POST':
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify(success=False, error='Expected loop settings'), 400
            if data.get('version') != version:
                return jsonify(success=False, error='This song or project changed. Close and reopen the loop editor.'), 409
            start = data.get('loop_start_ms')
            if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0:
                return jsonify(success=False, error='Loop start must be a finite, nonnegative time'), 400
            # Same filesystem for atomic publication; conversion never writes
            # over the source. A failed encode leaves the original untouched.
            with tempfile.TemporaryDirectory(prefix='.music-loop-', dir=hps.parent) as td:
                staged = Path(td) / 'track.hps'
                out = mexcli.commands.run_json(['hps-set-loop', hps, staged, str(start)])
                if not out.get('success') or not staged.is_file():
                    return jsonify(success=False, error=out.get('error', 'Could not save loop')), 400
                if get_current_project_path() != project or _loop_version(project, hps) != version:
                    return jsonify(success=False, error='This song or project changed. Close and reopen the loop editor.'), 409
                file_retry.replace(staged, hps)
            version = _loop_version(project, hps)
        else:
            out = mexcli.commands.run_json(['hps-loop-info', hps])
            if not out.get('success'):
                return jsonify(success=False, error=out.get('error', 'Could not read loop')), 400
        return jsonify(**{k: out[k] for k in ('duration_ms', 'loop_start_ms', 'loop_enabled', 'frequency')},
                       success=True, version=version)


@music_playlists_bp.route('/api/mex/music/<int:music_id>/loop/preview', methods=['GET'])
def music_loop_preview(music_id):
    with mexcli_lock:
        project = get_current_project_path()
        if project is None:
            return jsonify(success=False, error='No project open'), 409
        track = _loop_track(project, music_id)
        if track is None:
            return jsonify(success=False, error='Music file not found'), 404
        if request.args.get('version') != _loop_version(project, track['_hps_path']):
            return jsonify(success=False, error='Song changed; reopen the loop editor'), 409
        return _track_preview(project, track)


# ============= Stage music =============

@music_playlists_bp.route('/api/mex/das/<stage>/stage-music', methods=['GET'])
def get_stage_music(stage):
    """Return the stage's effective playlist in the open project. When
    the project playlist is empty, the tracks are the stage's vanilla
    songs and `vanilla` is true."""
    code, _folder, stage_name = resolve_stage(stage)
    if code is None:
        return jsonify({'success': False, 'error': f'Not a DAS stage: {stage}'}), 404
    project_file = get_current_project_path()
    if project_file is None:
        return jsonify({'success': True, 'stage': code, 'project_open': False,
                        'vanilla': True, 'tracks': []})

    with mexcli_lock:
        tracks, vanilla = _stage_tracks(project_file, stage_name, code)
    if tracks is None:
        return jsonify({'success': False,
                        'error': f'{stage_name} not found in this project'}), 404
    return jsonify({'success': True, 'stage': code, 'project_open': True,
                    'vanilla': vanilla, 'tracks': _public_tracks(tracks)})


@music_playlists_bp.route('/api/mex/das/<stage>/stage-music/tracks/add', methods=['POST'])
def add_stage_track(stage):
    """Convert an upload, add it to the project's music pool and append
    it to the stage's playlist at an equal share."""
    code, _folder, stage_name = resolve_stage(stage)
    if code is None:
        return jsonify({'success': False, 'error': f'Not a DAS stage: {stage}'}), 404
    project_file = get_current_project_path()
    if project_file is None:
        return jsonify({'success': False, 'error': 'No project open'}), 409

    # Report a missing stage before spending time decoding the upload. MexCLI
    # repeats this preflight inside the combined, single-save mutation.
    tracks, _vanilla = _stage_tracks(project_file, stage_name, code)
    if tracks is None:
        return jsonify({'success': False,
                        'error': f'{stage_name} not found in this project'}), 404

    entries = _appended_entries(tracks, -1)
    music_out, name, err = _add_uploaded_music(
        project_file, 'stage', entries, stage_name=stage_name)
    if err:
        return err

    tracks, vanilla = _stage_tracks(project_file, stage_name, code)
    logger.info(f"Stage track '{name}' added to {stage_name} in "
                f"{Path(project_file).parent.name} ({len(tracks or [])} entries)")
    return jsonify({'success': True, 'vanilla': vanilla,
                    'tracks': _public_tracks(tracks or [])})


@music_playlists_bp.route('/api/mex/das/<stage>/stage-music/set', methods=['POST'])
def set_stage_music(stage):
    """Replace the stage's playlist. Chances are renormalized to sum to
    100. An empty entries list restores vanilla music."""
    code, _folder, stage_name = resolve_stage(stage)
    if code is None:
        return jsonify({'success': False, 'error': f'Not a DAS stage: {stage}'}), 404
    project_file = get_current_project_path()
    if project_file is None:
        return jsonify({'success': False, 'error': 'No project open'}), 409

    entries, err = _parse_set_entries(request.get_json(silent=True))
    if err:
        return err
    out = _set_stage_playlist(project_file, stage_name, entries)
    if not out.get('success'):
        return jsonify({'success': False,
                        'error': out.get('error', 'Failed to set stage playlist')}), 500
    tracks, vanilla = _stage_tracks(project_file, stage_name, code)
    return jsonify({'success': True, 'vanilla': vanilla,
                    'tracks': _public_tracks(tracks or [])})


@music_playlists_bp.route('/api/mex/das/<stage>/stage-music/track/<int:index>', methods=['GET'])
def preview_stage_track(stage, index):
    """Decode a stage playlist entry to WAV for browser preview."""
    code, _folder, stage_name = resolve_stage(stage)
    if code is None:
        return jsonify({'success': False, 'error': f'Not a DAS stage: {stage}'}), 404
    project_file = get_current_project_path()
    if project_file is None:
        return jsonify({'success': False, 'error': 'No project open'}), 409

    with mexcli_lock:
        tracks, _vanilla = _stage_tracks(project_file, stage_name, code)
    if tracks is None or not (0 <= index < len(tracks)):
        return jsonify({'success': False, 'error': f'Track {index} out of range'}), 404
    return _track_preview(project_file, tracks[index])


# ============= Menu music =============

@music_playlists_bp.route('/api/mex/menu-music', methods=['GET'])
def get_menu_music():
    """Return the open project's menu playlist (all entries with chances)."""
    project_file = get_current_project_path()
    if project_file is None:
        return jsonify({'success': False, 'error': 'No project open'}), 409

    with mexcli_lock:
        tracks = _get_menu_playlist(project_file)
    return jsonify({'success': True, 'tracks': _public_tracks(_normalize_chances(tracks))})


@music_playlists_bp.route('/api/mex/menu-music/tracks/add', methods=['POST'])
def add_menu_track():
    """Convert an upload, add it to the project's music pool and append
    it to the menu playlist at an equal share."""
    project_file = get_current_project_path()
    if project_file is None:
        return jsonify({'success': False, 'error': 'No project open'}), 409

    entries = _appended_entries(_get_menu_playlist(project_file), -1)
    music_out, name, err = _add_uploaded_music(project_file, 'menu', entries)
    if err:
        return err

    tracks = _get_menu_playlist(project_file)
    logger.info(f"Menu track '{name}' added in {Path(project_file).parent.name} "
                f"({len(tracks)} entries)")
    return jsonify({'success': True, 'tracks': _public_tracks(tracks)})


@music_playlists_bp.route('/api/mex/menu-music/set', methods=['POST'])
def set_menu_music():
    """Replace the menu playlist. Chances are renormalized to sum to
    100. Must keep at least one song — menus have no vanilla fallback."""
    project_file = get_current_project_path()
    if project_file is None:
        return jsonify({'success': False, 'error': 'No project open'}), 409

    entries, err = _parse_set_entries(request.get_json(silent=True))
    if err:
        return err
    if not entries:
        return jsonify({'success': False,
                        'error': 'The menu playlist needs at least one song — '
                                 'add a replacement first'}), 400
    out = _set_menu_playlist(project_file, entries)
    if not out.get('success'):
        return jsonify({'success': False,
                        'error': out.get('error', 'Failed to set menu playlist')}), 500
    return jsonify({'success': True,
                    'tracks': _public_tracks(_get_menu_playlist(project_file))})


@music_playlists_bp.route('/api/mex/menu-music/track/<int:index>', methods=['GET'])
def preview_menu_track(index):
    """Decode a menu playlist entry to WAV for browser preview."""
    project_file = get_current_project_path()
    if project_file is None:
        return jsonify({'success': False, 'error': 'No project open'}), 409

    with mexcli_lock:
        tracks = _get_menu_playlist(project_file)
    if not (0 <= index < len(tracks)):
        return jsonify({'success': False, 'error': f'Track {index} out of range'}), 404
    return _track_preview(project_file, tracks[index])
