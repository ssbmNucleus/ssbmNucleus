# FigaCodec

Preserved from the accepted Incineroar catch-wait codec v2, formerly under
`tests/artifacts/mocap/20260905-pilots/incineroar-grab/catchwait-codec-v2/private-src/LocoCodec`.
This is a command-line asset compiler, independent of the host application.

Build with .NET 8 and an explicit HSDRaw assembly directory:
`dotnet build FigaCodec.csproj -p:HsdBin=<assembly-directory> -o <new-output>`.
The HSDRaw source lives in `app/utility/tools/HSDLib/HSDRaw`.
Keep the exact assembly hash with build receipts.

Modes: `encode <baseline-AJ> <curves.json> <out-directory> [motion]` and
`audit <figatree.dat> <new-output.json>`. Each channel may specify a positive
`quantization` tolerance (default 0.0001). Verify packed world/skin error after
encoding; scalar tolerances alone do not certify geometry fidelity.

FOBJ uses integer packed delta times, despite the editor exposing floating point
frame values. Fractional key times are rejected explicitly. Slope-only commands
do not advance the animation clock.
