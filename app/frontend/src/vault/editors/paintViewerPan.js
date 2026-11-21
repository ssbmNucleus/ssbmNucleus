import { cameraPanStep } from '../../shared/viewer/viewerInput.js'

// Scene units per pixel of a Texture Lab pan before the renderer's camera is read, or from a renderer that cannot
// say: the speeds the lab always panned at (a costume's, a stage's), now with the cursor on both axes.
export const PAN_STEP = 0.1
export const STAGE_PAN_STEP = 0.4

/** The running renderer's camera (exportScene: z, fovRadians), or null when it cannot say. */
export async function readViewerCamera(electron) {
  try {
    const scene = await electron?.viewerExportScene?.()
    return scene?.camera || null
  } catch { return null }
}

/**
 * How far one pixel of a right-drag moves the Texture Lab's camera, as in Randall's workbench (cameraPanStep): the
 * model stays under the cursor on both axes, at any zoom and view size. `camera`: the renderer's, as last read;
 * `element`: the view. -> scene units per pixel.
 */
export function paintPanStep(camera, element, isStage) {
  return cameraPanStep(camera, element?.clientWidth, element?.clientHeight) ?? (isStage ? STAGE_PAN_STEP : PAN_STEP)
}
