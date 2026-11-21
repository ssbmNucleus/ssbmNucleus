// Helpers for exporting the DAT file from the embedded viewer via Electron IPC

// Request a DAT export from the viewer. The 'exportDat' viewer message resolves/rejects
// the promise through the resolver ref (handled by the viewer message handler).
export const cancelExportDat = (exportDatResolverRef, reason = 'Export cancelled') => {
  const request = exportDatResolverRef.current
  if (!request) return false

  exportDatResolverRef.current = null
  clearTimeout(request.timeoutId)
  request.reject(new Error(reason))
  return true
}

export const settleExportDat = (exportDatResolverRef, message) => {
  const request = exportDatResolverRef.current
  if (!request) return false

  if (request.sessionId && (message.sessionId !== request.sessionId ||
      message.requestId !== request.requestId || message.type !== request.type)) return false

  exportDatResolverRef.current = null
  clearTimeout(request.timeoutId)
  if (message.success) request.resolve(request.type === 'exportPaintPair' ? message.members : message.data)
  else request.reject(new Error(`${message.memberId ? `${message.memberId === 'nana' ? 'Nana' : 'Popo'}: ` : ''}${message.error || 'Export failed'}`))
  return true
}

let nextExportRequest = 0
export const requestExportDat = (exportDatResolverRef, timeoutMs = 30000, options = {}) => {
  // Pair exports echo session/request IDs; legacy single exports remain compatible.
  // Keep only one active export so close/disconnect can cancel it atomically.
  if (exportDatResolverRef.current) {
    return Promise.reject(new Error('An export is already in progress'))
  }

  return new Promise((resolve, reject) => {
    const request = { resolve, reject, timeoutId: null, type: options.type || 'exportDat',
      sessionId: options.sessionId, requestId: `export-${++nextExportRequest}` }
    exportDatResolverRef.current = request
    request.timeoutId = setTimeout(() => {
      if (exportDatResolverRef.current === request) {
        exportDatResolverRef.current = null
        reject(new Error('Export timed out'))
      }
    }, timeoutMs)

    try {
      Promise.resolve(window.electron.viewerSend({ type: request.type,
        ...(request.sessionId ? { sessionId: request.sessionId, requestId: request.requestId } : {}) })).then(sent => {
          if (sent === false) throw new Error('Viewer disconnected before export')
        }).catch((error) => {
        if (exportDatResolverRef.current !== request) return
        exportDatResolverRef.current = null
        clearTimeout(request.timeoutId)
        reject(error instanceof Error ? error : new Error(String(error)))
      })
    } catch (error) {
      if (exportDatResolverRef.current === request) exportDatResolverRef.current = null
      clearTimeout(request.timeoutId)
      reject(error instanceof Error ? error : new Error(String(error)))
    }
  })
}

export const base64ToBlob = (base64Data) => {
  const byteCharacters = atob(base64Data)
  const byteNumbers = new Array(byteCharacters.length)
  for (let i = 0; i < byteCharacters.length; i++) {
    byteNumbers[i] = byteCharacters.charCodeAt(i)
  }
  const byteArray = new Uint8Array(byteNumbers)
  return new Blob([byteArray], { type: 'application/octet-stream' })
}
