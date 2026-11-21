# One-Click Imports

One-click import is the website-driven version of manual import.

## What It Is

The app registers a `nucleus://` protocol.

A link using that protocol can open Nucleus, download a ZIP from a URL, and send it through the normal import flow.

On the website, this is the flow behind the **Add to Nucleus** button.

## What Happens When You Open One

At a high level, the flow is:

1. Nucleus opens or focuses the app.
2. The link provides a download URL and can also provide a filename and title.
3. Nucleus asks **Import from a website?**, naming the site the file comes from (and saying so when it is not
   ssbmnucleus.net). Any web page can open a `nucleus://` link, so nothing is downloaded until you choose
   **Import**.
4. Nucleus downloads the ZIP.
5. The ZIP goes through the same import pipeline used by manual import.
6. If needed, the normal Slippi safety dialog still appears.
7. On success, the imported item is added to the vault.

So the one-click part is just the handoff. It does not bypass the normal scan or validation steps.

Links received while Nucleus starts wait until the interface can accept them.
Repeated copies of the same link arriving together are treated as one handoff.

If a download or import fails, choose **Retry**, **Skip & Continue** to move to
the next queued item, or **Cancel Remaining** to stop the queue. With no items
waiting, you can retry or close the error. Successful imports already completed
are kept.

## How The Server Side Works

If a site says it supports one-click install for Nucleus, what it is really doing is packaging or hosting a ZIP in the format Nucleus already expects.

The mod format is still just a normal supported archive. The link is only what tells Nucleus where to get it.

## Whole-Build Sharing

One-click links are for individual mods (a skin, a stage).

For sharing a whole build — patch plus texture pack in one file — the format is the `.ssbm` [Mod Bundle](Mod-Bundles.md).

## Related Pages

- [Manual Import](Manual-Import.md)
- [Patches](Patches.md)
- [Mod Bundles](Mod-Bundles.md)
- [Texture Pack Mode](Texture-Pack-Mode.md)
