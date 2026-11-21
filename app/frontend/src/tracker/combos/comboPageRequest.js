import { createLatestRequest } from '../lib/latestRequest.js'

export const createComboPageRequest = options =>
  createLatestRequest({ errorMessage: 'Could not load combos.', ...options })
