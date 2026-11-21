"""Slap City's files (Unity 2020.3, Mono, serialized format 22, no type trees), read through UnityPy.

UnityPy reads Unity's own types (GameObject, Transform, Mesh, Texture2D, AnimationClip, AudioClip). The game's own
classes (MonoBehaviours: the fighter, its attack properties, its skins) carry no type tree in a player build, so
UnityPy's TypeTreeGenerator makes one from the game's own `Managed/*.dll`. Two faults of the generator for this
build are mended here (found 2026-11-13 by reading field by field until the read went wrong):
  - `m_Enabled` (a byte) is not marked to align, so every field after it is read four bytes early
    (`m_Script` came out as garbage): it is given the align flag.
  - a `string[]` field is typed "string" with an array of strings under it: it is read as an array.
UnityPy's C reader also fails on such trees, so the pure Python reader is used (a few seconds more).

UnityPy is not in the app's Python: it is installed into its own folder (`pip install --target <folder> UnityPy`,
with TypeTreeGeneratorAPI for the generator) and found through the UNITY_PYDEPS environment variable.

Nothing here writes under the game's folder.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

VERSION = '2020.3.36f1'
FILES = ('globalgamemanagers', 'globalgamemanagers.assets', 'resources.assets', 'sharedassets0.assets')
ALIGN = 0x4000                  # a type tree node's "align after me" flag


def unitypy():
    """The UnityPy module, from the app's Python or from UNITY_PYDEPS."""
    try:
        import UnityPy
    except ImportError:
        deps = os.environ.get('UNITY_PYDEPS')
        if not deps or not Path(deps).is_dir():
            raise SystemExit('reading a Unity game needs UnityPy: install it into a folder of its own '
                             '(python -m pip install --target <folder> UnityPy TypeTreeGeneratorAPI) and set '
                             'UNITY_PYDEPS to that folder')
        sys.path.insert(0, deps)
        import UnityPy
    import UnityPy.helpers.TypeTreeHelper as helper
    helper.read_typetree_boost = None           # the C reader fails on the generated trees (see above)
    return UnityPy


def mend(node):
    """The generated type tree of a MonoBehaviour, with the generator's two faults for this build mended."""
    for child in node.m_Children:
        if child.m_Name == 'm_Enabled':
            child.m_MetaFlag |= ALIGN

    def walk(n):
        kids = n.m_Children or []
        if (n.m_Type == 'string' and kids and kids[0].m_Type == 'Array' and len(kids[0].m_Children) > 1
                and kids[0].m_Children[1].m_Type != 'char'):
            n.m_Type = 'vector'
        for k in kids:
            walk(k)
    walk(node)
    return node


class Game:
    """The game's data folder (`<game>/<name>_Data`), opened once. `files`: {file name: UnityPy's SerializedFile}."""

    def __init__(self, data_dir, names=FILES):
        self.dir = Path(data_dir)
        if not (self.dir / 'globalgamemanagers').is_file():
            raise FileNotFoundError(f'{self.dir} is not a Unity data folder (it has no globalgamemanagers)')
        UnityPy = unitypy()
        from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
        self.env = UnityPy.load(*[str(self.dir / n) for n in names])
        generator = TypeTreeGenerator(VERSION)
        generator.load_local_dll_folder(str(self.dir / 'Managed'))
        self.env.typetree_generator = generator
        self.files = {os.path.basename(k): v for k, v in self.env.files.items()}
        self._container = None
        self._classes = {}
        fmod()                                          # before any picture is decoded (see fmod)

    # ---- where things are
    def file_of(self, owner, file_id):
        """The file a reference (`file_id` as written in `owner`) points into."""
        if file_id == 0:
            return owner
        return self.files.get(os.path.basename(owner.externals[file_id - 1].path))

    def deref(self, owner, ref):
        """{'m_FileID', 'm_PathID'} (or UnityPy's PPtr) written in `owner` -> the ObjectReader, or None."""
        fid = ref['m_FileID'] if isinstance(ref, dict) else ref.m_FileID
        pid = ref['m_PathID'] if isinstance(ref, dict) else ref.m_PathID
        if not pid:
            return None
        f = self.file_of(owner, fid)
        return None if f is None else f.objects.get(pid)

    def container(self):
        """{asset path: ObjectReader} from the ResourceManager (the game's `Resources` folder by name)."""
        if self._container is None:
            gm = self.files['globalgamemanagers']
            manager = next(o for o in gm.objects.values() if o.type.name == 'ResourceManager')
            self._container = {}
            for path, ref in manager.read_typetree()['m_Container']:
                obj = self.deref(gm, ref)
                if obj is not None:
                    self._container[path] = obj
        return self._container

    # ---- the game's own classes
    def script(self, obj):
        """The class name of a MonoBehaviour (read from its raw head: m_Script sits at byte 16)."""
        fid, pid = struct.unpack_from('<iq', obj.get_raw_data(), 16)
        key = (id(obj.assets_file), fid, pid)
        if key not in self._classes:
            target = self.deref(obj.assets_file, {'m_FileID': fid, 'm_PathID': pid})
            self._classes[key] = target.read().m_ClassName if target is not None else None
        return self._classes[key]

    def mono(self, obj):
        """A MonoBehaviour's fields as a dict (the generated type tree, mended)."""
        return obj.read_typetree(nodes=mend(obj._get_typetree_node()))


_FMOD = {}


def fmod():
    """The process's one FMOD system (32 voices; `Game` makes it as it opens the game). Found, not explained: once
    UnityPy has decoded a picture in the process, FMOD refuses clips (FORMAT for the fighter's sounds, INVALID PARAM
    for the fanfare) unless it had already decoded clips before the picture. So the reader decodes every sound
    before any picture (__main__: sounds, then identity with the fanfare before its picture, then the bodies)."""
    if 'system' not in _FMOD:
        unitypy()
        from fmod_toolkit.importer import import_pyfmodex
        pf = import_pyfmodex()
        system = pf.System()
        system.init(32, pf.flags.INIT_FLAGS.NORMAL, None)
        _FMOD['system'] = system
    return _FMOD['system']


def audio(clip):
    """An AudioClip as WAV bytes (its first sound), decoded by the FMOD library UnityPy carries.
    Not `clip.samples`: that opens FMOD with as many voices as the clip has channels, and FMOD then refuses a long
    stereo Vorbis clip (INVALID PARAM: the victory fanfare); with 32 voices it decodes it. One FMOD for the process."""
    unitypy()
    from fmod_toolkit import fmod as fm
    from fmod_toolkit.importer import import_pyfmodex
    from UnityPy.helpers.ResourceReader import get_resource_data
    pf = import_pyfmodex()
    if clip.m_AudioData:
        data = bytes(clip.m_AudioData)
    else:
        r = clip.m_Resource
        data = bytes(get_resource_data(r.m_Source, clip.object_reader.assets_file, r.m_Offset, r.m_Size))
    if data[:4] == b'RIFF':
        return data
    sound = fmod().create_sound(data, pf.flags.MODE.OPENMEMORY, exinfo=pf.structure_declarations.CREATESOUNDEXINFO(
        length=len(data), numchannels=int(clip.m_Channels), defaultfrequency=int(clip.m_Frequency)))
    try:
        return next(iter(fm.sound_to_wav(sound, clip.m_Name).values()))
    finally:
        sound.release()
