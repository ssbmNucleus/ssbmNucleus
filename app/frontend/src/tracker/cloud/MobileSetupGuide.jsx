import { useId, useState } from 'react'

export default function MobileSetupGuide() {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const headingId = useId()

  return (
    <div className="vault-mobile-guide">
      <button
        type="button"
        className="iso-browse-button vault-mobile-guide-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(value => !value)}
      >
        {open ? 'Hide mobile setup guide' : 'Mobile setup guide'}
      </button>
      <div id={panelId} className="vault-mobile-guide-panel" role="region"
           aria-labelledby={headingId} hidden={!open}>
        <h4 id={headingId}>Set up Nucleus on your phone</h4>
        <p>The phone app and whole-library sync come with any paid Patreon tier
          ($5/month and up). Link Patreon at the top of Settings → Cloud first.</p>
        <ol>
          <li><strong>Finish desktop setup.</strong> Set up Tracker with your replay
            folders and connect codes, and let it index your games.</li>
          <li><strong>Add the phone app.</strong> On your phone, open{' '}
            <span className="vault-mobile-guide-address">tracker.ssbmnucleus.net</span>{' '}
            in your browser. Choose <strong>Add to Home Screen</strong> from its
            share or menu options, then close the browser.</li>
          <li><strong>Show the desktop QR code.</strong> In desktop Tracker, go to{' '}
            <strong>Settings → Cloud</strong> and press <strong>Pair your phone</strong>.</li>
          <li><strong>Pair from the Home Screen app.</strong> Open Nucleus from your
            phone’s Home Screen, tap <strong>Scan pairing code</strong>, allow
            camera access, and scan the QR code on your desktop.</li>
          <li><strong>Let your games upload.</strong> Keep desktop Nucleus open.
            Uploading a large history takes time; check progress in{' '}
            <strong>Settings → Cloud → Cloud library</strong>. Use <strong>Sync now</strong>{' '}
            if an upload has not started.</li>
        </ol>
        <p className="vault-mobile-guide-note">The desktop QR hides after two minutes.
          If it disappears before you scan it, choose <strong>Pair your phone</strong> again.</p>
      </div>
    </div>
  )
}
