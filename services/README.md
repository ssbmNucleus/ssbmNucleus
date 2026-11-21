# services/

Things that are deployed somewhere other than the desktop app. Nothing here ships in the installer.

- `cloudflare/replay-worker` serves `ssbmnucleus.net/replay/*` share pages. `cloudflare/bugreport-worker` is the private bug-report intake (`ssbmnucleus.net/bugreport/*`, R2 `nucleus-bug-reports`). `cloudflare/copyright-email-worker` handles copyright-notice email (deployed with `npm run deploy`).
  Deploy: `cd services/cloudflare/<worker> && npm test && CLOUDFLARE_ACCOUNT_ID=<account id> npx wrangler deploy`, with the Nucleus account's id (replay-worker has no tests; deploy the bug-report worker before releasing an app that needs it).
- `mobile/` is the phone vault PWA, deployed to Cloudflare Pages project `nucleus-vault`; esbuild comes from `app/frontend/node_modules`.
  Deploy: `python services/mobile/build.py <site_dir>` (add `--assets` to rebuild packs/icons), then `npx wrangler pages deploy <site_dir> --project-name nucleus-vault`.
- Tests live in the repo-root `tests/services/` (not here): `node --test --experimental-test-isolation=none tests/services/mobile/**/*.test.js` from the repo root, and `npm test` inside `cloudflare/bugreport-worker` and `copyright-email-worker` (their scripts point at `tests/services/<worker>/`). The Friends presence worker was removed in 0.8.16; its source is on the `archive/friends` tag.
