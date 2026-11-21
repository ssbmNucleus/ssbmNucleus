/**
 * appControl.js — say plainly when Windows refused to load a file Nucleus ships.
 *
 * Windows Smart App Control (and App Control for Business) loads an exe or dll
 * only when it is code-signed or Microsoft's reputation service vouches for it.
 * When it refuses one, the tool that needed it (m-ex, the 3D viewer, the
 * backend) fails with Windows error 0x800711C7 (Win32 4551) and a .NET or Python
 * message naming the file. 0.8.15 showed that raw text and nothing else (bug
 * report ee46f7d3: every new project failed on utility\mex\GCILib.dll).
 * The cause is files Nucleus does not sign (only the installer is signed, by the
 * owner's choice); docs/dev/WINDOWS_SIGNING.md.
 *
 *   appControlBlockedFile(text)  null, or { file } (the blocked file's name, or null)
 *   explainAppControl(text)      the plain explanation when `text` is that error,
 *                                else `text` unchanged
 *
 * Pure, so `node --test` covers it. Applied where errors reach the screen:
 * API errors (transport/api.js), job errors (jobs/) and viewer starts (viewer/).
 */

const BLOCKED = /0x800711C7|Application Control policy has blocked|WinError 4551/i
const FILE = /([^\s'"\\/:]+\.(?:dll|exe|pyd))\b/i
const PYTHON_MODULE = /DLL load failed while importing ([\w.]+)/i

export function appControlBlockedFile(text) {
  const message = String(text ?? '')
  if (!BLOCKED.test(message)) return null
  const file = message.match(FILE)?.[1] || message.match(PYTHON_MODULE)?.[1] || null
  return { file }
}

export function explainAppControl(text) {
  const blocked = appControlBlockedFile(text)
  if (!blocked) return text
  const what = blocked.file ? `${blocked.file}, a file that comes with Nucleus,` : 'a file that comes with Nucleus'
  return `Windows Smart App Control blocked ${what} because Nucleus does not code-sign it. `
    + 'Smart App Control has no exception for a single app, so this step only runs with Smart App Control '
    + 'turned off (Windows Security > App & browser control). (Windows error 0x800711C7)'
}
