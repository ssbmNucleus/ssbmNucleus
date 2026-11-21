# Native resource HUD

`own_meter` supplies a reusable per-player resource number on the native match HUD.
BCM consumes it for cash. Text uses the existing match camera/font and player HUD anchors;
green marks a bound buy, gold a bound sell, white an ordinary state. These are port UI
choices. The original source BUY/SELL particles, cards and other resource effects remain open.

The text GObj updates at priority 17, after native contacts/damage, so hitlag does not leave
the display waiting for the fighter animation callback. Values and colors change only when
needed. The native text destructor is wrapped to clear this module's slot, then delegates
the original text allocation/list cleanup. A fighter never destroys the shared font/canvas.
Ownership replacement, scene destruction, two player slots and hidden/sleeping state have
generated-C regressions; the component also compiles against MexTK.

Native references: `sislib.c` HSD_SisLib_803A611C / 803A6754 / 803A5A2C / 803A84BC;
`ifcoget.c` uses font 2 and the existing match camera, p_link 15 / GX link 11.
The first render exposed two format details: individual subtext scaling retains a large
baseline, and unsupported ASCII punctuation consumes a following byte as Shift-JIS.
The accepted build scales the viewport, places it above percent, and rejects unsupported
label characters (including `$`).

## Native evidence

Normal driver -> sounds -> build: `app/scratch/slapcity-bcman/bcman-meter-v3.iso`.
SHA-256: `41ddbfbfb7a4aef511aae319fffa4b069c2c59a813e9ae2693276ec3cb5693f3`.
An owned MCP session used BCM against a human-neutral Marth on Final Destination, with
no CPU or continuous target pinning. No text/layout RAM patches were used in the v3 acceptance.
An earlier v2 placement preview was explicitly a RAM experiment; it is not the accepted disc.

- Jab from zero cash: real contact, target DamageN2 and 6%, green `Cash 30` during hitlag;
  recovery retains 30 without another credit.
- Forward strong after explicitly seeding only cash to 400: target DamageFlyN and 24%,
  gold `Cash 0` during contact; recovery retains zero while Marth moves freely.

Evidence: `app/scratch/source-calibration/shared-timing/bcman-meter-native.json`;
screenshots `app/scratch/mcp/20261113-170934/bcman-meter-v3-buy.png` and
`bcman-meter-v3-sell.png`. Owned session closed.

Required suite: **664 passed, 6 skipped** (149.12 s). Normal package verification: **0 FAULT**,
51 file checks (30 ok, 21 say). Unanswered character acceptance items remain open.

BCM's custom specials, counter, remaining resource branches and source effects are still
unfinished and explicitly reported. Ranno's animation capacity and custom specials are
separate ongoing work. This component does not require users to run a harness.
