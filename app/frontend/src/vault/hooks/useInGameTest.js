/** Interactive per-mod sessions and the separate automated screenshot flows. */
import { useEffect, useState } from 'react'
import { channel } from '../../shared/transport/socket'
import { api } from '../../shared/transport/api'
import { playSound } from '../../shared/audio/sounds'
import { jobStore, refreshJob, startJobStore } from '../../shared/jobs/jobs'
import { createInGameSession, initialTestState } from './inGameSession'

export function useInGameTest() {
  const [state, setState] = useState(initialTestState)
  const [session] = useState(() => createInGameSession({
    api, channel, playSound, onState: setState,
    jobs: { get: jobStore.get, subscribe: jobStore.subscribe, refresh: refreshJob },
    storage: {
      getItem: key => sessionStorage.getItem(key),
      setItem: (key, value) => sessionStorage.setItem(key, value),
      removeItem: key => sessionStorage.removeItem(key),
    },
    readPaths: () => ({ vanillaIsoPath: localStorage.getItem('vanilla_iso_path'),
      slippiDolphinPath: localStorage.getItem('slippi_dolphin_path') }),
  }))
  useEffect(() => {
    startJobStore()
    session.mount()
    return () => session.unmount()
  }, [session])

  const startCostumeTest = ({ character, skinId, colorName }) =>
    session.start('/test-in-game/costume', { character, skinId, colorName })
  const startCustomCharacterTest = ({ slug, name }) =>
    session.start('/test-in-game/custom-character', { slug, name })
  const startCustomCharacterSkinTest = ({ slug, skinId, costumeIndex, colorName }) =>
    session.start('/test-in-game/custom-character-skin', { slug, skinId, costumeIndex, colorName })
  const startCustomStageTest = ({ slug, name }) =>
    session.start('/test-in-game/custom-stage', { slug, name })
  const startStageSkinTest = ({ stageCode, stageFolder, variantId, name, button }) =>
    session.start('/test-in-game/stage-skin', { stageCode, stageFolder, variantId, name, button })

  const captureStageScreenshot = ({ stageCode, stageFolder, variantId, name, button }) =>
    session.start('/test-in-game/capture-stage-screenshot',
      { stageCode, stageFolder, variantId, name, button }, {
        interactive: false, message: 'Starting screenshot capture…',
        result: data => ({ success: true, captured: true,
          reason: 'Replace this stage’s current screenshot with the captured shot?',
          screenshot: data.screenshot || null, stageFolder: data.stageFolder, variantId: data.variantId }),
      })
  const capturePauseScreenshot = ({ modId, name }) =>
    session.start('/test-in-game/capture-pause-screenshot', { modId }, {
      interactive: false, message: 'Starting pause screenshot capture…',
      result: data => ({ success: true, captured: true,
        reason: `Saved as the preview for "${name || 'this mod'}".`,
        screenshot: data.screenshot || null, modId: data.modId }),
    })

  return { ...state, startCostumeTest, startCustomCharacterTest, startCustomCharacterSkinTest,
    startCustomStageTest, startStageSkinTest, captureStageScreenshot, capturePauseScreenshot,
    stopTest: session.stop, resetTest: session.reset }
}
