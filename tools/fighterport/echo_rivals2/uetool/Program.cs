// Rivals 2 pak reader (CUE4Parse), the source of echo_rivals2's reads. Usage:
//   uetool summary                       counts of files by their first three folders
//   uetool list <substring>              every path containing the substring
//   uetool props <path>                  the package's objects and their properties as JSON (needs the mappings:
//                                        the game is cooked with unversioned properties)
//   uetool export <pkg[,pkg...]> <outdir> meshes, skeletons, clips and pictures through CUE4Parse-Conversion
//                                        (UE_MESH=psk: psk/psa, the default glTF for meshes; clips are never glTF)
//   uetool scripts <path>                Blueprint functions, including decoded bytecode
//   uetool animation-curves <pkg[,pkg...]>  complete float curves, timing and interpolation data
//   uetool raw <path> <outfile>          one file of the pak as it is stored (an .ini, a .bank)
//   uetool acl-raw <pkg[,pkg...]> <outdir>  an ACL-compressed clip's own bytes and track table (echo_rivals2/acl.py)
//   uetool fmod-events <Desktop> <bank,...>  the FMOD banks' event table: {event path: [sample, ...]}
// Where things are comes from the environment, with no defaults (a missing one is said, and the tool stops):
//   RIVALS2_PAKS   the game's Paks folder
//   OODLE_DLL      an oo2core_9_win64.dll (the pak is Oodle-compressed; the game's own install has none)
//   RIVALS2_USMAP  the mappings dumped from the running game (see the reader's README)
// Copied 2026-11-13 from app/scratch/rivals2/uetool (where it was first written) so that the recipe owns it.
using CUE4Parse.Compression;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using Newtonsoft.Json;

if (args.Length > 2 && args[0] == "fmod-events")
    return FmodEvents(args[1], args[2]);

string Need(string name, string what)
{
    var v = Environment.GetEnvironmentVariable(name);
    if (string.IsNullOrEmpty(v))
    {
        Console.Error.WriteLine($"uetool: set {name} to {what}");
        Environment.Exit(2);
    }
    return v!;
}
var Paks = Need("RIVALS2_PAKS", "the game's Paks folder (<install>/Rivals2/Content/Paks)");
var Oodle = Need("OODLE_DLL", "an oo2core_9_win64.dll already on the machine (another Unreal game's install may hold one)");
// without the mappings only file names can be read (the game is cooked with unversioned properties)
var Usmap = Need("RIVALS2_USMAP", "the mappings (.usmap) dumped from the running game");

OodleHelper.Initialize(Oodle);
var game = Enum.Parse<EGame>(Environment.GetEnvironmentVariable("UE_GAME") ?? "GAME_UE5_LATEST");
var provider = new DefaultFileProvider(Paks, SearchOption.TopDirectoryOnly, new VersionContainer(game));
if (File.Exists(Usmap)) provider.MappingsContainer = new FileUsmapTypeMappingsProvider(Usmap);
provider.Initialize();
provider.SubmitKey(new FGuid(), new FAesKey(new byte[32]));
// the plugins' mount points (/ACLPlugin/ -> Engine/Plugins/Animation/ACLPlugin/Content): a clip compressed by the ACL
// plugin names its codec there, and without them the codec is never found (the clip reads with no data at all)
provider.LoadVirtualPaths();

var mode = args.Length > 0 ? args[0] : "summary";
switch (mode)
{
    case "acl-raw":
        // acl-raw <clip pkg[,pkg...]> <outdir>: each ACL-compressed clip's own bytes (the ACL library's compressed
        // tracks, base64), its track-to-bone table, frames, length and rate scale, as <outdir>/<name>.json, for the
        // recipe's own decoder (echo_rivals2/acl.py): CUE4Parse decodes ACL only through a native library
        // (CUE4Parse-Natives) that is not in its NuGet package
        Directory.CreateDirectory(args[2]);
        foreach (var pkg in args[1].Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var name = pkg.Split('/').Last();
            try
            {
                var seq = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.Animation.UAnimSequence>($"{pkg}.{name}");
                var acl = seq.CompressedDataStructure as CUE4Parse.UE4.Assets.Exports.Animation.ACL.FACLCompressedAnimData;
                // the skeleton's reference pose: ACL leaves a sub-track that holds it out of the data, and the
                // ActorX clip carries it as its bone table
                var skel = seq.Skeleton.Load<CUE4Parse.UE4.Assets.Exports.Animation.USkeleton>();
                var refs = skel?.ReferenceSkeleton;
                var o = new Dictionary<string, object?>
                {
                    ["clip"] = pkg,
                    ["name"] = name,
                    ["codec"] = seq.CompressedDataStructure?.GetType().Name,
                    ["codec_handle"] = seq.BoneCodecDDCHandle,
                    ["frames"] = seq.NumFrames,
                    ["seconds"] = seq.SequenceLength,
                    ["rate_scale"] = seq.RateScale,
                    ["additive"] = seq.IsValidAdditive(),
                    ["track_to_bone"] = seq.CompressedTrackToSkeletonMapTable.Select(t => t.BoneTreeIndex).ToArray(),
                    ["skeleton"] = skel?.GetPathName(),
                    ["bones"] = refs?.FinalRefBoneInfo.Select((bi, i) => new Dictionary<string, object>
                    {
                        ["name"] = bi.Name.Text,
                        ["parent"] = bi.ParentIndex,
                        ["q"] = new[] { refs.FinalRefBonePose[i].Rotation.X, refs.FinalRefBonePose[i].Rotation.Y, refs.FinalRefBonePose[i].Rotation.Z, refs.FinalRefBonePose[i].Rotation.W },
                        ["t"] = new[] { refs.FinalRefBonePose[i].Translation.X, refs.FinalRefBonePose[i].Translation.Y, refs.FinalRefBonePose[i].Translation.Z },
                        ["s"] = new[] { refs.FinalRefBonePose[i].Scale3D.X, refs.FinalRefBonePose[i].Scale3D.Y, refs.FinalRefBonePose[i].Scale3D.Z },
                    }).ToArray(),
                    ["acl"] = acl?.CompressedByteStream is { } b ? Convert.ToBase64String(b) : null,
                };
                File.WriteAllText(Path.Combine(args[2], name + ".json"), JsonConvert.SerializeObject(o, Formatting.Indented));
                Console.WriteLine($"ok   {pkg}: {o["codec"]} ({seq.BoneCodecDDCHandle}), {seq.NumFrames} frames, {acl?.CompressedByteStream?.Length ?? 0} bytes");
            }
            catch (Exception e)
            {
                Console.WriteLine($"FAIL {pkg}: {e.GetType().Name}: {e.Message}");
            }
        }
        break;
    case "summary":
        Console.WriteLine($"{provider.Files.Count} files, game {game}");
        foreach (var g in provider.Files.Keys
                     .Select(k => string.Join('/', k.Split('/').Take(3)))
                     .GroupBy(k => k).OrderByDescending(g => g.Count()).Take(80))
            Console.WriteLine($"{g.Count(),7}  {g.Key}");
        break;
    case "list":
        foreach (var k in provider.Files.Keys.Where(k => k.Contains(args[1], StringComparison.OrdinalIgnoreCase)).OrderBy(k => k))
            Console.WriteLine(k);
        break;
    case "animation-curves":
        var curves = new SortedDictionary<string, object>();
        foreach (var pkg in args[1].Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var seq = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.Animation.UAnimSequence>(
                $"{pkg}.{pkg.Split('/').Last()}");
            if (seq.CompressedCurveNames is { Length: > 0 } && !seq.CompressedCurveData.HasValue
                && !(seq.CurveCodecPath?.Contains("AnimCurveCompressionCodec_ACL") ?? false))
                throw new InvalidDataException($"{pkg}: animation curves were not decoded ({seq.CurveCodecPath})");
            curves[pkg] = new Dictionary<string, object?>
            {
                ["frames"] = seq.NumFrames, ["seconds"] = seq.SequenceLength, ["rate_scale"] = seq.RateScale,
                ["curve_names"] = seq.CompressedCurveNames, ["curves"] = seq.CompressedCurveData,
                ["codec"] = seq.CurveCodecPath,
                ["acl"] = !seq.CompressedCurveData.HasValue && seq.CompressedCurveByteStream is { Length: > 0 } cb
                    ? Convert.ToBase64String(cb) : null,
            };
        }
        Console.WriteLine(JsonConvert.SerializeObject(curves, Formatting.Indented));
        break;
    case "scripts":
        // Explicit opt-in: ordinary property reads need not deserialize every Blueprint function.
        // Kept separate from props so an old properties cache cannot hide executable source behavior.
        provider.ReadScriptData = true;
        var functions = provider.LoadPackage(args[1]).GetExports()
            .OfType<CUE4Parse.UE4.Objects.UObject.UFunction>().ToArray();
        Console.WriteLine(JsonConvert.SerializeObject(functions, Formatting.Indented));
        break;
    case "props":
        var objs = provider.LoadPackage(args[1]).GetExports();
        Console.WriteLine(JsonConvert.SerializeObject(objs, Formatting.Indented));
        break;
    case "raw":
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[2]))!);
        File.WriteAllBytes(args[2], provider.SaveAsset(args[1]));
        Console.WriteLine($"{args[1]} -> {args[2]}");
        break;
    case "export":
        // args[1]: package path without extension, e.g. Rivals2/Content/Characters/Zetterburn/Skins/Default/SK_Zet_Default
        // (one or more, comma separated); args[2]: output folder.
        var fmt = Environment.GetEnvironmentVariable("UE_MESH") switch
        {
            "psk" => CUE4Parse_Conversion.Options.EMeshFormat.ActorX,
            "ueformat" => CUE4Parse_Conversion.Options.EMeshFormat.UEFormat,
            "usd" => CUE4Parse_Conversion.Options.EMeshFormat.USD,
            _ => CUE4Parse_Conversion.Options.EMeshFormat.Gltf2,
        };
        var eopts = new CUE4Parse_Conversion.Options.ExportOptions(meshFormat: fmt, exportMaterials: false);
        var session = new CUE4Parse_Conversion.ExportSession();
        Directory.CreateDirectory(args[2]);
        foreach (var pkg in args[1].Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var name = pkg.Split('/').Last();
            session.Add(provider.LoadPackageObject($"{pkg}.{name}"));
        }
        var results = await session.RunAsync(args[2], eopts, null, CancellationToken.None);
        foreach (var r in results)
            Console.WriteLine($"{(r.Success ? "ok  " : "FAIL")} {r.ObjectPath} -> {string.Join(", ", r.DiskFilePaths ?? [])} {r.Error}");
        break;
    default:
        Console.Error.WriteLine("modes: summary | list <substring> | props <path> | scripts <path> | animation-curves <pkg[,pkg...]> | export <pkg[,pkg...]> <outdir> | raw <path> <outfile> | acl-raw <pkg[,pkg...]> <outdir> | fmod-events <Desktop dir> <bank,...>");
        return 2;
}
return 0;

// The FMOD banks' EVENT TABLE (what each event plays), read with CUE4Parse's own FMOD reader: each named bank's
// metadata `<name>.bank` and its sounds `<name>.assets.bank` are read and merged, the events resolved to the samples
// their timelines, instruments and playlists reach (EventNodesResolver), and each event named by its path from
// `Master.strings.bank`. Prints one JSON object: {event path: {"bank": bank, "samples": [sample name, ...]}} (an event
// no string names is keyed by its guid). Takes no pak: it is answered before the provider is made.
static int FmodEvents(string desktop, string banks)
{
    var strings = new CUE4Parse.UE4.FMod.FModReader(new BinaryReader(File.OpenRead(Path.Combine(desktop, "Master.strings.bank"))), "Master.strings");
    var outp = new SortedDictionary<string, Dictionary<string, object>>();
    foreach (var bank in banks.Split(',', StringSplitOptions.RemoveEmptyEntries))
    {
        CUE4Parse.UE4.FMod.FModReader? reader = null;
        foreach (var part in new[] { bank + ".bank", bank + ".assets.bank" })
        {
            var file = Path.Combine(desktop, part);
            if (!File.Exists(file)) continue;
            var r = new CUE4Parse.UE4.FMod.FModReader(new BinaryReader(File.OpenRead(file)), Path.GetFileNameWithoutExtension(file));
            if (reader == null) reader = r; else reader.Merge(r);
        }
        if (reader == null) { Console.Error.WriteLine($"no bank {bank}"); return 3; }
        var events = CUE4Parse.UE4.FMod.Utils.EventNodesResolver.TryResolveAudioEvents(reader, out _);
        foreach (var (guid, samples) in events)
        {
            var name = strings.StringTable?.RadixTree is { } tree && tree.TryGetString(guid, out var path) ? path : guid.ToString();
            outp[name] = new Dictionary<string, object>
            {
                ["bank"] = bank,
                ["samples"] = samples.Select(s => s.Name ?? "?").OrderBy(s => s).ToList(),
            };
        }
    }
    Console.WriteLine(JsonConvert.SerializeObject(outp, Formatting.Indented));
    return 0;
}
