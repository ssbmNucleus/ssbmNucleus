import { useEffect, useRef, useState } from 'react'

export function useMaterialColors({ generation, onChanged }) {
  const [materials, setMaterials] = useState([])
  const [baseColors, setBaseColors] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const pending = useRef(null)
  const revision = useRef(0)
  const request = async command => {
    const version = revision.current
    while (pending.current) await pending.current.promise
    if (version !== revision.current) return { success: false, error: 'Editor session changed' }
    setBusy(true); setError('')
    const requestId = `material-${crypto.randomUUID()}`
    let resolve
    const promise = new Promise(done => { resolve = done })
    const timeout = setTimeout(() => {
      if (pending.current?.id !== requestId) return
      if (pending.current.changed) onChanged()
      pending.current = null; setBusy(false); setError('The viewer did not confirm the change. Refresh materials before saving.')
      resolve({ success: false, error: 'Material update timed out' })
    }, 10000)
    pending.current = { id: requestId, timeout, promise, resolve, changed: ['setMaterial', 'setMaterialColors'].includes(command.type) }
    try {
      if (await window.electron.viewerSend({ ...command, requestId }) === false) throw new Error('Viewer disconnected')
    } catch (err) {
      if (pending.current?.id !== requestId) return
      clearTimeout(timeout); pending.current = null; setBusy(false); setError(err.message)
      resolve({ success: false, error: err.message })
    }
    return promise
  }
  const receive = message => {
    if (!pending.current || message.requestId !== pending.current.id) return false
    if (!['materials', 'commandError', 'error'].includes(message.type)) return false
    const operation = pending.current
    clearTimeout(operation.timeout); pending.current = null; setBusy(false)
    if (message.error || message.success === false) setError(message.error || 'Could not update the material')
    else {
      setMaterials(message.materials || []); setBaseColors(Boolean(message.previewBaseColors))
      if (operation.changed) onChanged()
    }
    operation.resolve(message)
    return true
  }
  useEffect(() => {
    setMaterials([]); setError(''); setBusy(false); setBaseColors(false)
    return () => { revision.current++; clearTimeout(pending.current?.timeout); pending.current?.resolve({success:false,error:'Editor closed'}); pending.current = null }
  }, [generation])
  const checked = async command => {
    const reply = await request(command)
    if (!reply || reply.success === false || reply.error) throw new Error(reply?.error || 'Material update failed')
    return reply
  }
  return { inspect: async () => (await checked({ type: 'getMaterials' })).materials,
    apply: edits => checked({ type: 'setMaterialColors', edits }), materials, busy, error, baseColors, receive,
    load: () => request({ type: 'getMaterials' }),
    set: (id, field, value) => request({ type: 'setMaterial', id, field, value }),
    reset: (id, field) => request({ type: 'setMaterial', id, field, reset: true }),
    preview: enabled => request({ type: 'previewBaseColors', enabled }) }
}
