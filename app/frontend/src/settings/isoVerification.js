export function classifyIsoVerification(data) {
  if (data?.valid === true) {
    return { status: 'valid', message: 'Valid vanilla Melee 1.02 ISO!' }
  }
  if (data?.valid !== false) {
    throw new Error('Verification service returned an incomplete response')
  }
  // The backend says why (compressed, NKit, wrong disc or revision, trimmed, modified).
  if (typeof data?.message === 'string' && data.message) {
    return { status: 'invalid', message: data.message }
  }
  const md5 = typeof data?.md5 === 'string' ? data.md5 : ''
  return {
    status: 'invalid',
    message: md5
      ? `Invalid ISO (MD5: ${md5.slice(0, 8)}...). Need vanilla Melee 1.02`
      : 'Invalid ISO. This is not a vanilla Melee 1.02 ISO.',
  }
}

export function classifyIsoVerificationFailure(error) {
  const detail = error?.message || 'Backend unavailable'
  // The backend could not read the file and says why (e.g. macOS privacy);
  // that is not a backend outage, so no "check that Nucleus is running".
  if (error?.data?.reason === 'unreadable') {
    return { status: 'unavailable', message: detail }
  }
  if (error?.status === 404) {
    return {
      status: 'unavailable',
      message: `Could not find the ISO at this path: ${detail}. Reconnect the drive or choose the file again, then retry.`,
    }
  }
  return {
    status: 'unavailable',
    message: `Could not verify this ISO right now: ${detail}. Check that Nucleus is running, then retry.`,
  }
}

export function createIsoVerificationGate() {
  let generation = 0
  return {
    begin(path) { return { generation: ++generation, path } },
    isCurrent(request, path) {
      return request.generation === generation && request.path === path
    },
    invalidate() { generation += 1 },
  }
}
