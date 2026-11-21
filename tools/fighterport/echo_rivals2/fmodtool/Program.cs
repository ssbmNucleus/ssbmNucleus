// fmodtool <bank> <out dir>: every sample of an FMOD bank's sound table (its FSB5) written as a file of its own
// (Vorbis rebuilt as .ogg, PCM as .wav), named by the table's own names; prints one line a sample: name, file, rate.
using Fmod5Sharp;

var bytes = File.ReadAllBytes(args[0]);
var outDir = args[1];
Directory.CreateDirectory(outDir);
int at = -1;
for (int i = 0; i + 4 <= bytes.Length; i++)
    if (bytes[i] == 'F' && bytes[i + 1] == 'S' && bytes[i + 2] == 'B' && bytes[i + 3] == '5') { at = i; break; }
if (at < 0) { Console.Error.WriteLine("no FSB5 in the bank"); return 2; }
var fsb = FsbLoader.LoadFsbFromByteArray(bytes[at..]);
int n = 0;
foreach (var s in fsb.Samples)
{
    var name = string.IsNullOrEmpty(s.Name) ? $"sample_{n:D4}" : s.Name;
    if (s.RebuildAsStandardFileFormat(out var data, out var ext) && data != null)
    {
        var file = Path.Combine(outDir, name + "." + ext);
        File.WriteAllBytes(file, data);
        Console.WriteLine($"{name}\t{Path.GetFileName(file)}\t{s.Metadata.Frequency}\t{s.Metadata.Channels}");
    }
    else
        Console.WriteLine($"{name}\t-\t{s.Metadata.Frequency}\t{s.Metadata.Channels}");
    n++;
}
return 0;
