// Superseded or closed requests cannot publish data, errors, or completion.
export function createLatestRequest({ request, onData, onLoading, onError, onSettled = () => {},
  errorMessage = 'Could not load data.' }) {
  let current = null
  return {
    async load(url, context) {
      current?.abort()
      const controller = new AbortController()
      current = controller
      onLoading(true)
      onError('')
      try {
        const data = await request(url, { signal: controller.signal })
        if (current === controller) onData(data, context)
      } catch (error) {
        if (current === controller && error?.name !== 'AbortError') onError(error?.message || errorMessage)
      } finally {
        if (current === controller) {
          current = null
          onLoading(false)
          onSettled()
        }
      }
    },
    cancel() {
      current?.abort()
      current = null
    },
  }
}
