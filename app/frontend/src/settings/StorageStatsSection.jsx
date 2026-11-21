/**
 * StorageStatsSection - Display vault storage statistics
 *
 * Features:
 * - Shows costume count across all characters
 * - Shows stage variant count
 * - Shows disk space usage, split by Vault and projects
 */
import { useState, useEffect } from 'react'
import { api } from '../shared/transport/api'

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—'
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export default function StorageStatsSection({ metadata }) {
  const [sizeStats, setSizeStats] = useState(null)

  useEffect(() => {
    api.get('/storage/stats')
      .then(data => {
        setSizeStats(data.stats)
      })
      .catch(err => console.error('Failed to fetch storage stats:', err))
  }, [])

  // Calculate storage statistics
  const getStorageStats = () => {
    if (!metadata) return { costumeCount: 0, stageCount: 0, extrasCount: 0, patchCount: 0 }

    let costumeCount = 0
    let extrasCount = 0

    Object.values(metadata.characters || {}).forEach(char => {
      costumeCount += (char.skins || []).length
      // Count extras across all extra types
      if (char.extras && typeof char.extras === 'object') {
        Object.values(char.extras).forEach(extraList => {
          if (Array.isArray(extraList)) {
            extrasCount += extraList.length
          }
        })
      }
    })

    let stageCount = 0
    Object.values(metadata.stages || {}).forEach(stage => {
      stageCount += (stage.variants || []).length
    })

    const patchCount = (metadata.xdelta || []).length

    return { costumeCount, stageCount, extrasCount, patchCount }
  }

  const stats = getStorageStats()

  return (
    <section className="settings-section">
      <h3>Storage Statistics</h3>
      <div className="storage-stats-grid">
        <div className="stat-item">
          <div className="stat-value">{stats.costumeCount}</div>
          <div className="stat-label">Costumes</div>
        </div>
        <div className="stat-item">
          <div className="stat-value">{stats.stageCount}</div>
          <div className="stat-label">Stages</div>
        </div>
        <div className="stat-item">
          <div className="stat-value">{stats.extrasCount}</div>
          <div className="stat-label">Extras</div>
        </div>
        <div className="stat-item">
          <div className="stat-value">{stats.patchCount}</div>
          <div className="stat-label">Patches</div>
        </div>
        <div className="stat-item">
          <div className="stat-value">{sizeStats ? formatBytes(sizeStats.storage) : '...'}</div>
          <div className="stat-label">Vault Size</div>
        </div>
        <div className="stat-item">
          <div className="stat-value">{sizeStats ? formatBytes(sizeStats.projects) : '...'}</div>
          <div className="stat-label">Projects Size</div>
        </div>
      </div>
    </section>
  )
}

// Export the stats calculation function for use by other components
export function getStorageStats(metadata) {
  if (!metadata) return { characterCount: 0, stageCount: 0, costumeCount: 0 }

  const characterCount = Object.keys(metadata.characters || {}).length
  let costumeCount = 0

  Object.values(metadata.characters || {}).forEach(char => {
    costumeCount += (char.skins || []).length
  })

  let stageCount = 0
  Object.values(metadata.stages || {}).forEach(stage => {
    stageCount += (stage.variants || []).length
  })

  return { characterCount, stageCount, costumeCount }
}
