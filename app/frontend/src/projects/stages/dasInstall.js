/**
 * What a Dynamic Alternate Stages install leaves the user to know.
 *
 * POST /das/install succeeds even when a stage's loader could not be made
 * (it is rebuilt from the user's own vanilla stage file); the response then
 * carries `warning`. Create Project and the Stages tab both show it.
 */
export const DAS_NOTICE_TITLE = 'Dynamic Alternate Stages'

/** The notice for an install response, or null when every stage went in. */
export function dasInstallNotice(result) {
  const warning = typeof result?.warning === 'string' ? result.warning.trim() : ''
  return warning ? `Dynamic Alternate Stages is set up, but not for every stage.\n\n${warning}` : null
}

/** The notice for an install request that failed outright. */
export function dasInstallFailureNotice(err) {
  return `Dynamic Alternate Stages could not be set up: ${err?.message || 'unknown error'}\n\n`
    + 'Install it again from the Stages tab.'
}
