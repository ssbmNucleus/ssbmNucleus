"""The ONE portrait renderer.

Every character-select portrait in the app is produced here: the vault retake,
the CSP manager's HD regen, pose thumbnails and alternates, custom-character
previews. Before 2026-08-22 three call sites resolved a pose independently and
two of them got it wrong -- scene-mode characters rendered without their baked
animation, custom characters looked in a directory that never exists, and a
Game & Watch colour mod came out BLACK because its colours were never passed
down. Those are the bugs this module exists to make unrepeatable.

What "resolving a render" means:

  pose        -> the animation + camera the renderer is given. A *scene* pose
                 (`useSceneAnimation: true`) has no animSymbol: the character's
                 baked csp_data/<char>/scene.yml supplies the animation and the
                 pose supplies only camera/frame, so the two are merged into a
                 temp file that MUST be named scene.yml (the name is what puts
                 the viewer in scene mode). A symbol pose goes straight through
                 with the character's AJ archive.
  character   -> where the poses live (custom characters keep theirs under
                 custom_poses/custom_characters/<slug>) and which AJ archive to
                 use (extracted from the fighter.zip for custom characters).
  colours     -> Mr. Game & Watch renders white and is recoloured at load; the
                 flat colour must be passed in or he falls back to vanilla slot
                 0 (black). Colour mods carry theirs in a gaw.json sidecar.

Ice Climbers are the one deliberate gap: their portrait is a Popo-over-Nana
composite and custom poses for them are an accepted scope cut (see the wiki's
CSP-And-Pose-Workflow). A posed IC render therefore keeps the PAIRED default
rather than silently dropping Nana.
"""
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import NamedTuple

from core.config import PROCESSOR_DIR, VANILLA_ASSETS_DIR
from core.constants import CHAR_PREFIXES
from core.metadata import custom_character_slug
from generate_csp import (_model_dobj_count, apply_character_specific_layers, generate_csp,
                          generate_single_csp_internal)

logger = logging.getLogger(__name__)


def pose_character_key(character):
    """Directory key for a character's poses. The two custom-character pseudo
    keys ('custom_characters/<slug>/skins' and '.../costumes') share ONE
    folder so a pose made on a bundled costume serves the added skins too."""
    slug = custom_character_slug(character)
    return f'custom_characters/{slug}' if slug else character


def poses_root():
    """The pose library root every character's poses_dir() lives under."""
    return VANILLA_ASSETS_DIR / "custom_poses"


def poses_dir(character):
    return poses_root() / pose_character_key(character)


def character_aj_file(character):
    """AJ archive for pose rendering: vanilla assets for canonical characters,
    the fighter.zip animation archive (cached) for custom characters."""
    slug = custom_character_slug(character)
    if slug:
        from core.viewer_tools import extract_custom_character_aj
        return extract_custom_character_aj(slug)
    char_prefix = CHAR_PREFIXES.get(character)
    if not char_prefix:
        return None
    return VANILLA_ASSETS_DIR / character / f"Pl{char_prefix}AJ.dat"


# ----- "Scene poses": save the baked vanilla CSP pose + a custom camera ------
#
# Scene-mode characters (DK, Mewtwo, Ganon, ...) load a baked animation from
# their csp_data/<char>/scene.yml in the viewer. A user can pose with that
# baked animation (no AJ symbol) and just rotate/scrub. Such a pose stores
# `useSceneAnimation: true` (no animSymbol). At render time we merge the
# character's scene.yml (its settings + baked `animation:` block, kept
# byte-for-byte) with the pose's camera/frame/hiddenNodes into a temp
# `scene.yml`, which the existing scene-mode render path consumes.

def character_scene_file(character):
    """The baked csp_data scene.yml for a character (canonical scene-mode
    char, or a custom char whose donor skeleton is scene-mode). None when the
    character has no baked scene — those must pose via an AJ symbol."""
    slug = custom_character_slug(character)
    if slug:
        from core.viewer_tools import custom_character_based_on
        name = custom_character_based_on(slug)
    else:
        name = character
    if not name:
        return None
    folder = name
    if name == 'Ice Climbers':
        folder = 'Ice Climbers (Popo)'
    if name == 'Mr. Game & Watch':
        folder = 'G&W'
    scene = PROCESSOR_DIR / 'csp_data' / folder / 'scene.yml'
    return scene if scene.exists() else None


def parse_pose_yaml(text):
    """Parse the flat pose YAML this module writes (frame/camera/hiddenNodes/
    flags). Hand-rolled to avoid a pyyaml dependency."""
    out = {'camera': {}, 'hiddenNodes': []}
    in_camera = False
    in_hidden = False
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw.startswith('- ') and in_hidden:
            try:
                out['hiddenNodes'].append(int(raw[2:].strip()))
            except ValueError:
                pass
            continue
        if not raw[0].isspace():
            in_camera = raw.startswith('camera:')
            in_hidden = raw.startswith('hiddenNodes:')
            if ':' in raw and not in_camera and not in_hidden:
                k, v = raw.split(':', 1)
                out[k.strip()] = v.strip()
            continue
        if in_camera and ':' in raw:
            k, v = raw.split(':', 1)
            out['camera'][k.strip()] = v.strip()
    return out


def build_scene_pose_yaml(scene_path, pose):
    """Merge a character's baked scene.yml with a pose's camera/frame/
    hiddenNodes. Keeps the scene's `settings:` + `animation:` blocks intact;
    overrides only the camera fields the pose actually sets (preserving the
    scene camera's mode/clip planes, which scene-mode render needs)."""
    lines = scene_path.read_text(encoding='utf-8', errors='replace').splitlines()
    order, tops = [], {}
    for i, l in enumerate(lines):
        if l and not l[0].isspace() and not l.startswith('-'):
            key = l.split(':', 1)[0].strip()
            tops[key] = i
            order.append(key)

    def next_after(key, eof):
        idx = order.index(key)
        return tops[order[idx + 1]] if idx + 1 < len(order) else eof

    # Camera: start from the scene's camera block, override pose-set fields
    cam = pose.get('camera') or {}
    cs, ce = tops['camera'], next_after('camera', len(lines))
    new_cam = ['camera:']
    for cl in lines[cs + 1:ce]:
        k = cl.split(':', 1)[0].strip()
        new_cam.append(f'  {k}: {cam[k]}' if k in cam else cl)

    keep_key = 'settings' if 'settings' in tops else 'animation'
    keep = lines[tops[keep_key]:next_after('animation', len(lines))]

    header = [
        f"frame: {pose.get('frame', 0)}",
        f"cSPMode: {str(pose.get('cSPMode', pose.get('cspMode', True))).lower()}",
        f"showGrid: {str(pose.get('showGrid', False)).lower()}",
        f"showBackdrop: {str(pose.get('showBackdrop', False)).lower()}",
    ] + new_cam

    footer = []
    if pose.get('hiddenNodes'):
        footer.append('hiddenNodes:')
        footer += [f'- {n}' for n in pose['hiddenNodes']]

    return '\n'.join(header + keep + footer) + '\n'


def _body_nodes(nodes, body_count):
    """The hidden DObj indices that can name a body DObj: those below the model's body DObj count."""
    return [n for n in nodes if n < body_count] if body_count else list(nodes)


def _strip_hidden_past(text, body_count):
    """A pose YAML with its ``hiddenNodes`` entries at or past ``body_count`` dropped, the rest unchanged."""
    if not body_count:
        return text
    out, in_hidden = [], False
    for line in text.splitlines():
        if line.startswith('hiddenNodes:'):
            in_hidden = True
            out.append(line)
            continue
        if in_hidden:
            match = re.match(r'-\s*(\d+)\s*$', line.strip())
            if match:
                if int(match.group(1)) < body_count:
                    out.append(line)
                continue
            if line and not line[0].isspace():
                in_hidden = False
        out.append(line)
    return '\n'.join(out) + '\n'


def render_pose_csp(dat_file, character, pose_path, aj_file, scale, no_shadow=False,
                    color_index=None, gw_colors=None):
    """Render a CSP from a saved pose. Scene poses (`useSceneAnimation: true`)
    merge the character's baked scene.yml; symbol poses go straight through the
    animSymbol+AJ path. Returns the generated CSP path or None.

    A pose's ``hiddenNodes`` were numbered by the live viewer, which keeps a costume's extra accessory DObjs
    (Jigglypuff's hats: blue's never-drawn ones are 14..23) linked after the body's and saves them as hidden. The
    CSP renderer unlinks those accessories before it numbers DObjs, so those saved indices land on the visible bow.
    Entries at or past the body's DObj count never name a body DObj; they are dropped here (2026-11-19, the blue
    Jigglypuff bow report)."""
    try:
        text = Path(pose_path).read_text(encoding='utf-8', errors='replace')
    except Exception:
        text = ''
    body = _model_dobj_count(dat_file)

    if re.search(r'(?m)^useSceneAnimation:\s*true\s*$', text):
        scene_src = character_scene_file(character)
        if scene_src is None:
            logger.warning(f"Scene pose for {character} but no baked scene.yml found")
            return None
        pose = parse_pose_yaml(text)
        pose['hiddenNodes'] = _body_nodes(pose.get('hiddenNodes') or [], body)
        tmp = tempfile.mkdtemp(prefix='scenepose_')
        try:
            scene_yml = Path(tmp) / 'scene.yml'   # name matters: triggers scene mode
            scene_yml.write_text(build_scene_pose_yaml(scene_src, pose), encoding='utf-8')
            return generate_single_csp_internal(
                str(dat_file), character, str(scene_yml), None, scale, no_shadow,
                color_index=color_index, gw_colors=gw_colors)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    aj = str(aj_file) if aj_file and Path(aj_file).exists() else None
    stripped = _strip_hidden_past(text, body) if text else text
    if not text or stripped == text or stripped == text + '\n':
        return generate_single_csp_internal(
            str(dat_file), character, str(pose_path), aj, scale, no_shadow,
            color_index=color_index, gw_colors=gw_colors)
    tmp = tempfile.mkdtemp(prefix='symbolpose_')
    try:
        pose_yml = Path(tmp) / 'pose.yml'     # NOT scene.yml: that name switches the renderer into scene mode
        pose_yml.write_text(stripped, encoding='utf-8')
        return generate_single_csp_internal(
            str(dat_file), character, str(pose_yml), aj, scale, no_shadow,
            color_index=color_index, gw_colors=gw_colors)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def camera_scene_yaml(pose):
    """A viewer scene file carrying just a pose's camera/frame/hiddenNodes (no
    baked animation). For 'start from a symbol pose': SceneSettings restores the
    camera + frame on load (it ignores the unrelated keys), and the viewer loads
    the animation separately by symbol. farClip/nearClip are spelled out because
    scene-mode load replaces the whole camera, so missing planes => 0 => broken."""
    cam = pose.get('camera') or {}
    lines = [
        f"frame: {pose.get('frame', 0)}",
        f"cSPMode: {str(pose.get('cSPMode', 'true')).lower()}",
        f"showGrid: {str(pose.get('showGrid', 'false')).lower()}",
        f"showBackdrop: {str(pose.get('showBackdrop', 'false')).lower()}",
        "camera:",
        f"  x: {cam.get('x', 0)}",
        f"  y: {cam.get('y', 10)}",
        f"  z: {cam.get('z', -80)}",
        f"  scale: {cam.get('scale', 1)}",
        f"  fovRadians: {cam.get('fovRadians', 0.5236)}",
        f"  rotationXRadians: {cam.get('rotationXRadians', 0)}",
        f"  rotationYRadians: {cam.get('rotationYRadians', 0)}",
        "  farClipPlane: 100000",
        "  nearClipPlane: 10",
    ]
    if pose.get('hiddenNodes'):
        lines.append('hiddenNodes:')
        lines += [f'- {n}' for n in pose['hiddenNodes']]
    return '\n'.join(lines) + '\n'

class Portrait(NamedTuple):
    """What a render produced, and whether the POSE was actually applied.

    `pose_applied` is not a detail: a caller that stores the result under the
    pose's name must know when it got the default instead, or it writes a
    default portrait over a posed alternate and labels it with the pose.
    """
    path: str | None
    pose_applied: bool


def render_portrait(dat_file, character, *, pose_name=None, scale=1,
                    paired_dat=None, color_index=None, gw_colors=None,
                    no_shadow=False):
    """Render `dat_file`'s portrait. Returns a `Portrait(path, pose_applied)`.

    pose_name   the costume's active pose, or None for the character default.
                A pose whose file is missing, or whose render fails, falls back
                to the default WITH `pose_applied=False` -- never silently.
    paired_dat  Ice Climbers' Nana DAT, so the composite has both climbers.
                Wins over a pose (see the module docstring), again reported.
    color_index CSS slot, used for Mr. Game & Watch's vanilla 4-colour table.
    gw_colors   an explicit G&W colour mod ({'fill': ..., 'outline': ...}),
                which overrides color_index.

    The caller owns the output file: `generate_csp` writes its output next to
    the input, so callers that must not litter render from a temp copy.
    """
    pose_path = None
    if pose_name:
        candidate = poses_dir(character) / f"{pose_name}.yml"
        if candidate.exists():
            pose_path = candidate
        else:
            logger.info(f"pose '{pose_name}' not found for {character}; rendering the default")

    if pose_path and paired_dat:
        # Posing one climber would drop the other from the composite. Keep the
        # pair (see the module docstring) and tell the caller the pose was lost.
        logger.info(f"{character}: paired composite takes precedence over pose "
                    f"'{pose_name}' -- rendering the default pose")
        pose_path = None

    if pose_path:
        out = render_pose_csp(dat_file, character, pose_path,
                              character_aj_file(character), scale, no_shadow,
                              color_index=color_index, gw_colors=gw_colors)
        if out and Path(out).exists():
            apply_character_specific_layers(out, character, scale)
            return Portrait(out, True)
        logger.warning(f"pose render failed for {character}/{pose_name}; falling back to the default")

    return Portrait(generate_csp(
        str(dat_file), scale=scale,
        paired_dat_filepath=str(paired_dat) if paired_dat else None,
        color_index=color_index, gw_colors=gw_colors), False)
