const test = require('node:test');
const assert = require('node:assert/strict');
const { compareVersions, isManifestVersion, isPrerelease } = require('../../app/electron/updates/update-version');

test('the matching stable release upgrades a preview; an older public release does not', () => {
  for (const preview of ['0.8.2-preview.20260906.1', '0.8.2-preview.20260906.12']) {
    assert.equal(compareVersions('0.8.2', preview), 1);
    assert.equal(compareVersions(preview, '0.8.2'), -1);
    assert.equal(compareVersions('0.8.1', preview), -1);
  }
});

test('semantic prerelease ordering is numeric where required, and ignores build metadata', () => {
  const ordered = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta',
    '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0'];
  for (let i = 1; i < ordered.length; i++) assert.equal(compareVersions(ordered[i], ordered[i - 1]), 1);
  assert.equal(compareVersions('0.8.2+build.1', '0.8.2+build.2'), 0);
  assert.equal(compareVersions('0.10.0', '0.9.9'), 1);
});

test('invalid installed versions fail visibly instead of comparing as zero', () => {
  for (const invalid of ['garbage', '0.8', '0.08.2', '0.8.2-preview.01']) {
    assert.throws(() => compareVersions('0.8.2', invalid), /Invalid application version/);
  }
});

test('preview tags order numerically, and every preview is older than its release', () => {
  assert.equal(compareVersions('0.9.0-preview.10', '0.9.0-preview.9'), 1);
  assert.equal(compareVersions('0.9.0-preview.9', '0.9.0-preview.10'), -1);
  assert.equal(compareVersions('0.9.0-preview.8', '0.9.0-preview.8'), 0);
  assert.equal(compareVersions('0.9.0', '0.9.0-preview.10'), 1);
  assert.equal(compareVersions('0.9.0-preview.10', '0.8.9'), 1);
  assert.equal(compareVersions('0.9.1-preview.1', '0.9.0'), 1);
});

test('manifest versions: X.Y.Z always, X.Y.Z-<tag> only where the channel allows it', () => {
  for (const ok of ['0.9.0', '10.20.30']) {
    assert.equal(isManifestVersion(ok, { allowPrerelease: false }), true, ok);
    assert.equal(isManifestVersion(ok), true, ok);
  }
  for (const pre of ['0.9.0-preview.8', '0.9.0-preview.10', '1.0.0-rc.1', '0.8.2-preview.20260906.1']) {
    assert.equal(isManifestVersion(pre), true, pre);
    assert.equal(isManifestVersion(pre, { allowPrerelease: false }), false, pre);
  }
  for (const bad of ['', '0.9', 'v0.9.0', '0.09.0', '0.9.0-', '0.9.0-preview.08',
    '0.9.0+build.1', '0.9.0-preview.8+x', ' 0.9.0', null, undefined, 9]) {
    assert.equal(isManifestVersion(bad), false, String(bad));
  }
  assert.equal(isPrerelease('0.9.0-preview.8'), true);
  assert.equal(isPrerelease('0.9.0'), false);
  assert.equal(isPrerelease('garbage'), false);
});
