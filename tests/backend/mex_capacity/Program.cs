// Exercise the shipped native compiler, not a Python copy of its allocation rules.
// No Nintendo assets: a synthetic DOL supplies empty default lookup tables.
using System.Buffers.Binary;
using System.Reflection;
using System.IO.Compression;
using System.Text.Json;
using mexLib;
using mexLib.Utilties;

static void Check(bool value, string message)
{
    if (!value) throw new Exception(message);
}

string root = Path.GetFullPath(args[0]);
Directory.CreateDirectory(Path.Combine(root, "sys"));
Directory.CreateDirectory(Path.Combine(root, "files"));
byte[] dol = new byte[0x40100];
// DOL data section covering both native default effect/stage lookup tables.
BinaryPrimitives.WriteUInt32BigEndian(dol.AsSpan(0x1C), 0x100);
BinaryPrimitives.WriteUInt32BigEndian(dol.AsSpan(0x64), 0x803C0000);
BinaryPrimitives.WriteUInt32BigEndian(dol.AsSpan(0xAC), 0x40000);
File.WriteAllBytes(Path.Combine(root, "sys", "main.dol"), dol);
var workspace = new MexWorkspace();
// Workspace creation otherwise requires an ISO; only the path setter is private.
typeof(MexWorkspace).GetProperty("FilePath", BindingFlags.Instance | BindingFlags.NonPublic)!
    .SetValue(workspace, root + Path.DirectorySeparatorChar);
var gen = new MexGenerator(workspace);
Check(gen.EffectFiles.Count == 51, "Synthetic default table did not initialize");
Check(gen.GetEffectID("", "symbol") == -1, "Effectless fighter acquired a slot");
Check(gen.GetEffectID("anything", "") == -1, "Missing symbol acquired a slot");

void Write(string name, int value) => File.WriteAllBytes(workspace.GetFilePath(name), BitConverter.GetBytes(value));
string ImportEffect(string name, int value)
{
    using var bytes = new MemoryStream();
    using (var zip = new ZipArchive(bytes, ZipArchiveMode.Create, leaveOpen: true))
    using (var entry = zip.CreateEntry(name).Open())
        entry.Write(BitConverter.GetBytes(value));
    bytes.Position = 0;
    using var read = new ZipArchive(bytes, ZipArchiveMode.Read);
    return read.TryReadFile(workspace, name);
}
Write("EfImport.dat", 4321);
Check(ImportEffect("EfImport.dat", 4321) == "EfImport.dat", "Identical package file was renamed");
string renamed = ImportEffect("EfImport.dat", 8765);
Check(renamed != "EfImport.dat", "Different package bytes replaced an existing effect");
Check(workspace.FileManager.Get(workspace.GetFilePath(renamed)).AsSpan().SequenceEqual(BitConverter.GetBytes(8765)),
    "Renamed effect lost its distinct bytes");
Check(File.ReadAllBytes(workspace.GetFilePath("EfImport.dat")).AsSpan().SequenceEqual(BitConverter.GetBytes(4321)),
    "Original effect was overwritten by a variant");
Write("EfClone.dat", 1234);
Write("EfClone_001.dat", 1234);
Write("EfClone_002.dat", 5678);
int first = gen.GetEffectID("EfClone.dat", "effect");
Check(gen.GetEffectID("EfClone_001.dat", "effect") == first, "Equal bytes used a second slot");
int variant = gen.GetEffectID("EfClone_002.dat", "variant");
Check(variant != first, "Distinct clone bytes were collapsed");
var allocated = new HashSet<int> { first, variant };
for (int i = 0; i < 61; i++)
{
    string name = $"EfUnique{i}.dat";
    Write(name, 10000 + i);
    allocated.Add(gen.GetEffectID(name, "effect"));
}
Check(gen.EffectFiles.Count == 64, "Boundary table must contain exactly 64 slots");
Check(allocated.Count == 63 && !allocated.Contains(30), "Reserved slot 30 was consumed");
Check(gen.GetEffectID("EfClone_001.dat", "effect") == first, "Duplicate failed at capacity");
Check(gen.GetEffectID("", "") == -1, "Effectless fighter failed at capacity");
Write("EfOverflow.dat", 30000);
string? overflow = null;
try { gen.GetEffectID("EfOverflow.dat", "overflow"); }
catch (Exception ex) { overflow = ex.Message; }
Check(overflow != null && overflow.Contains("64 slots") && overflow.Contains("EfOverflow.dat"),
    "Overflow must explain the actual resource and refusing file");
Check(gen.EffectFiles.Count == 64, "Overflow mutated the table");
Check(gen.EffectFiles.All(e => e.FileName != "EfOverflow.dat"), "Failed effect leaked into table");
// A subsequent compilation starts with fresh state; removed effects free slots.
var reopened = new MexGenerator(workspace);
Check(reopened.GetEffectID("EfOverflow.dat", "overflow") >= 0, "New compilation kept stale capacity");
// More than 64 fighters is not itself an effect-table overflow.
var shared = new MexGenerator(workspace);
var sharedIds = Enumerable.Range(0, 100).Select(_ => shared.GetEffectID("EfClone.dat", "effect")).Distinct().ToArray();
Check(sharedIds.Length == 1, "A shared effect was allocated per fighter");
foreach (int count in new[] { 63, 64, 65, 72 })
{
    var external = Enumerable.Range(0, count).Select(i => MexFighterIDConverter.ToExternalID(i, count)).ToArray();
    Check(external.Distinct().Count() == count, $"Roster {count} has duplicate external IDs");
    Check(external.All(e => e >= 0 && e < count), $"Roster {count} has an out-of-range ID");
    Check(Enumerable.Range(0, count).All(i => MexFighterIDConverter.ToInternalID(external[i], count) == i),
        $"Roster {count} does not round trip");
}
Console.WriteLine(JsonSerializer.Serialize(new { success = true, slots = 64, usable = 63,
    reserved = 30, sharedReferences = 100, rosterRoundTrips = new[] { 63, 64, 65, 72 }, overflow }));
