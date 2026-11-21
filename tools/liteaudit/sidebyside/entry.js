// Browser entry: the REAL Watch Lite paint modules, bundled unchanged (build.mjs).
import { paintFrame, stepCamera, viewFromCam, drawRandall } from '@R/litePaint.js'
import { createRenderer } from '@R/meleeRender.js'
import { narrowAnimations } from '@R/liteClipLoader.js'
import { registerStageDataLoader, registerFighterDataLoader, registerItemDataLoader, registerHitDataLoader,
  ensureStageData, ensureReplayFighterData, ensureReplayItemData, ensureReplayHitData } from '@R/stageData.js'
import { stageGeometryAt } from '@R/liteStageInference.js'
window.WL = { paintFrame, stepCamera, viewFromCam, drawRandall, createRenderer, narrowAnimations,
  registerStageDataLoader, registerFighterDataLoader, registerItemDataLoader, registerHitDataLoader,
  ensureStageData, ensureReplayFighterData, ensureReplayItemData, ensureReplayHitData, stageGeometryAt }
