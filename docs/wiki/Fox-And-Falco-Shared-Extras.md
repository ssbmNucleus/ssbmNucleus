# Fox And Falco Shared Effects

Fox and Falco are the clearest example of why some effects are marked as shared and some are not.

The short version is:

- if the effect lives in `EfFxData.dat`, it is shared
- if the effect lives in `PlFx.dat` or `PlFc.dat`, it is not shared

That is the main reason the app presents some Fox/Falco effects as shared.

## Why Some Are Shared

Fox and Falco both use `EfFxData.dat` for some effect families.

So when an effect patches that file, it is not really making a separate Fox-only version and Falco-only version. It is changing one shared effect file that both characters use.

That is why the app marks those effects as shared.

## Why Some Are Not Shared

Other Fox/Falco effects live in their own character files:

- `PlFx.dat` for Fox
- `PlFc.dat` for Falco

When an effect patches those files, Fox and Falco can each have their own separate version of the effect.

That is why those effects are not marked as shared.

## Current Split

Not shared:

- laser
- side-B
- gun model

Those are character-local because they live in `PlFx.dat` or `PlFc.dat`.

Shared:

- shine
- up-B color
- up-B fire texture
- blaster flash (the streak burst on every blaster shot; formerly listed as "laser ring")

Those are shared because they use `EfFxData.dat`.

## Practical Rule

**Unreleased:** Falco's Spooky Phantasm afterimage model affects Falco only.
Installing it preserves the project's blaster and other fighter edits, including
an existing Animelee blaster. Choosing the Animelee version of this side-B
download does not install its bundled blaster as part of the afterimage extra.
See [Effects Workflow](Extras-And-Effects-Workflow.md) for import and restore behavior.

If you are looking at a Fox/Falco effect and wondering whether it should be shared, the question is usually just:

- does it patch `EfFxData.dat`?

If yes, shared makes sense.

If it patches `PlFx.dat` or `PlFc.dat`, it usually should not be shared.

## Summary

The app is not being arbitrary here.

Some Fox/Falco effects are shared because the underlying Melee file is shared.

Some are not shared because the underlying Melee file is character-specific.

## Related Pages

- [Effects Workflow](Extras-And-Effects-Workflow.md)
- [Melee Files Reference](reference/new-414/Melee-Files.md)
- [Effect Offsets Reference](reference/color-effects-reference/Effect-Offsets-Reference.md)
