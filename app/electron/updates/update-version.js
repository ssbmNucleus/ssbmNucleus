// SemVer precedence: a stable release is newer than its matching preview.
function parseVersion(value) {
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/.exec(String(value));
  if (!match) throw new Error(`Invalid application version: ${value}`);
  const prerelease = match[4]?.split('.') || [];
  if (prerelease.some(part => /^\d+$/.test(part) && part.length > 1 && part[0] === '0')) {
    throw new Error(`Invalid application version: ${value}`);
  }
  return { core: match.slice(1, 4).map(BigInt), prerelease };
}

function compareVersions(a, b) {
  const left = parseVersion(a), right = parseVersion(b);
  for (let i = 0; i < 3; i++) {
    if (left.core[i] !== right.core[i]) return left.core[i] > right.core[i] ? 1 : -1;
  }
  const pa = left.prerelease, pb = right.prerelease;
  if (!pa.length || !pb.length) return pa.length ? -1 : pb.length ? 1 : 0;
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    if (pa[i] === undefined) return -1;
    if (pb[i] === undefined) return 1;
    if (pa[i] === pb[i]) continue;
    const na = /^\d+$/.test(pa[i]), nb = /^\d+$/.test(pb[i]);
    if (na && nb) return BigInt(pa[i]) > BigInt(pb[i]) ? 1 : -1;
    if (na !== nb) return na ? -1 : 1;
    return pa[i] > pb[i] ? 1 : -1;
  }
  return 0;
}

// What a signed update manifest may carry: X.Y.Z, or X.Y.Z-<tag> when the
// channel allows prereleases. No build metadata: it does not order, so two
// manifests differing only there would be indistinguishable to the updater.
const MANIFEST_VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

function isManifestVersion(value, { allowPrerelease = true } = {}) {
  if (typeof value !== 'string' || !MANIFEST_VERSION.test(value)) return false;
  try {
    const { prerelease } = parseVersion(value);
    return allowPrerelease || prerelease.length === 0;
  } catch {
    return false;
  }
}

function isPrerelease(value) {
  try {
    return parseVersion(value).prerelease.length > 0;
  } catch {
    return false;
  }
}

module.exports = { compareVersions, isManifestVersion, isPrerelease };
