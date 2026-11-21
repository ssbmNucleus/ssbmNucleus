import { deriveFromSlp } from './index.js'

// One request per worker. The loader transfers the raw buffer and terminates
// the worker on completion (including parse errors), releasing the full trace.
self.onmessage = ({ data: { bytes, options } }) => {
  try {
    self.postMessage({ bundle: deriveFromSlp(bytes, options) })
  } catch (error) {
    self.postMessage({ error: { name: error.name, message: error.message } })
  }
}
