# CSP Compression

CSP Compression is the simple export-side workaround for portrait memory limits.

## What It Does

When you lower the compression value during ISO export, Nucleus exports smaller CSP images into the build.

In practical terms, this is a portrait downscale setting.

Higher values keep more detail.

Lower values save more memory.

## Why It Exists

Melee has limited memory for menu portraits.

If a build has too many portrait images at full size, the game can become unstable or crash.

So this setting exists to trade portrait sharpness for stability and room.

## When To Use It

This is the easier option when:

- you just want a quick export
- you are testing a few skins
- you do not need HD Dolphin portraits
- you need the build to fit more safely inside Melee's normal portrait limits

That is why this is usually the better first choice for testing.

## How It Relates To Texture Pack Mode

CSP Compression and [Texture Pack Mode](Texture-Pack-Mode.md) solve different problems.

- CSP Compression keeps everything inside the ISO, just at a smaller portrait size
- Texture Pack Mode is the higher-effort path that uses Dolphin texture loading for better portrait quality

So the tradeoff is simple:

- use CSP Compression when you want fast, practical exports
- use Texture Pack Mode when you are polishing a finished build and want better portrait presentation

## Summary

CSP Compression is the simple "make the portraits lighter so Melee can handle them" option.

Texture Pack Mode is the more elaborate "let Dolphin load better portraits from outside the ISO" option.

## Related Pages

- [Texture Pack Mode](Texture-Pack-Mode.md)
- [Vault Backup And Restore](Vault-And-Distribution-Workflow.md)
