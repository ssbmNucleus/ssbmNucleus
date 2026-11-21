// Keep one card at its first appearance; later receipts update its state in place.
export function collectWebsiteCards(messages, presence = {}) {
  const cards = new Map()
  for (const message of messages) for (const tool of message.tools || []) {
    const mods = tool.result?.website_mods || tool.approval?.website_mods || []
    for (const mod of mods) {
      const previous = cards.get(mod.post_id)
      const card = previous || { owner: tool.id, mod: {} }
      card.mod = { ...card.mod, ...mod }
      if (tool.name === 'download_website_mod') {
        card.download = tool
        if (tool.result?.imported_count > 0 || tool.result?.skipped_count > 0) card.inVault = true
      }
      if (tool.name === 'download_website_mods') {
        const entry = tool.result?.downloads?.find(item => item.post_id === mod.post_id)
        card.download = { ...tool, status: entry?.status || tool.status, result: entry?.result }
        if (entry?.result?.imported_count > 0 || entry?.result?.skipped_count > 0) card.inVault = true
      }
      cards.set(mod.post_id, card)
    }
  }
  for (const [postId, card] of cards) {
    if (typeof presence[postId] === 'boolean') card.inVault = presence[postId]
    else if (typeof card.mod.in_vault === 'boolean') card.inVault = card.mod.in_vault
  }
  return cards
}
