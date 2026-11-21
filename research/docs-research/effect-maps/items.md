# Items-pass effect map — PK Fire pillar, up-B coins, Link bomb (MAP 2026-07-02)

Mission: the extras campaign's ITEMS-PASS — effects that live in ITEM article
files / per-fighter player files / unattributed common scripts, headlined by
**Ness PK Fire** (the burn PILLAR) and the **Mario/Luigi up-B "coin" ring**.

TL;DR verdicts:
- **PK Fire flame pillar** → 🟢 **VERIFIED colorable** in **`PlNs.dat`** (three
  `070707` blocks: two blue rings + one orange aura). Bag-verified this pass.
- **PK Fire cast lens-flare** (`PlNs.dat` 0x10194) → ⚪ **DEAD** (the hand muzzle
  flash is article/self-colored, no response — confirms ness.md).
- **PK Fire pillar 42 material blocks** → ⚪ no visible response (subtle/no-op,
  Mario-tornado-42 precedent).
- **Mario/Luigi up-B "coin" ring** → 🎨 **TEXTURE-ONLY common effect**, NOT a
  colorable ptcl/model record. The gold-coin sprite is a texture in EfCoData's
  tex bank. mario.md already killed the EfMrData CF records (⚪); this pass
  confirms STATICALLY it is texture-path, not any color operand. **Route to the
  EfCoData texture pass, do not wire as a color extra.**
- **Link bomb explosion** → not re-attempted (harness bomb-throw recipe still
  missing). Static verdict unchanged: bomb visuals are the article DAT model /
  `PlLk.dat` / EfCoData, NOT EfLkData (see link.md). Flagged, not mapped.

Probe spec: `backend/probes/ness_pkfire_probe.json`. Captures:
`tests/artifacts/datram-probe-ness-pkfire/` (bag = DK dx=10, PK Fire connects
point-blank → DamageAir1/2/DamageN2, pillar renders f24-f60).

---

## 1. Item architecture (decomp ground truth)

`src/melee/it/items/` — the relevant item source:

- **`itnesspkfire.c` / `itnesspkfirepillar.c`** — PK Fire is TWO items:
  `It_Kind_Ness_PKFire` (the travelling bolt) which, on hit/clank
  (`it_2725_Logic23_DmgDealt`), spawns `It_Kind_Ness_PKFire_Flame` (the burn
  PILLAR) via `itNesspkfirepillar_802AA494`. **Neither has an `efSync_Spawn`
  call** — both articles draw their own animated JOBJ models. Those models +
  their material/070707 color blocks live in **`PlNs.dat`** (the player file),
  NOT in EfNsData and NOT in ItCo.dat. This is why ness.md (EfNsData scope)
  correctly found the pillar was "not an EfNsData model block" — it's PlNs.
- **`itcoin.c`** — this is the **money/bonus COIN item** (`It_Kind_Coin`, the
  coin that drops on Peach's Castle / in coin mode), its model in `ItCo.dat`.
  It is **NOT** the Mario up-B "coin punch" visual. Do not conflate them.
- **`itmariofireball.c` / `itmariocape.c`** — Mario articles (mapped in mario.md,
  EfMrData + PlMr).
- **`itlinkbomb.c` / `itlinkboomerang.c` / `itlinkarrow.c` / `itlinkhookshot.c`**
  — Link articles (mapped/quarantined in link.md; bomb/boomerang = article DAT
  model / PlLk.dat, arrow/hookshot = EfCoData gfx 1096/1052/1009).

**Mario/Luigi up-B "coin" has NO item and NO C-level effect spawn.**
`ftMr_SpecialHi.c` (and the Luigi equivalent) contain zero `efSync_Spawn` — the
coin GFX is a **subaction event-GFX** baked in the fighter's animation data
(AJ), referencing a **common-bank (EfCoData) effect id < 1000**. It is the
classic SMB gold-coin sprite = a **texture**, not a color record. Same class as
the §3b texture-only marquee effects in `efcodata.md` (Din's Fire, Vanish, etc.).

**`ItCo.dat` is a plain item-model archive**, NOT an `SBM_EffectTable`
(`ptcl_parse` chokes on it). Root symbol `itPublicData` + fire-flower/beam-sword
anim joints. It holds the COMMON pickup-item models (coin item, fire flower,
beam sword, capsule, bob-omb, …). None of PK Fire / up-B coin ring / Link bomb
live here.

---

## 2. PK Fire flame PILLAR — `PlNs.dat` — 🟢 VERIFIED

Extra name suggestion: **`ness_pk_fire`** (pillar). Target file `PlNs.dat`
(356055 B). Marker-verified `07 07 07 04` blocks; c1 = bright core @marker+4,
c2 = glow @marker+8 (lesson 2). All offsets byte-verified against vanilla
`storage/test-base/files/PlNs.dat` 2026-07-02.

| layer_id | format | marker | c1 off / vanilla | c2 off / vanilla | semantic | verdict |
|---|---|---|---|---|---|---|
| pillar_ring_in_c1 | 070707 | 0x11A8C | 0x11A90 `FFFFFF` | — | pillar bottom ring INSIDE core | 🟢 |
| pillar_ring_in_c2 | 070707 | 0x11A8C | — | 0x11A94 `007FFF` | pillar bottom ring INSIDE glow (blue) | 🟢 (turned green/magenta) |
| pillar_aura_c1 | 070707 | 0x11B58 | 0x11B5C `FFFFE5` | — | pillar MAIN fire aura core (cream) | 🟢 |
| pillar_aura_c2 | 070707 | 0x11B58 | — | 0x11B60 `FF9900` | pillar MAIN fire aura glow (orange) | 🟢 |
| pillar_ring_out_c1 | 070707 | 0x11DF8 | 0x11DFC `FFFFFF` | — | pillar bottom ring OUTSIDE core | 🟢 |
| pillar_ring_out_c2 | 070707 | 0x11DF8 | — | 0x11E00 `007FFF` | pillar bottom ring OUTSIDE glow (blue) | 🟢 (turned green/magenta) |

**LIVE (bag):** poked all 6 (c1→green `00FF00`, c2→magenta `FF00FF`). At the
clean hit frame f24 the vanilla **blue horizontal ring** through DK's midsection
turned unmistakably **bright GREEN** with **magenta glow edges + magenta
sparks**; at f32 the whole pillar base glowed green + purple. Strong, clean,
on every PK-Fire connect. Captures:
`pkfire_pillar_07-sideb-f24.png`/`-f32.png` vs `vanilla-sideb-f24.png`/`-f32.png`.

> The pillar's main **orange fire body** (the tall flame column texture) did NOT
> recolor — that is texture-driven, a separate texture lead. But the RING
> accents + aura glow (the 070707 c2 blocks) are fully colorable. This matches
> the vanilla layout: `007FFF` blue rings are the editable part, the fire body
> is texture.

### Per-record vanilla bytes (lesson 12 — split per record; c1 differ)

`pillar_aura` c1 is `FFFFE5` (cream) while the two rings' c1 are `FFFFFF` —
so WIRE keys each record separately, no shared vanilla. c2: rings `007FFF`,
aura `FF9900`.

### Follow-up 42 material blocks (⚪ no visible response — do NOT ship)

Same pillar region has `4248` material blocks (diffuse @block+4):
0x11B00 `FFFFCC`, 0x11BCC `CCE6FF`, 0x11C6C/0x11D0C/0x11DAC `FFFFFF`,
0x11E6C/0x11F0C/0x11F38 `FFFFCC`. Poked all 8 magenta — NO visible change to the
pillar vs vanilla at any frame (the 07 rings dominate). Consistent with the
Mario-tornado-42 finding (42 diffuse = minor/no-op secondary here). Listed for
completeness; not primary layers.

### AUDIT_HINTS

- `ness sideb frames [24, 32, 44]` **with the bag** (PK Fire is on-hit — the
  pillar only forms when the bolt connects). effect_probe/extras_audit bag key:
  `"bag": {"char": "dk", "dx": 10}` — dx=10 puts DK point-blank so PK Fire
  connects on ~f22 and the pillar renders f24+.
- Anti-colors per operand (lesson 11): c1 cores are white/cream → poke green or
  magenta; c2 glows are blue (rings) / orange (aura) → green/magenta are far
  from both. Verified good.
- Shared by: **PK Fire is Ness-only** (Kirby-Ness copy would draw the same
  PlNs? — Kirby copies use `PlKbNs`-style article; not confirmed here, low
  priority). No Doc/YLink sharing.

---

## 3. PK Fire cast lens-flare — `PlNs.dat` 0x10194 — ⚪ DEAD

| layer | marker | c1 off / vanilla | c2 off / vanilla | verdict |
|---|---|---|---|---|
| lensflare | 0x10194 | 0x10198 `FFFF66` | 0x1019C `FFE500` | ⚪ DEAD |

**LIVE:** poked c1→green / c2→magenta. The yellow-green **muzzle-flash ring at
Ness's hand** on cast (f08) was **IDENTICAL** vanilla vs poked. The hand cast
flash is drawn by the bolt article's own model / a common effect, not this
block (or this block drives an unlit element). Confirms ness.md's "PK Fire cast
flash = article/common". Not shippable. Captures: `pkfire_lensflare_07-sideb-f08.png`
== `vanilla-sideb-f08.png`.

---

## 4. Mario / Luigi up-B "coin" ring — 🎨 TEXTURE-ONLY common effect (do NOT wire as color)

**Static verdict (this pass) + prior LIVE (mario.md, efcodata.md):**

- The up-B "coin" is the SMB **gold-coin SPRITE** — a **texture**, spawned by a
  subaction event-GFX resolving into **EfCoData** (common bank, gfx < 1000). No
  fighter C code spawns it (`ftMr_SpecialHi.c` / Luigi equivalent = zero
  `efSync_Spawn`). Same class as the §3b texture-only marquee specials in
  `efcodata.md` (Din's Fire, Vanish, Quick Attack, Bowser Bomb, Link arrow).
- **mario.md already killed the EfMrData CF records** (`upb_coin` s11/s12/s13 at
  0x62C–0x70F): with a DK bag taking the up-B, poking all 6 green/magenta AND
  far-red produced NO change to the on-contact cyan-teal coin ring → common-bank.
  ⚪ DEAD, do not ship.
- **Luigi's** `spark_yellow_s9/s10` (EfLgData CF 0x536/0x5A6…) are the analogous
  on-hit up-B sparks — flagged on-hit-pending in the Luigi WIRE notes; those are
  the *spark*, not the coin sprite.

**Conclusion:** the up-B coin ring is **NOT colorable with the ptcl/model color
editor**. To make the coin recolorable it needs the **EfCoData texture pass**
(decode the TEXGraphicBank, find the coin/ring texGroup, hue-shift like Fox
`upb_texture` / Samus `charge_shot`). This is the honest answer to the user's
"up-B coins" request: it's a texture edit, not a color-slot edit.

**WIRE list: nothing to wire here.** Route to the EfCoData §5 texture pass
(efcodata.md open lead 3). Owner would be a "Common Effects" / per-char texture
extra (the coin sprite is shared by Mario + Dr. Mario + Luigi up-B).

---

## 5. Link bomb explosion — flagged, not mapped

The mission's fallback: try a fresh bomb-throw recipe (downb pulls, then
forward+A / Z-throw to throw + detonate). Per lesson 15, **Z is swallowed by the
Slippi pipe** and the current `ingame/moves.py` has no throw-item recipe (only
grab = L+A). Building a pull→throw→detonate input chain is a harness change
beyond a couple of attempts, so per the mission's own "if unworkable, static-map
only and flag" clause:

**Static verdict (from link.md, unchanged):** Link's bomb explosion, boomerang
trail, arrow, hookshot are **NOT EfLkData ptcl/color records** (EfLkData has no
ptcl bank; only `spin_attack_trail` at 0x5510/0x5514 is a live-verified EfLkData
color = the up-B spin disc). Bomb/boomerang colors → **article DAT model +
`PlLk.dat`** (ref mods 15262/15263 diff PlLk, not EfLkData) and/or **EfCoData
common bank**. YLink shares EfLkData + PlCl.

**WIRE list: nothing new.** Bomb explosion remains an open lead needing (a) a
throw-item + detonate harness recipe, and (b) a PlLk.dat-focused mapping pass
(the bomb's article model colors are in PlLk, cross-referenced to link.md's
quarantine). Flagged for a future PlLk mission.

---

## 6. Cross-reference notes (for the sibling specs)

- **ness.md:** add — PK Fire's burn PILLAR IS colorable, but in **`PlNs.dat`**
  (0x11A8C/0x11B58/0x11DF8 070707 rings+aura), NOT EfNsData. ness.md correctly
  found it wasn't an EfNsData model block; this pass located + bag-verified the
  PlNs blocks. The cast lens-flare (PlNs 0x10194) stays ⚪ DEAD (article/common,
  confirms ness.md). See §2/§3 here. Extra `ness_pk_fire` is WIRE-ready.
- **mario.md:** confirm — the up-B "coin" ring is a **texture-only EfCoData
  effect** (the coin SPRITE), which is *why* the EfMrData CF records were ⚪ DEAD
  under the bag. Not a color extra; route to the EfCoData texture pass. No
  change to mario.md's verdicts (already ⚪).
- **link.md:** confirm — bomb/boomerang not in EfLkData; the item source
  (`itlinkbomb.c` etc.) has no `efSync_Spawn`, so their visuals are the article
  DAT model / PlLk.dat / EfCoData. Bomb explosion remains an open lead pending a
  throw+detonate harness recipe (Z-swallow blocker per lesson 15) + a PlLk pass.
- **efcodata.md:** add — the Mario/Luigi up-B **coin sprite** is another §3b
  texture-only common effect (subaction event-GFX, no C caller, texture-driven).
  Add to the texture-pass shopping list alongside Din's Fire / Vanish etc. The
  coin ring texGroup is a lead for the TEXGraphicBank decode.

---

## 7. WIRE-ready summary

**Ship this pass: 1 extra.**

### Extra `ness_pk_fire` — target `PlNs.dat` — 🟢 VERIFIED

PK Fire burn-PILLAR ring + aura. Three `070707` blocks, 6 color operands.
On-hit (needs the bag to demonstrate: PK Fire connects → pillar).

| layer_id | format | offset | vanilla | semantic |
|---|---|---|---|---|
| pillar_ring_in_c1  | 070707 core | 0x11A90 | `FFFFFF` | bottom ring inside core |
| pillar_ring_in_c2  | 070707 glow | 0x11A94 | `007FFF` | bottom ring inside glow (blue) |
| pillar_aura_c1     | 070707 core | 0x11B5C | `FFFFE5` | main fire aura core (cream) |
| pillar_aura_c2     | 070707 glow | 0x11B60 | `FF9900` | main fire aura glow (orange) |
| pillar_ring_out_c1 | 070707 core | 0x11DFC | `FFFFFF` | bottom ring outside core |
| pillar_ring_out_c2 | 070707 glow | 0x11E00 | `007FFF` | bottom ring outside glow (blue) |

- Markers `07 07 07 04` at 0x11A8C / 0x11B58 / 0x11DF8; c1 = marker+4, c2 =
  marker+8. Per-record vanilla differ (aura c1 `FFFFE5` ≠ ring c1 `FFFFFF`) —
  key each record separately (lesson 12).
- Editor grouping: two `_c1`/`_c2` sub-groups — **rings** (in+out, blue glow)
  and **aura** (orange glow) — OR one flat 6-operand list. Rings are the strong
  visual (blue→green was dramatic); aura orange→magenta was visible on the base.
- AUDIT_HINTS: `ness sideb frames [24, 32, 44]`, `"bag": {"char": "dk", "dx": 10}`.
  Forced anti-colors: c1 = `00FF00`, c2 = `FF00FF` (far from white/cream cores
  and blue/orange glows). Ness-only.
- On-hit: yes — the pillar only forms on a PK Fire connect. Fully colorable
  every time it forms (not harness-blocked; the bag demonstrates it cleanly).

**Do NOT ship (routed elsewhere):** PK Fire lens-flare (⚪ dead), PK Fire pillar
42 blocks (no-op), Mario/Luigi up-B coin (texture pass), Link bomb (open lead +
PlLk pass).
