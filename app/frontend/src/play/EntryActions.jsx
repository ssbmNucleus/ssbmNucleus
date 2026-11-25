/**
 * EntryActions - what sits beside a card's Play button: where to play it (TargetChooser) and
 * the entry menu (open data folder; for an added game also rename, describe, change cover,
 * choose its engine, remove). Every change goes through the Play routes, which need the
 * window's key.
 */
import { useRef, useState } from 'react'
import { api } from '../shared/transport/api'
import { playHoverSound, playSound } from '../shared/audio/sounds'
import { useClickOutside } from '../shared/hooks/useClickOutside'
import { appConfirm, appPrompt } from '../shared/ui/appDialogs'
import { COVER_TYPES } from '../shared/jobs/shelfAdd'
import { isBuiltin, targetChoices } from './playCards'

// Which Melee Unlocked engine plays an added game (play/routing.py decides for 'auto').
const ENGINE_CHOICES = [
  { id: 'auto', label: 'Automatic', title: 'The Source Port when every fighter can run there, else the compatibility engine.' },
  { id: 'source', label: 'Source Port', title: 'Faster. Fighters whose code has not been built may not work.' },
  { id: 'compat', label: 'Compatibility', title: "Slower. Runs the disc's own code (melee_port.exe)." },
]

/**
 * Melee Unlocked or Dolphin, for an added game that can be played in both. Remembered when it is
 * played. The built-in Nucleus and Vanilla cards have none: they start the Nucleus client.
 */
export function TargetChooser({ entry, target, setTarget, disabled }) {
  if (isBuiltin(entry)) return null
  const choices = targetChoices(entry)
  if (choices.filter((choice) => choice.available).length < 2) return null
  return (
    <select
      className="play-target"
      aria-label={`Where to play ${entry.name}`}
      value={target}
      disabled={disabled}
      onChange={(e) => setTarget(e.target.value)}
    >
      {choices.map((choice) => (
        <option key={choice.id} value={choice.id} disabled={!choice.available} title={choice.reason || undefined}>
          {choice.label}{choice.available ? '' : ' (not available)'}
        </option>
      ))}
    </select>
  )
}

export function EntryMenu({ entry, running, onChanged, onCoverChanged, onError }) {
  const [open, setOpen] = useState(false)
  const [working, setWorking] = useState(false)
  const menuRef = useRef(null)
  const fileRef = useRef(null)
  useClickOutside(menuRef, open, () => setOpen(false))
  const path = `/api/play/shelf/${encodeURIComponent(entry.id)}`

  const act = async (work) => {
    setOpen(false)
    setWorking(true)
    onError(entry.id, null)
    try {
      await work()
    } catch (err) {
      playSound('back')
      onError(entry.id, err.message || 'That did not work.')
    } finally {
      setWorking(false)
    }
  }

  const reveal = () => act(() => api.post(`/api/play/reveal/${encodeURIComponent(entry.id)}`, {}))

  const rename = () => act(async () => {
    const name = await appPrompt('The name this game has on the shelf.', {
      title: 'Rename', defaultValue: entry.name, confirmText: 'Rename',
    })
    if (name == null || name.trim() === '' || name.trim() === entry.name) return
    await api.patch(path, { name })
    playSound('boop')
    await onChanged()
  })

  const describe = () => act(async () => {
    const description = await appPrompt('A line or two about this game.', {
      title: 'Description', defaultValue: entry.description || '', confirmText: 'Save',
    })
    if (description == null || description === (entry.description || '')) return
    await api.patch(path, { description })
    playSound('boop')
    await onChanged()
  })

  const chooseCover = () => {
    setOpen(false)
    fileRef.current?.click()
  }

  const uploadCover = (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    act(async () => {
      const form = new FormData()
      form.append('cover', file)
      await api.post(`${path}/cover`, form)
      playSound('boop')
      onCoverChanged(entry.id)
      await onChanged()
    })
  }

  const remove = () => act(async () => {
    const yes = await appConfirm(
      `Remove "${entry.name}" from the shelf? Its disc, its saves and its memory card are deleted. This cannot be undone.`,
      { title: 'Remove game', confirmText: 'Remove' })
    if (!yes) return
    await api.delete(path)
    playSound('back')
    await onChanged()
  })

  const chooseEngine = (engine) => act(async () => {
    await api.patch(path, { engine })
    playSound('boop')
    await onChanged()
  })

  const items = [{ label: 'Open data folder', run: reveal }]
  if (!entry.builtin) {
    items.push(
      { label: 'Rename', run: rename },
      { label: 'Edit description', run: describe },
      { label: 'Change cover', run: chooseCover },
    )
    const current = entry.engineChoice || 'auto'
    for (const choice of ENGINE_CHOICES) {
      items.push({
        label: `${current === choice.id ? '✓ ' : ''}Engine: ${choice.label}`,
        title: choice.title,
        run: () => chooseEngine(choice.id),
        disabled: running || current === choice.id,
      })
    }
    items.push({ label: 'Remove from shelf', run: remove, danger: true, disabled: running })
  }

  return (
    <div className="play-menu" ref={menuRef}>
      <button
        type="button"
        className="play-quiet play-menu-button"
        aria-label={`More for ${entry.name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={working}
        onMouseEnter={playHoverSound}
        onClick={() => setOpen(!open)}
      >
        ⋯
      </button>
      {open && (
        <ul className="play-menu-list" role="menu">
          {items.map((item) => (
            <li key={item.label} role="none">
              <button type="button" role="menuitem" disabled={item.disabled} title={item.title}
                className={`play-menu-item ${item.danger ? 'play-menu-item--danger' : ''}`} onClick={item.run}>
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
      {!entry.builtin && (
        <input ref={fileRef} type="file" accept={COVER_TYPES} hidden onChange={uploadCover} />
      )}
    </div>
  )
}
