import './Settings.css'
import { useId, useState } from 'react'
import { RECORD_MODE } from '../shared/config/recordMode'
import { ASSISTANT_ENABLED } from '../shared/config/features'
import BackupRestore from './BackupRestore'
import StorageStatsSection from './StorageStatsSection'
import AdditionalDataSection from './AdditionalDataSection'
import IsoPathSection from './IsoPathSection'
import SlippiPathSection from './SlippiPathSection'
import MeleeUnlockedSection from './MeleeUnlockedSection'
import ClearStorageSection from './ClearStorageSection'
import DiscordSection from './DiscordSection'
import VolumeSection from './VolumeSection'
import SetupSection from './SetupSection'
import UpdateSection from './UpdateSection'
import BugReportSection from './BugReportSection'
import AccountSection from './AccountSection'
import CreditsSection from './CreditsSection'
import VaultSection from '../tracker/cloud/VaultSection'
import StorageLocationSection from './StorageLocationSection'
import McpSection from './McpSection'
import ModelImportToolsSection from './ModelImportToolsSection'
import CreationToolkitSection from './CreationToolkitSection'

export default function Settings({ metadata, onOpenFirstRunSetup, mode = 'nucleus', section, onSectionChange }) {
  // In nucleOME mode, hide the vault/ISO-workshop sections (backup/export,
  // texture packs, storage stats) — they belong to the modding app.
  // Paths, setup, account, sounds, Discord, updates apply to both modes.
  const nucleome = mode === 'nucleome'
  const [localSection, setLocalSection] = useState('general')
  const panelId = useId()
  // AI (owner 11-20: "it should have its own tab on the left ... like all the ai stuff"): connecting your own AI,
  // the model import's download and the creation toolkit. Builds with the assistant only.
  const aiTab = ASSISTANT_ENABLED && !RECORD_MODE
  const groups = [
    { id: 'general', label: 'General', cards: <>
      <VolumeSection />
      {!RECORD_MODE && <UpdateSection />}<DiscordSection />
      {!RECORD_MODE && <BugReportSection />}<CreditsSection />
    </> },
    { id: 'setup', label: 'Files & setup', cards: <>
      {!RECORD_MODE && <AccountSection nucleome={nucleome} />}
      <IsoPathSection /><SlippiPathSection />
      <MeleeUnlockedSection />
      <SetupSection onOpenFirstRunSetup={onOpenFirstRunSetup} />
    </> },
    ...(aiTab ? [{ id: 'ai', label: 'AI', cards: <>
      <McpSection />
      {/* The model import's own download: the assistant build gate, open to everyone (no entitlement). */}
      <ModelImportToolsSection />
      <CreationToolkitSection />
    </> }] : []),
    ...(nucleome ? [{ id: 'cloud', label: 'Cloud', cards: <VaultSection /> }] : []),
    { id: 'storage', label: nucleome ? 'Storage' : 'Storage & backups', cards: <>
      <StorageLocationSection />
      {!nucleome && <><BackupRestore /><AdditionalDataSection />
        <StorageStatsSection metadata={metadata} /><ClearStorageSection metadata={metadata} /></>}
    </> },
  ]
  const selected = groups.some(group => group.id === (section ?? localSection)) ? (section ?? localSection) : 'general'
  const selectSection = id => { setLocalSection(id); onSectionChange?.(id) }

  const handleNavigationKey = event => {
    const index = groups.findIndex(group => group.id === selected)
    const next = event.key === 'ArrowDown' ? (index + 1) % groups.length
      : event.key === 'ArrowUp' ? (index + groups.length - 1) % groups.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? groups.length - 1 : null
    if (next === null) return
    event.preventDefault()
    selectSection(groups[next].id)
    event.currentTarget.parentElement.querySelectorAll('[role="tab"]')[next]?.focus()
  }

  return (
    <div className="settings-container">
      <div className="settings-content">
        <h2>Settings</h2>

        <div className="settings-layout">
          <div className="settings-navigation" role="tablist" aria-label="Settings categories" aria-orientation="vertical">
            {groups.map(group => <button key={group.id} type="button" role="tab"
              id={`${panelId}-${group.id}-tab`} aria-controls={`${panelId}-${group.id}`}
              aria-selected={selected === group.id} tabIndex={selected === group.id ? 0 : -1}
              className="settings-category-button" onClick={() => selectSection(group.id)} onKeyDown={handleNavigationKey}>
              {group.label}
            </button>)}
          </div>
          <div className="settings-panels">
            {/* Keep cards mounted so switching categories preserves drafts and ongoing operations. */}
            {groups.map(group => <section key={group.id} id={`${panelId}-${group.id}`} role="tabpanel"
              aria-labelledby={`${panelId}-${group.id}-tab`} hidden={selected !== group.id} tabIndex={0}
              className="settings-category-panel">
              <h3 className="settings-category-heading">{group.label}</h3>
              <div className={`settings-category-cards${group.id === 'cloud' ? ' settings-cloud-cards' : ''}`}>{group.cards}</div>
            </section>)}
          </div>
        </div>
      </div>
    </div>
  )
}
