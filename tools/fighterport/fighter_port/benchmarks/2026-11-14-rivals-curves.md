# Rivals source curves and renderer bindings — 2026-11-14

The normal Rivals game-data reader retains animation float curves and the actual default skin's
renderer inheritance in `source_visuals`. The source material behavior was previously dropped.
This is shared reader work; native shader/visibility playback remains open.

Installed-source checks:

- Ranno: 184 source animation packages, 168 with curve data, 36 decoded through the new ACL scalar path.
- Zetterburn: 200 packages, 154 with curves. The tick contains an unsupported EX_LetObj; no unconditional
  material binding is invented, and the complete renderer functions remain in the output.
- Normal Ranno `gamedata.load` export: 47 moves, 11 hurtboxes and 184 curve records, completed in 36.07 s.
- Required suite: 674 passed, 6 skipped (128.85 s); focused Rivals reader suite: 34 passed, 2 skipped.
- uetool Release build passes with existing dependency advisory/nullability warnings.

Ranno's skin points to BP_Ran_Default, which inherits BP_Ran_Standard. Its effective ReceiveTick
enters ExecuteUbergraph_BP_Ran_Standard at statement 10, builds [SashGroup], obtains the recolorable
mesh components and calls SetParameterFromAnimCurve with Visible, SashVisible, true. The last
argument excludes the shield mesh; it does not invert the curve. SashGroup resolves to slot Sash.
Victory's float curve is near zero through 4.9 s and transitions to near one at 5.0 s. The exact
keys/tangents are retained. No native visibility threshold or hidden-track pruning is applied.

The scalar decoder follows ACL v2.1.0's scalar_tracks_header, bit-rate table and float1f decoding:
https://github.com/nfrechette/acl/blob/v2.1.0/includes/acl/core/impl/compressed_headers.h
https://github.com/nfrechette/acl/blob/v2.1.0/includes/acl/core/impl/variable_bit_rates.h
https://github.com/nfrechette/acl/blob/v2.1.0/includes/acl/decompression/impl/decompression.scalar.h
The local CUE4Parse AnimCurveCompressionCodec_ACL confirms compressed curve-name/track ordering.
Tests exercise unaligned raw floats alongside quantized/constant tracks, wrapped closing samples,
unknown layouts, partial bytecode, inheritance, branches and cache reuse.

A separate read-only redundant-key experiment reduced Win1 to 51,136 bytes at the existing loosest
scalar budget, still above 45,056, with 0.17662 rig-height maximum joint-position error. Rejected;
no production reducer, native buffer, rig or animation bank was changed by that experiment.
Ranno victory capacity, high-error clips and custom specials remain open. Owned game sessions are
closed and Steam remains offline.
