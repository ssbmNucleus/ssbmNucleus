"""The vault's side catalogs outside the routes: where each kind of library item
is stored and how its index is read and written.

Shared by the Vault routes (vault/routes/) and the Projects routes that install
or build from those items (projects/routes/), so neither imports the other.

  codes.py              Gecko code catalog (storage/codes/), seeded from the bundled library
  bundles.py            .ssbm bundles (storage/bundles/) and their index entries
  custom_stages.py      custom stage index reads (metadata.json["custom_stages"])
  custom_characters.py  custom character index reads, fighter.zip rewriting, skin CSP lookup
"""
