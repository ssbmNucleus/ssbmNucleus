import configparser

import shared.ingame.boot as boot


def _prepared_boot(monkeypatch, tmp_path, template):
    monkeypatch.setattr(
        boot, 'resolve_dolphin',
        lambda _slippi_path: ('C:/fake/Slippi Dolphin.exe', str(template)))
    instance = boot.DolphinBoot(
        'fake.iso', 'C:/fake', tmp_path / 'runs', pipe_index=7)
    return instance.prepare()


def test_prepare_copies_gc_into_throwaway_user(monkeypatch, tmp_path):
    template = tmp_path / 'template' / 'User'
    gc = template / 'GC'
    gc.mkdir(parents=True)
    (gc / 'MemoryCardA.USA.raw').write_bytes(b'memory-card')
    (gc / 'SRAM.raw').write_bytes(b'sram')

    prepared = _prepared_boot(monkeypatch, tmp_path, template)
    copied_gc = prepared.user_dir / 'GC'

    assert (copied_gc / 'MemoryCardA.USA.raw').read_bytes() == b'memory-card'
    assert (copied_gc / 'SRAM.raw').read_bytes() == b'sram'

    # The isolated card is a real copy: changing it cannot mutate the template.
    (copied_gc / 'MemoryCardA.USA.raw').write_bytes(b'isolated-change')
    assert (gc / 'MemoryCardA.USA.raw').read_bytes() == b'memory-card'


def test_prepare_allows_template_without_gc(monkeypatch, tmp_path):
    template = tmp_path / 'template' / 'User'
    (template / 'Config').mkdir(parents=True)

    prepared = _prepared_boot(monkeypatch, tmp_path, template)

    assert prepared.user_dir.is_dir()
    assert not (prepared.user_dir / 'GC').exists()


def test_separate_render_surface_preserves_real_graphics_profile(monkeypatch, tmp_path):
    template = tmp_path / 'template' / 'User'
    config = template / 'Config'
    config.mkdir(parents=True)
    dolphin = b'[Core]\nGFXBackend = OGL\n[Display]\nRenderToMain = True\n'
    gfx = b'[Hardware]\nadapter = 2\n'
    (config / 'Dolphin.ini').write_bytes(dolphin)
    (config / 'GFX.ini').write_bytes(gfx)
    prepared = _prepared_boot(monkeypatch, tmp_path, template)
    copied = (prepared.user_dir / 'Config' / 'Dolphin.ini').read_text(encoding='utf-8')
    assert 'RenderToMain = False' in copied
    assert 'GFXBackend = OGL' in copied
    assert (prepared.user_dir / 'Config' / 'GFX.ini').read_bytes() == gfx
    assert (config / 'Dolphin.ini').read_bytes() == dolphin
    assert (config / 'GFX.ini').read_bytes() == gfx


# The shape of a Slippi User dir whose log channels were all toggled on (the
# 0.9.0 smoke test's template: 28.8 MB of PowerPC exceptions in 3 minutes).
ALL_CHANNELS_ON = """[LogWindow]
x = 743
y = 557
pos = 2
[Options]
Font = 0
WrapLines = False
Verbosity = 3
WriteToFile = True
WriteToConsole = True
WriteToWindow = True
[Logs]
ActionReplay = True
BOOT = True
DVD = True
EXI = True
FileMon = True
Host GPU = True
MemCard Manager = True
HLE = True
OSREPORT = True
PowerPC = True
SLIPPI = True
SLIPPI_ONLINE = True
"""


def _logger(user_dir):
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str
    cfg.read(user_dir / 'Config' / 'Logger.ini', encoding='utf-8')
    return cfg


def test_prepare_logs_only_osreport_whatever_the_template_enables(monkeypatch, tmp_path):
    template = tmp_path / 'template' / 'User'
    (template / 'Config').mkdir(parents=True)
    (template / 'Config' / 'Logger.ini').write_text(ALL_CHANNELS_ON, encoding='utf-8')

    prepared = _prepared_boot(monkeypatch, tmp_path, template)
    cfg = _logger(prepared.user_dir)

    assert cfg['Options']['WriteToFile'] == 'True'
    assert cfg['Options']['WriteToConsole'] == 'False'
    assert cfg['Options']['Verbosity'] == '4'   # every OSReport line, Info included
    logs = dict(cfg['Logs'])
    assert logs.pop('OSREPORT') == 'True'
    assert logs.pop('OSREPORT_HLE') == 'True'
    assert logs['PowerPC'] == 'False'
    assert logs['EXI'] == 'False'
    assert logs['Host GPU'] == 'False'          # names with spaces survive the rewrite
    assert set(logs.values()) == {'False'}
    # Only the run's copy changes; the user's own Dolphin keeps its settings.
    assert (template / 'Config' / 'Logger.ini').read_text(encoding='utf-8') == ALL_CHANNELS_ON


def test_logger_ini_without_a_template_names_only_osreport(tmp_path):
    (tmp_path / 'Config').mkdir()

    boot._patch_logger_ini(str(tmp_path))

    cfg = _logger(tmp_path)
    assert dict(cfg['Logs']) == {'OSREPORT': 'True', 'OSREPORT_HLE': 'True'}
    assert cfg['Options']['Verbosity'] == '4'


def test_logger_ini_channel_names_compare_without_case(tmp_path):
    (tmp_path / 'Config').mkdir()
    (tmp_path / 'Config' / 'Logger.ini').write_text(
        '[Logs]\nosreport = False\npowerpc = True\n', encoding='utf-8')

    boot._patch_logger_ini(str(tmp_path))

    logs = dict(_logger(tmp_path)['Logs'])
    # The template's own spelling is turned on, not shadowed by a second key.
    assert logs == {'osreport': 'True', 'powerpc': 'False', 'OSREPORT_HLE': 'True'}
