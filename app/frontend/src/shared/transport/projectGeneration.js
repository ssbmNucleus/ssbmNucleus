/**
 * projectGeneration.js — which open project this window is showing.
 *
 * The backend counts every project open, close and delete (its "generation")
 * and returns it from /status, /project/open, /project/close and
 * /project/delete. api.js sends the last one heard as X-Nucleus-Project, so a
 * request made for a project that has since been switched away is refused
 * (409, code 'project_changed') instead of landing on the new one.
 * null = not known yet, and then no header is sent.
 */
let generation = null

export function getProjectGeneration() {
  return generation
}

export function setProjectGeneration(next) {
  if (next === undefined || next === null) return
  generation = next
}

export function isProjectChanged(err) {
  return err?.status === 409 && err?.data?.code === 'project_changed'
}
