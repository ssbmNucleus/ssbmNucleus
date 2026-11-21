"""tools/build/pin_model_import_tools.py: versions in, URL + sha256 + size out, from the publishers' own files.

Everything here runs against a stand-in for the script's ``Web`` (the same three reads) backed by small fixture
texts and JSON; nothing touches the network. The committed manifest itself is test_model_import_tools_manifest.py.
"""
import base64
import importlib.util
import json
import urllib.request

import pytest

from tests.paths import REPO

_SPEC = importlib.util.spec_from_file_location('pin_model_import_tools_under_test',
                                               REPO / 'tools' / 'build' / 'pin_model_import_tools.py')
pin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pin)


def sha(n):
    """A distinct, valid sha256 hex for fixture n."""
    return f'{n:064x}'


TAG = '20261110'
BLENDER = '4.3.2'
PY_WIN = '3.13.17'
PY_PBS = '3.13.18'


class FakeWeb:
    """The script's Web with dicts instead of HTTP; an unexpected URL fails loudly."""

    def __init__(self, texts=None, jsons=None, sizes=None):
        self.texts, self.jsons, self.sizes = dict(texts or {}), dict(jsons or {}), dict(sizes or {})
        self.asked = []

    def text(self, url):
        self.asked.append(url)
        if url not in self.texts:
            raise AssertionError(f'unexpected text read: {url}')
        return self.texts[url]

    def json(self, url):
        self.asked.append(url)
        if url not in self.jsons:
            raise AssertionError(f'unexpected json read: {url}')
        return json.loads(json.dumps(self.jsons[url]))

    def size(self, url):
        self.asked.append(url)
        if url not in self.sizes:
            raise AssertionError(f'unexpected size read: {url}')
        return self.sizes[url]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('the pin tests must not reach the network')
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)


# ------------------------------------------------------------------ fixtures

def wheel(filename, n, size=1000, packagetype='bdist_wheel', yanked=False):
    return {'filename': filename, 'url': f'https://files.pythonhosted.org/packages/xx/{filename}',
            'digests': {'sha256': sha(n)}, 'size': size, 'packagetype': packagetype, 'yanked': yanked}


BPY_FILES = [
    wheel('bpy-5.2.2-cp313-cp313-win_amd64.whl', 101, 400_000_000),
    wheel('bpy-5.2.2-cp312-cp312-win_amd64.whl', 102),                      # not 3.13
    wheel('bpy-5.2.2-cp313-cp313-manylinux_2_28_x86_64.whl', 103, 410_000_000),
    wheel('bpy-5.2.2-cp313-cp313-manylinux_2_34_x86_64.whl', 104),          # above the glibc 2.28 floor
    wheel('bpy-5.2.2-cp313-cp313-musllinux_1_2_x86_64.whl', 105),           # not glibc
    wheel('bpy-5.2.2-cp313-cp313-macosx_11_0_arm64.whl', 106, 300_000_000),
    wheel('bpy-5.2.2-cp313-cp313-macosx_14_0_arm64.whl', 107),              # above the macOS 11.0 floor
    wheel('bpy-5.2.2.tar.gz', 108, packagetype='sdist'),
]
NUMPY_FILES = [
    wheel('numpy-2.5.3-cp313-cp313-win_amd64.whl', 201),
    wheel('numpy-2.5.3-cp313-cp313-manylinux_2_28_x86_64.whl', 202),
    wheel('numpy-2.5.3-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl', 203),   # lower floor wins
    wheel('numpy-2.5.3-cp313-cp313-macosx_14_0_arm64.whl', 204),
    wheel('numpy-2.5.3-cp313-cp313-macosx_11_0_arm64.whl', 205),
    wheel('numpy-2.5.3-cp313-cp313-macosx_10_13_universal2.whl', 206),     # arm64-only beats universal2
    wheel('numpy-2.5.3-py3-none-any.whl', 207),
]
ABI3_FILES = [
    wheel('stable-1.0-cp39-abi3-win_amd64.whl', 301),
    wheel('stable-1.0-cp39-abi3-manylinux_2_17_x86_64.whl', 302),
    wheel('stable-1.0-cp39-abi3-macosx_11_0_arm64.whl', 303),
    wheel('stable-1.0-py3-none-any.whl', 304),
]
PURE_FILES = [
    wheel('pure-2.0-py3-none-any.whl', 401),
    wheel('pure-2.0-py2.py3-none-any.whl', 402, yanked=True),
]

REQUIREMENTS = f"""# rigswap's packages (a fixture in the real file's format)
bpy==5.2.2 \\
    --hash=sha256:{sha(101)}
numpy==2.5.3 \\
    --hash=sha256:{sha(201)} \\
    --hash=sha256:{sha(999)}
# a comment between entries
stable==1.0 \\
    --hash=sha256:{sha(301)}
pure==2.0 \\
    --hash=sha256:{sha(401)}
"""


def blender_url(name):
    return pin.BLENDER_DIR.format(series='4.3') + name


def python_org_url(version=PY_WIN):
    return pin.PYTHON_ORG.format(v=version)


def pbs_asset(version, triple, tag=TAG, kind='install_only_stripped.tar.gz'):
    return f'cpython-{version}+{tag}-{triple}-{kind}'


LINUX, MAC = pin.PBS_TRIPLE['linux-x64'], pin.PBS_TRIPLE['osx-arm64']
PBS_ASSETS = {
    pbs_asset('3.13.9', LINUX): 30_000_000, pbs_asset('3.13.9', MAC): 20_000_000,
    pbs_asset(PY_PBS, LINUX): 35_000_000, pbs_asset(PY_PBS, MAC): 25_000_000,
    pbs_asset('3.13.19', LINUX): 36_000_000,                                   # only one platform: skipped
    pbs_asset('3.12.20', LINUX): 1, pbs_asset('3.12.20', MAC): 1,
    pbs_asset('3.14.1', LINUX): 1, pbs_asset('3.14.1', MAC): 1,
    pbs_asset(PY_PBS, LINUX + '-freethreaded'): 1, pbs_asset(PY_PBS, MAC + '-freethreaded'): 1,
    pbs_asset(PY_PBS, LINUX, kind='debug-full.tar.zst'): 1,
    pbs_asset(PY_PBS, LINUX, kind='install_only.tar.gz'): 1,
    'SHA256SUMS': 1,
}


def sigstore(hexdigest, algorithm='SHA2_256'):
    return {'mediaType': 'application/vnd.dev.sigstore.bundle+json;version=0.3',
            'messageSignature': {'messageDigest': {'algorithm': algorithm,
                                                   'digest': base64.b64encode(bytes.fromhex(hexdigest)).decode()},
                                 'signature': 'c2ln'}}


def make_web(*, blender_win_sha=sha(1), pbs_sums=None):
    names = {'win-x64': f'blender-{BLENDER}-windows-x64.zip', 'linux-x64': f'blender-{BLENDER}-linux-x64.tar.xz',
             'osx-arm64': f'blender-{BLENDER}-macos-arm64.dmg'}
    blender_sums = '\n'.join([f'{blender_win_sha}  {names["win-x64"]}', f'{sha(2)}  {names["linux-x64"]}',
                              f'{sha(3)}  {names["osx-arm64"]}', f'{sha(4)}  blender-{BLENDER}-macos-x64.dmg', ''])
    sums = pbs_sums if pbs_sums is not None else '\n'.join(
        f'{sha(500 + i)}  {name}' for i, name in enumerate(sorted(PBS_ASSETS)) if name != 'SHA256SUMS')
    release = {'tag_name': TAG, 'assets': [{'name': n, 'size': s} for n, s in PBS_ASSETS.items()]}
    files = {'bpy': BPY_FILES, 'numpy': NUMPY_FILES, 'stable': ABI3_FILES, 'pure': PURE_FILES}
    versions = {'bpy': '5.2.2', 'numpy': '2.5.3', 'stable': '1.0', 'pure': '2.0'}
    return FakeWeb(
        texts={blender_url(f'blender-{BLENDER}.sha256'): blender_sums,
               pin.PBS_FILE.format(tag=TAG, name='SHA256SUMS'): sums},
        jsons={python_org_url() + '.sigstore': sigstore(sha(7)),
               pin.PBS_API.format(which=f'tags/{TAG}'): release,
               pin.PBS_API.format(which='latest'): release,
               **{pin.PYPI.format(name=n, version=versions[n]): {'urls': f} for n, f in files.items()}},
        sizes={**{blender_url(n): 100_000_000 + i for i, n in enumerate(names.values())},
               python_org_url(): 11_000_000})


def fixture_manifest():
    return {'_README': ['fixture'], 'schema': 1,
            'pin': {'blender': BLENDER, 'python': {'win-x64': PY_WIN, 'linux-x64': PY_PBS, 'osx-arm64': PY_PBS},
                    'python_build_standalone': TAG, 'requirements': 'utility/rigswap.requirements.txt'},
            'license': {'notice': 'THIRD_PARTY_NOTICES.md'}}


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """The script reads the requirements file from APP/<pin.requirements>: point APP at a fixture."""
    app = tmp_path / 'app'
    (app / 'utility').mkdir(parents=True)
    (app / 'utility' / 'rigswap.requirements.txt').write_text(REQUIREMENTS, encoding='utf-8')
    monkeypatch.setattr(pin, 'APP', app)
    return app


# ------------------------------------------------------------------ requirements

def test_requirements_parses_continuation_lines_comments_and_hashes(tmp_path):
    path = tmp_path / 'r.txt'
    path.write_bytes(REQUIREMENTS.replace('\n', '\r\n').encode('utf-8'))     # a CRLF checkout
    assert pin.requirements(path) == [('bpy', '5.2.2', {sha(101)}), ('numpy', '2.5.3', {sha(201), sha(999)}),
                                      ('stable', '1.0', {sha(301)}), ('pure', '2.0', {sha(401)})]


def test_requirements_take_unhashed_pins_and_refuse_an_unpinned_line(tmp_path):
    path = tmp_path / 'r.txt'
    path.write_text('requests==2.34.2  # no hash\nattrs==26.1.0\n', encoding='utf-8')
    assert pin.requirements(path) == [('requests', '2.34.2', set()), ('attrs', '26.1.0', set())]
    path.write_text('requests>=2\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='not a pinned requirement'):
        pin.requirements(path)


def test_the_real_requirements_file_parses_with_one_hash_each():
    reqs = pin.requirements(REPO / 'app' / 'utility' / 'rigswap.requirements.txt')
    names = [name for name, _, _ in reqs]
    assert {'bpy', 'numpy', 'pillow', 'requests'} <= set(names)
    assert len(names) == len(set(names))
    assert all(len(hashes) == 1 for _, _, hashes in reqs)
    assert dict((n, v) for n, v, _ in reqs)['bpy'] == '5.2.2'


# ------------------------------------------------------------------ wheels

@pytest.mark.parametrize('platform, expected', [
    ('win-x64', 'bpy-5.2.2-cp313-cp313-win_amd64.whl'),
    ('linux-x64', 'bpy-5.2.2-cp313-cp313-manylinux_2_28_x86_64.whl'),
    ('osx-arm64', 'bpy-5.2.2-cp313-cp313-macosx_11_0_arm64.whl'),
])
def test_pick_wheel_takes_cpython_313_within_the_os_floors(platform, expected):
    assert pin.pick_wheel(BPY_FILES, platform, 'bpy', '5.2.2')['filename'] == expected


@pytest.mark.parametrize('platform, expected', [
    ('win-x64', 'numpy-2.5.3-cp313-cp313-win_amd64.whl'),
    ('linux-x64', 'numpy-2.5.3-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl'),
    ('osx-arm64', 'numpy-2.5.3-cp313-cp313-macosx_11_0_arm64.whl'),
])
def test_pick_wheel_prefers_a_platform_wheel_then_the_lower_floor_and_arm64_over_universal2(platform, expected):
    assert pin.pick_wheel(NUMPY_FILES, platform, 'numpy', '2.5.3')['filename'] == expected


def test_pick_wheel_prefers_the_lower_floor_between_two_arm64_wheels():
    files = [wheel('x-1-cp313-cp313-macosx_11_0_arm64.whl', 1), wheel('x-1-cp313-cp313-macosx_10_9_arm64.whl', 2)]
    assert pin.pick_wheel(files, 'osx-arm64', 'x', '1')['filename'].endswith('macosx_10_9_arm64.whl')


def test_pick_wheel_order_is_cp313_then_abi3_then_pure():
    with_cp313 = [*ABI3_FILES, wheel('stable-1.0-cp313-cp313-win_amd64.whl', 309)]
    assert pin.pick_wheel(with_cp313, 'win-x64', 'stable', '1.0')['filename'] == 'stable-1.0-cp313-cp313-win_amd64.whl'
    for platform, tail in (('win-x64', 'win_amd64'), ('linux-x64', 'manylinux_2_17_x86_64'),
                           ('osx-arm64', 'macosx_11_0_arm64')):
        assert pin.pick_wheel(ABI3_FILES, platform, 'stable', '1.0')['filename'] == f'stable-1.0-cp39-abi3-{tail}.whl'
    for platform in pin.PLATFORMS:
        assert pin.pick_wheel(PURE_FILES, platform, 'pure', '2.0')['filename'] == 'pure-2.0-py3-none-any.whl'


def test_pick_wheel_refuses_when_nothing_fits():
    losers = [f for f in BPY_FILES if '_2_34_' in f['filename'] or 'musllinux' in f['filename']
              or 'cp312' in f['filename'] or f['packagetype'] == 'sdist']
    with pytest.raises(SystemExit, match='no bpy 5.2.2 wheel for CPython 3.13 on linux-x64'):
        pin.pick_wheel(losers, 'linux-x64', 'bpy', '5.2.2')
    with pytest.raises(SystemExit):
        pin.pick_wheel([wheel('old-1-cp312-abi3-win_amd64.whl', 1)], 'osx-arm64', 'old', '1')
    yanked = [wheel('y-1-py3-none-any.whl', 1, yanked=True)]
    with pytest.raises(SystemExit):
        pin.pick_wheel(yanked, 'win-x64', 'y', '1')


def test_pin_wheels_takes_the_requirements_hash_on_windows(app_dir):
    reqs = pin.requirements(app_dir / 'utility' / 'rigswap.requirements.txt')
    wheels = pin.pin_wheels(make_web(), 'win-x64', reqs)
    assert [(w['name'], w['version'], w['sha256']) for w in wheels] == [
        ('bpy', '5.2.2', sha(101)), ('numpy', '2.5.3', sha(201)), ('stable', '1.0', sha(301)), ('pure', '2.0', sha(401))]
    assert all(w['url'].endswith('/' + w['filename']) and w['size'] > 0 for w in wheels)


def test_pin_wheels_refuses_a_windows_hash_that_is_not_the_picked_wheel(app_dir):
    web = make_web()
    # the requirements pin the cp312 wheel's sha: PyPI has it, but it is not what a 3.13 installs
    with pytest.raises(SystemExit, match='bpy 5.2.2: the requirements file pins a hash that is not the win-x64'):
        pin.pin_wheels(web, 'win-x64', [('bpy', '5.2.2', {sha(102)})])
    with pytest.raises(SystemExit, match='not the win-x64'):
        pin.pin_wheels(web, 'win-x64', [('bpy', '5.2.2', {sha(12345)})])


def test_pin_wheels_ignores_the_windows_hash_on_other_platforms(app_dir):
    wheels = pin.pin_wheels(make_web(), 'linux-x64', [('bpy', '5.2.2', {sha(12345)})])
    assert wheels[0]['sha256'] == sha(103)


# ------------------------------------------------------------------ Python, Blender

def test_sigstore_sha256_decodes_the_message_digest():
    web = FakeWeb(jsons={'https://x/y.zip.sigstore': sigstore(sha(77))})
    assert pin.sigstore_sha256(web, 'https://x/y.zip') == sha(77)


def test_sigstore_sha256_refuses_another_algorithm_or_no_digest():
    web = FakeWeb(jsons={'https://x/a.zip.sigstore': sigstore(sha(1), algorithm='SHA2_512'),
                         'https://x/b.zip.sigstore': {'messageSignature': {}}, 'https://x/c.zip.sigstore': {}})
    for name in 'abc':
        with pytest.raises(SystemExit, match='no SHA2_256 digest'):
            pin.sigstore_sha256(web, f'https://x/{name}.zip')


def test_newest_313_takes_the_newest_patch_every_platform_has():
    # 3.13.19 is linux-only, 3.13.9 sorts below 3.13.18 numerically, 3.12/3.14/freethreaded are not candidates
    assert pin.newest_313(PBS_ASSETS, TAG) == PY_PBS


def test_newest_313_refuses_a_release_without_one():
    with pytest.raises(SystemExit, match='no CPython 3.13'):
        pin.newest_313({pbs_asset('3.13.18', LINUX): 1, pbs_asset('3.12.1', MAC): 1}, TAG)
    with pytest.raises(SystemExit):
        pin.newest_313(PBS_ASSETS, 'another-tag')


def test_blender_sums_reads_the_checksum_file_and_refuses_an_empty_one():
    web = make_web()
    sums = pin.blender_sums(web, BLENDER)
    assert sums[f'blender-{BLENDER}-windows-x64.zip'] == sha(1)
    assert len(sums) == 4
    empty = FakeWeb(texts={blender_url(f'blender-{BLENDER}.sha256'): '<html>not found</html>'})
    with pytest.raises(SystemExit, match='lists no checksums'):
        pin.blender_sums(empty, BLENDER)


def test_pin_blender_refuses_a_platform_the_checksum_file_lacks():
    with pytest.raises(SystemExit, match='has no blender-4.3.2-linux-x64.tar.xz'):
        pin.pin_blender(make_web(), 'linux-x64', BLENDER, {f'blender-{BLENDER}-windows-x64.zip': sha(1)})


def test_pin_pbs_refuses_an_asset_without_a_checksum():
    with pytest.raises(SystemExit, match='no checksum'):
        pin.pin_pbs('linux-x64', PY_PBS, TAG, PBS_ASSETS, {})


# ------------------------------------------------------------------ resolve and main

def test_resolve_fills_url_sha256_and_size_for_every_platform(app_dir):
    resolved = pin.resolve(fixture_manifest(), make_web(), log=lambda *_: None)
    assert resolved['license'] == {'notice': 'THIRD_PARTY_NOTICES.md'} and resolved['_README'] == ['fixture']
    assert set(resolved['platforms']) == set(pin.PLATFORMS)
    for platform, entry in resolved['platforms'].items():
        items = [entry['blender'], entry['python'], *entry['wheels']]
        for item in items:
            assert item['url'].startswith('https://'), (platform, item)
            assert len(item['sha256']) == 64 and item['size'] > 0, (platform, item)
        assert entry['blender']['version'] == BLENDER
        assert [w['name'] for w in entry['wheels']] == ['bpy', 'numpy', 'stable', 'pure']
    win, linux, mac = (resolved['platforms'][p] for p in pin.PLATFORMS)
    assert win['python']['url'] == python_org_url() and win['python']['sha256'] == sha(7)
    assert win['python']['size'] == 11_000_000 and win['python']['kind'] == 'embeddable'
    assert win['blender']['sha256'] == sha(1) and win['blender']['root'] == f'blender-{BLENDER}-windows-x64'
    assert win['blender']['trim'][0] == 'blender.pdb' and '4.3/datafiles/locale' in win['blender']['trim']
    assert linux['python']['url'] == pin.PBS_FILE.format(tag=TAG, name=pbs_asset(PY_PBS, LINUX))
    assert linux['python']['size'] == PBS_ASSETS[pbs_asset(PY_PBS, LINUX)] and linux['python']['release'] == TAG
    assert linux['wheels'][0]['filename'].endswith('manylinux_2_28_x86_64.whl')
    assert mac['blender']['entrypoint'] == 'Blender.app/Contents/MacOS/Blender' and mac['blender']['trim'] == []
    assert all(p.startswith('Blender.app/Contents/Resources/4.3/') for p in mac['blender']['verify'])
    assert mac['wheels'][1]['filename'].endswith('macosx_11_0_arm64.whl')


def test_main_writes_then_check_passes_and_a_moved_pin_fails_check(app_dir, capsys):
    path = app_dir / 'utility' / 'model_import_tools.json'
    path.write_text(json.dumps(fixture_manifest()), encoding='utf-8')
    assert pin.main(['--manifest', str(path)], web=make_web()) == 0
    written = path.read_text(encoding='utf-8')
    assert json.loads(written)['platforms']['win-x64']['blender']['sha256'] == sha(1)
    assert pin.main(['--check', '--manifest', str(path)], web=make_web()) == 0
    assert 'ok: the manifest matches its pins' in capsys.readouterr().out
    # Blender re-published under the same name: the manifest is now stale, and --check never writes
    assert pin.main(['--check', '--manifest', str(path)], web=make_web(blender_win_sha=sha(9))) == 1
    assert 'STALE' in capsys.readouterr().out
    assert path.read_text(encoding='utf-8') == written


def test_main_pbs_latest_moves_to_the_newest_313(app_dir):
    path = app_dir / 'utility' / 'model_import_tools.json'
    manifest = fixture_manifest()
    manifest['pin']['python'].update({'linux-x64': '3.13.9', 'osx-arm64': '3.13.9'})
    manifest['pin']['python_build_standalone'] = 'older'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    web = make_web()
    assert pin.main(['--pbs', 'latest', '--manifest', str(path)], web=web) == 0
    written = json.loads(path.read_text(encoding='utf-8'))
    assert written['pin']['python_build_standalone'] == TAG
    assert written['pin']['python'] == {'win-x64': PY_WIN, 'linux-x64': PY_PBS, 'osx-arm64': PY_PBS}
    assert pin.PBS_API.format(which='latest') in web.asked


def test_totals_add_blender_python_and_wheels():
    manifest = {'platforms': {'win-x64': {'blender': {'size': 5}, 'python': {'size': 3},
                                          'wheels': [{'size': 1}, {'size': 2}]}}}
    assert pin.totals(manifest) == {'win-x64': 11}
    assert pin.totals({}) == {}


# ------------------------------------------------------------------ measured on disk (0.9.0 build 3: the card's size)

def _receipt(entry, platform, sizes=(1_206_851_569, 1_113_277_867), changes=None):
    """An install's receipt.json (assemble.write_receipt's shape) for ``entry``; ``changes``: {piece: {key: value}}."""
    receipt = {'schema': 1, 'platform': platform,
               'blender': {'version': entry['blender']['version'], 'sha256': entry['blender']['sha256'],
                           'bytes_on_disk': sizes[0]},
               'runtime': {'key': pin.runtime_key(entry), 'bytes_on_disk': sizes[1]},
               'bytes_on_disk': sum(sizes)}
    for piece, values in (changes or {}).items():
        receipt[piece].update(values)
    return receipt


def test_measured_records_each_piece_of_the_pinned_downloads(app_dir, tmp_path, capsys):
    path = app_dir / 'utility' / 'model_import_tools.json'
    path.write_text(pin.dump(pin.resolve(fixture_manifest(), make_web(), log=lambda *_: None)), encoding='utf-8')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    linux, win = manifest['platforms']['linux-x64'], manifest['platforms']['win-x64']
    receipts = tmp_path / 'linux.json', tmp_path / 'win.json'
    receipts[0].write_text(json.dumps(_receipt(linux, 'linux-x64')), encoding='utf-8')
    receipts[1].write_text(json.dumps(_receipt(win, 'win-x64', (779_823_617, 761_981_130),
                                               {'runtime': {'key': 'another0runtime0'}})), encoding='utf-8')
    assert pin.main(['--measured', *map(str, receipts), '--manifest', str(path)]) == 0
    written = json.loads(path.read_text(encoding='utf-8'))['platforms']
    assert written['linux-x64']['on_disk'] == {
        'blender': {'sha256': linux['blender']['sha256'], 'bytes': 1_206_851_569},
        'runtime': {'key': pin.runtime_key(linux), 'bytes': 1_113_277_867}}
    assert written['win-x64']['on_disk'] == {'blender': {'sha256': win['blender']['sha256'], 'bytes': 779_823_617}}
    assert 'not of the pinned runtime' in capsys.readouterr().out
    assert 'on_disk' not in written['osx-arm64']
    assert pin.main(['--measured', str(receipts[0]), '--check', '--manifest', str(path)]) == 0
    # a receipt of other downloads than the manifest's records nothing
    other = tmp_path / 'other.json'
    other.write_text(json.dumps(_receipt(linux, 'linux-x64', changes={'blender': {'sha256': sha(77)},
                                                             'runtime': {'key': 'another0runtime0'}})), encoding='utf-8')
    with pytest.raises(SystemExit, match="neither piece is the manifest's linux-x64 pin"):
        pin.main(['--measured', str(other), '--manifest', str(path)])
    other.write_text(json.dumps(_receipt(linux, 'linux-riscv64')), encoding='utf-8')
    with pytest.raises(SystemExit, match='not in the manifest'):
        pin.main(['--measured', str(other), '--manifest', str(path)])


def test_a_re_pin_keeps_a_measured_size_only_while_its_downloads_stay(app_dir):
    resolved = pin.resolve(fixture_manifest(), make_web(), log=lambda *_: None)
    measured = pin.record_measured(resolved, [], log=lambda *_: None)
    for platform, entry in measured['platforms'].items():
        entry['on_disk'] = {'blender': {'sha256': entry['blender']['sha256'], 'bytes': 1000},
                            'runtime': {'key': pin.runtime_key(entry), 'bytes': 2000}}
    again = pin.resolve(measured, make_web(), log=lambda *_: None)
    assert pin.dump(again) == pin.dump(measured), 'nothing moved: every size stays, and --check passes'
    # Blender re-published for Windows: its size goes, the runtime's stays
    moved = pin.resolve(measured, make_web(blender_win_sha=sha(9)), log=lambda *_: None)
    assert moved['platforms']['win-x64']['on_disk'] == {'runtime': measured['platforms']['win-x64']['on_disk']['runtime']}
    # a new trim list changes what Blender leaves on disk
    trimmed = json.loads(json.dumps(measured))
    trimmed['platforms']['linux-x64']['blender']['trim'] = ['something/else']
    assert 'blender' not in pin.resolve(trimmed, make_web(), log=lambda *_: None)['platforms']['linux-x64']['on_disk']
    # a wheel moved: a new runtime key, so the runtime's size goes
    stale = json.loads(json.dumps(measured))
    stale['platforms']['osx-arm64']['on_disk']['runtime']['key'] = 'another0runtime0'
    assert 'runtime' not in pin.resolve(stale, make_web(), log=lambda *_: None)['platforms']['osx-arm64']['on_disk']


def test_the_pin_script_keys_a_runtime_as_the_app_does():
    from randall.model_import.tools import assemble
    entry = {'python': {'version': '3.13.18', 'sha256': sha(1)}, 'wheels': [{'name': 'bpy', 'version': '5.2.2'}],
             'blender': {'sha256': sha(2)}}
    assert pin.runtime_key(entry) == assemble.runtime_key(entry)
