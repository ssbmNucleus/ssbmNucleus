/**
 * Storage Viewer Utility Functions
 *
 * Pure utility functions for managing skin/variant display lists and folder organization
 */

import { sortComparator } from './vaultSort'

/**
 * Build display list from allSkins array with folder expansion state
 * @param {Array} allSkins - Array of skins and folders
 * @param {Object} expandedFolders - Map of folderId -> isExpanded
 * @param {Object|null} sort - {key, dir} vault sort; null/'custom' keeps the
 *   stored array order. A non-custom sort is DISPLAY-ONLY: root items sort
 *   among themselves and each folder's members sort within the folder, while
 *   folder headers keep their custom relative order. arrayIndex still points
 *   at the item's real position in the metadata array. Callers must disable
 *   index-based drag-reorder while a non-custom sort is active.
 * @returns {Array} Display list with type, item, arrayIndex
 */
export const buildDisplayList = (allSkins, expandedFolders = {}, sort = null) => {
  if (!allSkins?.length) return []

  const cmp = sortComparator(sort)
  if (cmp) {
    const folders = []
    const folderItems = {}
    const rootItems = []
    for (let i = 0; i < allSkins.length; i++) {
      const item = allSkins[i]
      if (item.type === 'folder') {
        folders.push({ folder: item, arrayIndex: i })
        if (!folderItems[item.id]) folderItems[item.id] = []
      } else if (item.visible !== false) {
        const entry = { skin: item, arrayIndex: i }
        if (item.folder_id) {
          if (!folderItems[item.folder_id]) folderItems[item.folder_id] = []
          folderItems[item.folder_id].push(entry)
        } else {
          rootItems.push(entry)
        }
      }
    }
    const bySkin = (a, b) => cmp(a.skin, b.skin)
    const result = []
    for (const entry of rootItems.slice().sort(bySkin)) {
      result.push({ type: 'skin', skin: entry.skin, folderId: null, arrayIndex: entry.arrayIndex })
    }
    for (const { folder, arrayIndex } of folders) {
      const isExpanded = expandedFolders[folder.id] ?? folder.expanded ?? true
      result.push({ type: 'folder', folder, isExpanded, arrayIndex })
      if (isExpanded && folderItems[folder.id]) {
        for (const entry of folderItems[folder.id].slice().sort(bySkin)) {
          result.push({ type: 'skin', skin: entry.skin, folderId: folder.id, arrayIndex: entry.arrayIndex })
        }
      }
    }
    return result
  }

  // Build folder info and collect folder items
  const folderItems = {} // folderId -> [items with arrayIndex]
  const folders = [] // folder objects with arrayIndex
  const rootItems = [] // items not in any folder

  for (let i = 0; i < allSkins.length; i++) {
    const item = allSkins[i]

    if (item.type === 'folder') {
      folders.push({ folder: item, arrayIndex: i })
      // Don't reset — the folder entry can sit AFTER its members in the array
      // (drag/reorder writes that order), and clobbering here dropped every
      // skin collected so far, so the folder opened empty.
      if (!folderItems[item.id]) {
        folderItems[item.id] = []
      }
    } else if (item.visible !== false) {
      if (item.folder_id) {
        if (!folderItems[item.folder_id]) {
          folderItems[item.folder_id] = []
        }
        folderItems[item.folder_id].push({ skin: item, arrayIndex: i })
      } else {
        rootItems.push({ skin: item, arrayIndex: i })
      }
    }
  }

  // Build display list: root items first, then folders with their items
  const result = []

  // Add root items that come before all folders
  // We need to maintain relative order, so track what we've added
  const addedIndices = new Set()

  // Go through array in order to maintain relative positioning
  for (let i = 0; i < allSkins.length; i++) {
    const item = allSkins[i]

    if (item.type === 'folder') {
      const isExpanded = expandedFolders[item.id] ?? item.expanded ?? true
      result.push({ type: 'folder', folder: item, isExpanded, arrayIndex: i })
      addedIndices.add(i)

      // If expanded, add all items belonging to this folder right after it
      if (isExpanded && folderItems[item.id]) {
        for (const folderItem of folderItems[item.id]) {
          result.push({ type: 'skin', skin: folderItem.skin, folderId: item.id, arrayIndex: folderItem.arrayIndex })
          addedIndices.add(folderItem.arrayIndex)
        }
      }
    } else if (item.visible !== false && !item.folder_id) {
      // Root item - add it
      result.push({ type: 'skin', skin: item, folderId: null, arrayIndex: i })
      addedIndices.add(i)
    }
    // Skip folder items here - they're added after their folder
  }

  return result
}

/**
 * Count skins in a folder (by folder_id)
 * @param {string} folderId - Folder ID
 * @param {Array} allSkins - Array of skins
 * @returns {number} Count of visible skins in folder
 */
export const countSkinsInFolder = (folderId, allSkins) => {
  return allSkins.filter(s => s.folder_id === folderId && s.visible !== false).length
}

