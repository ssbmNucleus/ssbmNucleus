# Reporting a Bug

Something broke? Open **Settings → Bug Report** and click **Report a Bug**.

## What it does

1. You describe what happened (and how to make it happen again — the more
   repro detail, the better).
2. The app attaches its own logs automatically. You don't have to find any
   files.
3. The report goes **privately to the developer** — it is never posted in the
   public Discord server.

Optionally leave a Discord handle or email so you can be reached with a fix
or a follow-up question. Reports without contact info are welcome too.

## When Randall gets something wrong

If a Randall conversation goes wrong, report it from the chat itself. Click the
small flag in the chat's top-right corner (on the phone, tap the flag in the
Randall header). You can say what went wrong and leave a contact if you want.
**What gets sent** shows exactly what is included: the conversation, what
Randall did in it, which model answered, and any errors. It never includes
your AI key. The conversation goes privately to the developer, is not public,
and is kept for 90 days.

If you gave Randall files in that chat (for example a model ZIP to import),
the report shows a checkbox: **Include the files I attached**. It is on by
default, because the developer usually needs your exact file to see the same
problem. Randall's preview pictures of your model go with them. Files that are
too big are listed by name and size instead. Game files from your ISO and your
vault are never sent. Untick it to send only the conversation.

## If Nucleus will not open

Choose **Copy details and close** in the startup error window, then include
those details in your report. They contain the app version, operating system,
CPU, and backend error. The window also shows where a copy was saved.
Nothing is sent automatically.

## Update first

If a newer version of Nucleus is available, the form asks you to update
before reporting — many reports turn out to be bugs that are already fixed.
The Settings tab shows a gold dot whenever an update is waiting.

## What's in the logs

If the 3D viewer fails to start, its error includes details from the renderer.
Include that message in your report and mention which costume you opened.

- The app's own log files (what you clicked, what the builder did, any
  errors).
- A `diagnostics.txt` with your app version, OS, and where the app keeps its
  files.
- Optionally, Slippi Dolphin's logs and crash dumps — tick the checkbox if
  your problem happened **in game** (a crash while playing a Nucleus-built
  ISO). Never replays or ISOs.

Before anything is sent, your Windows/mac/Linux **username is scrubbed from
file paths** and anything that looks like a login token is blanked. Reports
are kept for 90 days, then deleted.

## If sending fails

- **"Update first"** — install the update from Settings → Updates, reproduce
  the bug, then report.
- **No connection** — the report needs internet; try again later.
