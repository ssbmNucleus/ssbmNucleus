import { useCallback, useState } from 'react'
import { api } from '../../shared/transport/api'

// The Vault lists that are not part of the metadata payload, with their
// fetchers: stage variants grouped by stage, custom stages, custom characters
// (plus built-ins still waiting to be set up), and patch bundles.
export function useVaultLists() {
  const [stageVariants, setStageVariants] = useState({})
  const [bundles, setBundles] = useState([])
  const [customStages, setCustomStages] = useState([])
  const [customCharacters, setCustomCharacters] = useState([])
  // Built-in fighters staged by first-run setup but not built yet — they show
  // up greyed out in the grid and set themselves up on click.
  const [pendingBuiltins, setPendingBuiltins] = useState([])

  // Fetch stage variants function (defined early for use in drag/drop hook)
  const fetchStageVariants = async () => {
    try {
      const data = await api.get('/das/storage/variants')

      // Group variants by stage
      const grouped = {}
      data.variants.forEach(variant => {
        if (!grouped[variant.stageCode]) {
          grouped[variant.stageCode] = []
        }
        grouped[variant.stageCode].push(variant)
      })
      setStageVariants(grouped)
    } catch (err) {
      console.error('Failed to fetch stage variants:', err)
    }
  }

  // Fetch custom stages
  const fetchCustomStages = async () => {
    try {
      const data = await api.get('/custom-stages/list')
      setCustomStages(data.stages || [])
    } catch (err) {
      console.error('Failed to fetch custom stages:', err)
    }
  }

  // Custom stage zip imports and ISO scans now go through the unified
  // ImportFab pipeline / the unified IsoScanModal.

  // Fetch custom characters
  const fetchCustomCharacters = async () => {
    try {
      const data = await api.get('/custom-characters/list')
      setCustomCharacters(data.characters || [])
    } catch (err) {
      console.error('Failed to fetch custom characters:', err)
    }
    try {
      const data = await api.get('/custom-characters/builtins')
      setPendingBuiltins(data.builtins || [])
    } catch (err) {
      console.error('Failed to fetch built-in characters:', err)
    }
  }

  // Custom character zip imports and ISO scans now go through the unified
  // ImportFab pipeline / the unified IsoScanModal.

  // Fetch bundles - defined before hooks that need it as callback
  const fetchBundles = useCallback(async () => {
    try {
      const data = await api.get('/bundle/list')
      // Dedupe by id just in case
      const seen = new Set()
      const uniqueBundles = data.bundles.filter(b => {
        if (seen.has(b.id)) return false
        seen.add(b.id)
        return true
      })
      setBundles(uniqueBundles)
    } catch (err) {
      console.error('Failed to fetch bundles:', err)
    }
  }, [])

  return {
    stageVariants, setStageVariants, bundles, customStages, customCharacters, pendingBuiltins,
    fetchStageVariants, fetchCustomStages, fetchCustomCharacters, fetchBundles,
  }
}
