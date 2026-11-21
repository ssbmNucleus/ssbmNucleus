export function stripProgressPercentage(message) {
  if (typeof message !== 'string') {
    return message
  }

  return message
    .replace(/\s*(?:[-:]\s*)?\(?\d+(?:\.\d+)?%\)?\s*$/u, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

export function getProgressMessage(message, fallback = '') {
  const cleanedMessage = stripProgressPercentage(message || '')
  return cleanedMessage || fallback
}
