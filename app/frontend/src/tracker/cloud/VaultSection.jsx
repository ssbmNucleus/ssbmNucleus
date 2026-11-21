/**
 * VaultSection - Settings > Cloud: the Cloud hero (what your Patreon level
 * gives you and the next step), the Cloud library card (what is uploaded,
 * what is running, what happens automatically) and Cloud activity.
 *
 * "Cloud library" is the UI name for what the code calls the vault (the mod
 * library is also called the Vault, so the cloud one needed its own word).
 * Ids, routes and kv keys keep "vault".
 *
 * Replaces the two manual paths this used to need: hand-editing device rows in
 * SQL to pair a phone, and running the sync CLI by hand.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { refreshJob, useActiveJob, useJobEnd, useJobList } from '../../shared/jobs/useJobs'
import { getPatreonToken, buildPatreonAuthorizeUrl, openExternal, ENTITLEMENT_EVENT } from '../../shared/account/entitlement'
import { clearSignOutPending } from '../../shared/account/signOutPending'
import { usePremium } from '../../shared/account/usePremium'
import { cloudPlan, cloudPledgeKnown, overriddenPlan, paidTier, PHONE_PRICE } from '../../shared/account/cloudPlan'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import MobileSetupGuide from './MobileSetupGuide'
import CloudHero from './CloudHero'
import CloudActivitySection from './CloudActivitySection'
import { cloudErrorKind, friendlyCloudError } from './cloudErrors'
import { cloudView, cloudPhase, cloudStatusStep, STALL_S, SYNC_KIND } from './cloudJobs'
import { nextAccount } from './cloudAccount'
import { relativeTime } from './relativeTime'
import './VaultSection.css'

const API = `${BACKEND_URL}/api/nucleome`

const JSON_POST = { method: 'POST', headers: { 'Content-Type': 'application/json' } }

const fetchJson = (url, opts) => api.request(url, opts)

function VaultToggle({ label, note, checked, disabled, onChange }) {
  return (
    <label className={`vault-toggle ${disabled ? 'vault-toggle--disabled' : ''}`}>
      <input
        type="checkbox"
        checked={!!checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="vault-toggle-copy">
        <span className="vault-toggle-label">{label}</span>
        {note && <span className="vault-toggle-note">{note}</span>}
      </span>
    </label>
  )
}

export default function VaultSection() {
  // Whole-library sync and phone pairing are the paid half of the cloud;
  // sharing a single game is not, and uploads that game by itself. `loading`
  // matters: mirroring `active: false` before the entitlement check lands
  // would switch a paying user's autorun off for a moment.
  const {
    premium: pledged, loading: pledgeLoading, failed: pledgeUnknown, ent, overridden,
  } = usePremium()
  const [status, setStatus] = useState(null)
  const [accountReady, setAccountReady] = useState(false)
  const [statusError, setStatusError] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [actionError, setActionError] = useState('')
  const [devices, setDevices] = useState([])
  const [devicesLoaded, setDevicesLoaded] = useState(false)
  // The account the phones and pairing code belong to; a new one drops them.
  const account = useRef({ token: getPatreonToken() || null, epoch: 0 })
  const [epoch, setEpoch] = useState(0)

  const loadStatus = useCallback(async () => {
    try {
      const data = await fetchJson(`${API}/vault/status`)
      setStatus(data)
      setStatusError('')
      return data
    } catch (e) {
      // 404 = the vault is gated off in this build; the card would be an error
      // box the user can do nothing about, so it doesn't render at all.
      if (e.status === 404) setUnavailable(true)
      else setStatusError(friendlyCloudError(e.message, e.status))
      return null
    }
  }, [])

  const loadDevices = useCallback(async () => {
    const asked = account.current.epoch
    try {
      const data = await fetchJson(`${API}/vault/devices`)
      if (account.current.epoch === asked) setDevices(data?.devices || [])
    } catch (e) {
      setActionError(friendlyCloudError(e.message, e.status))
    } finally {
      if (account.current.epoch === asked) setDevicesLoaded(true)
    }
  }, [])

  // The Patreon token lives in localStorage, which the backend can't read. It
  // needs a copy on disk or the launch-time sync has no credentials at all.
  // The mirror goes BOTH ways: localStorage is the truth. Signed in but the
  // backend is empty -> hand it the token; signed OUT but the backend still
  // holds one (a sign-out from before the clear existed, or a wiped profile)
  // -> take it away, or the card stays armed and the autorun keeps syncing
  // for an account the app says is not linked.
  //
  // The pledge rides along: only this side knows whether the linked Patreon
  // is paying, and the autorun needs it to decide whether a background push
  // is allowed. That makes it a second reason to re-mirror even when the
  // token itself already matches -- a pledge can lapse without the token
  // changing at all. The first time it arrives as paid, the backend turns
  // automatic upload on (unless the user already chose) and starts it.
  useEffect(() => {
    let cancelled = false
    // `fromEvent`: a link or sign-out just happened, and `pledged` is still
    // the PREVIOUS account's answer (the fresh one re-runs this effect when
    // it lands). Send the token alone then; sending the old pledge with a new
    // token would hand a free account a paid upload.
    const reconcile = async (fromEvent) => {
      setAccountReady(false)
      if (pledgeLoading) return
      const first = await loadStatus()
      if (cancelled || !first) return
      const token = getPatreonToken()
      const active = !!pledged
      // A failed entitlement check is not a lapsed pledge: send the token but
      // leave the stored pledge alone, or an offline visit to this card turns
      // the backend's auto-sync off.
      const unknown = pledgeUnknown || fromEvent
      const pledgeMatches = !token || unknown || first.pledge_active === active
      if (!token && !first.configured && pledgeMatches) {
        clearSignOutPending()       // nothing left to clear
        return
      }
      const body = unknown ? { token: token || null } : { token: token || null, active }
      try {
        await fetchJson(`${API}/vault/token`,
          { ...JSON_POST, body: JSON.stringify(body) })
      } catch (e) {
        if (!cancelled) setStatusError(friendlyCloudError(e.message, e.status))
        return
      }
      if (!token) clearSignOutPending()
      const next = nextAccount(account.current, token)
      if (next !== account.current) {
        account.current = next
        setEpoch(next.epoch)
      }
      if (!cancelled) {
        await loadStatus()
        if (!cancelled) setAccountReady(true)
      }
    }
    reconcile(false)
    // Linking happens in the browser and lands through the deep link; the
    // entitlement event is how that reaches the rest of the app. Without
    // this the card only caught up on remount (leave Settings, come back).
    const onEntitlement = () => reconcile(true)
    window.addEventListener(ENTITLEMENT_EVENT, onEntitlement)
    return () => {
      cancelled = true
      window.removeEventListener(ENTITLEMENT_EVENT, onEntitlement)
    }
  }, [loadStatus, pledged, pledgeLoading, pledgeUnknown])

  const configured = !!status?.configured
  // Reloaded for a new account too: linking a second Patreon keeps
  // `configured` true, and the first account's phones must not stay (F-E-4).
  useEffect(() => {
    setDevices([])
    setDevicesLoaded(false)
    if (configured) loadDevices()
  }, [configured, epoch, loadDevices])

  // Until the device list is in, a non-paying account can't be told apart
  // from one whose pledge just lapsed with a phone still paired.
  // When Patreon's answer says nothing about the pledge (offline, or AI
  // paused), the last pledge the backend was told stands: a payer keeps
  // pairing and sync instead of reading "couldn't check" or "ended".
  const lastKnownPaid = status?.pledge_active === true
  const plan = useMemo(() => {
    if (overridden != null) return overriddenPlan(overridden, ent)
    if (ent !== undefined && !cloudPledgeKnown(ent) && lastKnownPaid) {
      return { state: 'paid', tier: ent?.linked ? paidTier(ent) : null, graceUntil: null }
    }
    const p = cloudPlan(ent, { hasPairedPhone: devices.length > 0 })
    if (configured && !devicesLoaded && ['free', 'non_member'].includes(p.state)) return { state: 'checking' }
    return p
  }, [overridden, ent, devices.length, configured, devicesLoaded, lastKnownPaid])
  const paid = plan.state === 'paid'
  const linked = !['signed_out', 'checking'].includes(plan.state)

  // The sync and the automatic chain are jobs (cloud_sync, cloud_autorun) the
  // window's job store follows, like the scans below.
  const jobList = useJobList()
  const [now, setNow] = useState(() => Date.now() / 1000)
  const cloud = useMemo(() => cloudView(jobList, now), [jobList, now])
  const running = cloud.running
  // No event arrives while a sync is stuck, which is when "no progress for
  // n min" must appear: keep the clock moving while one runs.
  useEffect(() => {
    if (!running) return undefined
    const id = setInterval(() => setNow(Date.now() / 1000), 15000)
    return () => clearInterval(id)
  }, [running])

  // The counts change when a pass ends, and along a long sync as it goes.
  useJobEnd(SYNC_KIND, loadStatus)
  useJobEnd('replay_scan', loadStatus)
  useJobEnd('combo_scan', loadStatus)
  const syncStep = cloudStatusStep(cloud)
  useEffect(() => { if (syncStep) loadStatus() }, [syncStep, loadStatus])

  // The launch chain runs index -> combos -> upload without anyone clicking
  // anything, so "what is happening right now" is whichever of the three is
  // live. Reported as one phase because they never overlap.
  const scanJob = useActiveJob('replay_scan')
  const comboJob = useActiveJob('combo_scan')
  const phase = useMemo(() => cloudPhase(cloud, scanJob, comboJob), [scanJob, comboJob, cloud.phase])

  const startSync = async () => {
    playSound('start')
    setActionError('')
    try {
      const data = await fetchJson(`${API}/vault/sync`, { method: 'POST' })
      // Show the bar on the click, not when the job's first event lands.
      if (data?.job_id) refreshJob(data.job_id).catch(() => {})
    } catch (e) {
      setActionError(friendlyCloudError(e.message, e.status))
      loadStatus()
    }
  }

  const revoke = async (deviceId) => {
    setActionError('')
    // Optimistic: the row disappears on the click, not two edge-function
    // round trips later (same pattern as setToggle). Restored on failure.
    const previous = devices
    setDevices((ds) => ds.filter((d) => d.id !== deviceId))
    try {
      await fetchJson(`${API}/vault/revoke`, { ...JSON_POST, body: JSON.stringify({ device_id: deviceId }) })
      loadDevices()          // background true-up; the list is already right
    } catch (e) {
      setDevices(previous)
      setActionError(friendlyCloudError(e.message, e.status))
    }
  }

  const setToggle = async (key, next) => {
    playSound('boop')
    const previous = status?.[key]
    setStatus((s) => ({ ...s, [key]: next }))
    setActionError('')
    try {
      const data = await fetchJson(`${API}/vault/settings`, { ...JSON_POST, body: JSON.stringify({ [key]: next }) })
      setStatus((s) => ({ ...s, auto_scan: data.auto_scan, auto_sync: data.auto_sync }))
    } catch (e) {
      // The backend never took it, so the switch must not look like it did.
      setStatus((s) => ({ ...s, [key]: previous }))
      setActionError(friendlyCloudError(e.message, e.status))
    }
  }

  const result = running ? null : cloud.result

  // The paid half's refusal is the hero's job to explain, with the button
  // that fixes it; repeating it here as a red box read as a fault.
  const syncErrorKind = cloudErrorKind(cloud.error)
  const showSyncError = !running && cloud.error && (paid || syncErrorKind !== 'pledge_required')

  if (unavailable) return null

  const synced = status?.synced ?? 0
  const pending = status?.pending ?? 0
  // Without Patreon the count and the two toggles say it all; a sentence
  // above them was one more grey line to read past.
  const description = paid
    ? 'Every game you play is uploaded here, and your phone reads it from here.'
    : linked
      ? 'Replays you share are kept here, so their links keep working.'
      : null

  return (
    <>
    <CloudHero
      key={epoch}
      plan={plan}
      entVersion={ent}
      devices={devices}
      configured={configured}
      onPaired={loadDevices}
      onRevoke={revoke}
    />
    <section className={`settings-section cloud-library ${configured ? '' : 'cloud-library--wide'}`}>
      <h3>Cloud library</h3>
      {description && <p className="section-description">{description}</p>}

      {statusError && <div className="vault-error" role="alert">{statusError}</div>}

      <div className="vault-summary">
        {paid ? (
          <span className="vault-count">
            {synced.toLocaleString()} games in the cloud
            {' · '}
            {pending.toLocaleString()} to sync
            {(status?.unsyncable ?? 0) > 0 && (
              <span
                className="vault-unsyncable"
                title="Replays that can't be turned into clips: solo training games and corrupt files. They stay on this computer and are skipped automatically."
              >
                {' · '}{status.unsyncable.toLocaleString()} can’t be uploaded
              </span>
            )}
          </span>
        ) : (
          <span className="vault-count">
            {(synced + pending).toLocaleString()} games processed on this computer
            {configured && synced > 0 && (
              <span className="vault-unsyncable">{' · '}{synced.toLocaleString()} in your cloud library</span>
            )}
          </span>
        )}
        {paid && <span className="vault-last-sync">Last sync {relativeTime(status?.last_sync_at)}</span>}
        {paid && (
          <button
            className="iso-browse-button"
            disabled={!configured || running}
            onMouseEnter={playHoverSound}
            onClick={startSync}
          >
            {running ? 'Syncing…' : 'Sync now'}
          </button>
        )}
      </div>

      {phase && (
        <div className="vault-activity">
          <div className="vault-activity-head">
            <span className="vault-activity-label">
              <span className="vault-activity-dot" />
              {phase.label}
            </span>
            <span className="vault-activity-count">
              {(phase.done || 0).toLocaleString()}
              {phase.total ? ` / ${phase.total.toLocaleString()}` : ''} {phase.unit}
              {phase.failed ? ` · ${phase.failed.toLocaleString()} failed` : ''}
              {/* A quota wait or a hung request freezes the counters; say so
                  rather than leave a bar that looks busy. */}
              {phase.idle >= STALL_S && (
                <span className="vault-stalled">
                  {' · '}no progress for {Math.floor(phase.idle / 60)} min
                </span>
              )}
            </span>
          </div>
          {/* An indeterminate bar while the total is still being counted —
              a 0/0 bar sitting at 100% reads as "finished", not "starting". */}
          <div className={`vault-progress ${phase.total ? '' : 'is-indeterminate'}`}>
            <div
              className="vault-progress-fill"
              style={phase.total
                ? { width: `${(100 * (phase.done || 0)) / phase.total}%` }
                : undefined}
            />
          </div>
        </div>
      )}

      {paid && result && (
        <div className="vault-sync-result">
          {result.pushed.toLocaleString()} uploaded · {result.skipped.toLocaleString()} already there
          {' · '}
          <span className={result.failed ? 'vault-failed' : ''}>{result.failed.toLocaleString()} failed</span>
          {result.metadataFailed > 0 && (
            <>{' · '}<span className="vault-failed">{result.metadataFailed.toLocaleString()} combo details not sent</span></>
          )}
        </div>
      )}
      {showSyncError && (
        <div className="vault-error" role="alert">
          {friendlyCloudError(cloud.error)}
          {syncErrorKind === 'relink' && (
            <button type="button" className="vault-error-action" onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); openExternal(buildPatreonAuthorizeUrl()) }}>
              Link Patreon again
            </button>
          )}
        </div>
      )}

      {cloud.autorunError && !phase && (
        <div className="vault-error" role="alert">
          Automatic processing stopped: {friendlyCloudError(cloud.autorunError)}
        </div>
      )}
      {actionError && <div className="vault-error" role="alert">{actionError}</div>}

      <div className="vault-block">
        {/* Processing is free and needs no account: it is local work on the
            user's own files. Only the upload is paid. */}
        <VaultToggle
          label="Process new replays"
          note="Finds new games and combos every 10 minutes while Nucleus is open."
          checked={status?.auto_scan}
          disabled={!status}
          onChange={(next) => setToggle('auto_scan', next)}
        />
        <VaultToggle
          label="Sync to your cloud library"
          note={paid ? 'Uploads them too, so your phone stays up to date.' : `Part of the $${PHONE_PRICE} tier, for the phone app.`}
          checked={status?.auto_sync && paid}
          disabled={!configured || !paid}
          onChange={(next) => setToggle('auto_sync', next)}
        />
      </div>

      {paid && <MobileSetupGuide />}
    </section>
    {configured && <CloudActivitySection ready={accountReady} running={running} />}
    </>
  )
}
