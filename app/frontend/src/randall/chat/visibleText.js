// Display-only cleanup: preserve stored content offsets and ordinary Unicode/emoji.
const TAGS = ['think', 'thinking', 'mm:think', 'mm:thinking'].flatMap(name => [`<${name}>`, `</${name}>`])
export function visibleAssistantText(content = '') {
  const text = content
    .replace(/<(?:mm:)?think(?:ing)?>[\s\S]*?(?:<\/(?:mm:)?think(?:ing)?>|$)/gi, '')
    .replace(/<\/(?:mm:)?think(?:ing)?>/gi, '')
  const start = text.lastIndexOf('<')
  if (start < 0) return text
  const suffix = text.slice(start).toLowerCase()
  return TAGS.some(tag => tag.startsWith(suffix)) ? text.slice(0, start) : text
}
