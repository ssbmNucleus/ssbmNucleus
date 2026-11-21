// A refresh started before a deletion/reimport must not replace its newer
// catalog when the network delivers the two responses out of order.
export function createMetadataRefresh({ read, setMetadata, setLoading, onError = console.error }) {
  let generation = 0
  return async () => {
    const request = ++generation
    try {
      const data = await read()
      if (request === generation) setMetadata(data.metadata)
    } catch (err) {
      if (request !== generation) return
      onError('Failed to fetch metadata:', err)
      // Preserve the existing backend-error behavior; only a transport error
      // clears the catalog. An older transport error cannot blank a newer one.
      if (!err.data) setMetadata({ characters: {} })
    } finally {
      if (request === generation) setLoading(false)
    }
  }
}
