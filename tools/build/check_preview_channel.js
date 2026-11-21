// Post-package gate for the secret preview update channel (build.bat).
//
//   node tools/build/check_preview_channel.js <resources dir>
//
// Reads the PACKAGED package.json (app.asar, or an unpacked app/ folder) and
// fails the build unless it carries exactly what the environment asked for:
//   - NUCLEUS_PREVIEW_CHANNEL set: previewChannel is that exact STRING,
//     previewFeatures is present and the version has a prerelease tag.
//     electron-builder's CLI coerces some values (all-digit, 0x...) to
//     numbers, which the updater would silently ignore, leaving testers
//     without updates.
//   - NUCLEUS_PREVIEW_CHANNEL unset: no previewChannel at all, so a stable
//     build can never locate the preview channel.
// Never prints the token.
const fs = require('fs');
const path = require('path');

function checkPackagedManifest(manifest, expectedToken) {
  const channel = manifest ? manifest.previewChannel : undefined;
  if (!expectedToken) {
    return channel === undefined ? null
      : 'packaged package.json carries previewChannel but NUCLEUS_PREVIEW_CHANNEL is not set';
  }
  if (channel !== expectedToken) {
    return `packaged previewChannel is not the NUCLEUS_PREVIEW_CHANNEL string (got a ${typeof channel})`;
  }
  const features = manifest.previewFeatures;
  const hasFeatures = Array.isArray(features) ? features.length > 0
    : typeof features === 'string' && features.trim().length > 0;
  if (!hasFeatures) return 'packaged previewChannel without previewFeatures';
  // A preview packaged as plain X.Y.Z would never see X.Y.Z stable as newer,
  // so testers could not move on; the channel needs a prerelease version.
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*$/
    .test(String(manifest.version))) {
    return `packaged previewChannel on a version without a prerelease tag (${manifest.version})`;
  }
  return null;
}

function readPackagedManifest(resourcesDir, requireFrom) {
  const unpacked = path.join(resourcesDir, 'app', 'package.json');
  if (fs.existsSync(unpacked)) return JSON.parse(fs.readFileSync(unpacked, 'utf8'));
  const asarPath = path.join(resourcesDir, 'app.asar');
  // @electron/asar ships with electron-builder in the project's node_modules.
  const asar = require(require.resolve('@electron/asar', { paths: [requireFrom] }));
  return JSON.parse(asar.extractFile(asarPath, 'package.json').toString('utf8'));
}

if (require.main === module) {
  const resourcesDir = process.argv[2];
  const projectRoot = path.resolve(__dirname, '..', '..', 'app');
  try {
    const error = checkPackagedManifest(
      readPackagedManifest(resourcesDir, projectRoot),
      process.env.NUCLEUS_PREVIEW_CHANNEL || '',
    );
    if (error) {
      console.error(`ERROR: ${error}`);
      process.exit(1);
    }
    console.log(process.env.NUCLEUS_PREVIEW_CHANNEL
      ? 'Packaged manifest carries the secret preview update channel.'
      : 'Packaged manifest carries no preview update channel.');
  } catch (error) {
    console.error(`ERROR: could not read the packaged package.json: ${error.message}`);
    process.exit(1);
  }
}

module.exports = { checkPackagedManifest, readPackagedManifest };
