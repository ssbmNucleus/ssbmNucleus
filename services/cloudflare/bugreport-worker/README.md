# nucleus-bugreport

Private intake for the desktop app's **Settings → Bug report** card. The Flask
backend builds a logs zip, `POST`s the description here, `PUT`s the zip, and
the worker stores both in R2 and posts an embed to a **private** Discord
channel with a signed download link (the zip is attached directly when it is
under 8 MB). Nothing is posted to the public server; reporters stay anonymous
unless they type a contact or are signed in with Discord.

Outdated clients are refused (`426 outdated`) by comparing `app_version`
against `releases.ssbmnucleus.net/<platform>/latest.json` — the same manifest
the in-app updater reads. If that manifest is unreachable the gate fails
**open** (report accepted, `gate: "unchecked"` in meta).

## Report kinds

The POST meta may carry `kind`. When `kind` is absent the report is a **bug**,
so every released client is unchanged. Unknown kinds are also filed as bugs.

| kind | Sender | Discord ping |
|---|---|---|
| `bug` (default) | Settings → Bug report | `v<ver> · <platform>` + renderer errors |
| `chat` | "Report this chat" in Randall: desktop mods and tracker (`/api/mex/chat-reports/*`) and the mobile vault | **💬 Randall chat report**, plus surface, messages, tool calls, errors, model. Optional `chat: {surface, message_count, tool_calls, errors, conversation_id, model}` (bounded). An empty description becomes `(no note)` |
| `capability_gap` | Randall feature requests (wishes) | **💡 Randall feature request** |

`platform: "mobile"` is accepted **only** with `kind: "chat"`. It has no
release manifest, so the version gate is skipped (`gate: "n/a (mobile)"`). The
mobile vault posts cross-origin, so `OPTIONS` preflights on `/bugreport*`
answer `204` with permissive CORS headers. Every response already carried
`access-control-allow-origin: *`. The zip's R2 `customMetadata.kind` and the
download filename (`chatreport-…zip`) follow the kind. See
[`docs/dev/RANDALL.md`](../../../docs/dev/RANDALL.md#11-report-this-chat).

## Routes (`ssbmnucleus.net/bugreport/*`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/bugreport` | `{service, version}` ping |
| `POST` | `/bugreport` | JSON meta → rate limit (3/min/IP), version gate, returns `{id, max_zip_bytes, upload_ttl_s}`. Optional `Authorization: Bearer <supabase jwt>` adds the Discord username; a bad token degrades to anonymous. |
| `PUT` | `/bugreport/:id/zip` | raw `application/zip` body, `Content-Length` must equal the declared `zip_size`; streams into R2, writes `meta.json`, notifies Discord. `{ok, id, notified}` — Discord failure is `notified:false`, never a 5xx. A repeat PUT of an already-stored id answers `200 {ok, id, notified, already_stored: true}` from its receipt (nothing is stored or pinged again), so `404` always means "not delivered". |
| `GET` | `/bugreport/:id/zip?d=&exp=&sig=` | admin download (HMAC-signed link from the embed) |
| `GET` | `/bugreport/:id/meta?d=&exp=&sig=` | the meta JSON |

Errors: `400` bad field / size mismatch / not a zip · `404` unknown id · `410`
slot older than 1 h · `411` no content-length · `413` over cap · `426`
outdated (`{current, latest, url, notes}`) · `429` rate limited · `503` no R2
binding.

R2 layout: `r/<YYYYMMDD>/<id>/report.zip` + `meta.json`; pending slots `s/<id>`;
delivery receipts `d/<id>` (tiny; kept as long as the report).

## One-time setup (the Nucleus Cloudflare account)

```bash
export CLOUDFLARE_ACCOUNT_ID=<account id>
npx wrangler r2 bucket create nucleus-bug-reports
# retention lives in lifecycle rules, not code
npx wrangler r2 bucket lifecycle add nucleus-bug-reports --prefix r/ --expire-days 90
npx wrangler r2 bucket lifecycle add nucleus-bug-reports --prefix s/ --expire-days 1
npx wrangler r2 bucket lifecycle add nucleus-bug-reports --prefix d/ --expire-days 90
# secrets — pipe from 1Password so the values never hit a terminal or a file
op read "op://<vault>/<item>/webhook" | npx wrangler secret put DISCORD_WEBHOOK_URL
op read "op://<vault>/<item>/signing"  | npx wrangler secret put LINK_SIGNING_SECRET
npx wrangler deploy
```

`DISCORD_WEBHOOK_URL` is the webhook of a private channel (Channel → Edit →
Integrations → Webhooks). `LINK_SIGNING_SECRET` is any 32+ random bytes
(`openssl rand -hex 32`); rotating it invalidates every previously posted link.

If `wrangler deploy` rejects the `[[ratelimits]]` block on this account, delete
it and add a zone WAF rate-limiting rule on `http.request.uri.path contains
"/bugreport"` instead — the worker treats a missing binding as "no limit".

## Local testing

`npm test` runs `tests/services/bugreport-worker/worker.test.js` (repo root) on plain Node (in-memory R2, stubbed
manifest and Discord); it needs no install and no network.

```bash
npx wrangler dev --var RELEASES_BASE:http://127.0.0.1:8765   # serve a fake latest.json there
curl -s -X POST localhost:8787/bugreport -H 'content-type: application/json' \
  -d '{"platform":"windows","app_version":"0.1.0","description":"x","zip_size":22}'   # → 426
```

Point the desktop backend at it with `NUCLEUS_BUGREPORT_URL=http://127.0.0.1:8787/bugreport`.

## Reading reports without the Discord link

`python tools/admin/bug_reports.py list|get|rm` (boto3, same `R2_*` creds as
`tools/build/release_to_r2.py`; bucket from `R2_BUGREPORTS_BUCKET`). The
existing R2 token may be scoped to `nucleus-releases` only — widen it or mint
one for `nucleus-bug-reports`.
