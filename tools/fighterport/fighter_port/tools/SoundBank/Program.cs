using System.Collections.ObjectModel;
using System.Text.Json;
using mexLib;
using mexLib.Types;
using mexLib.Utilties;

// Reads a donor workspace; writes a separate bank package. Never saves the donor.
var json = new JsonSerializerOptions { WriteIndented = true };
if (args.Length < 3) throw new ArgumentException("inspect <project> <bank> | pack <project> <bank> <manifest> <new-output-directory>");
if (!MexWorkspace.TryOpenWorkspace(args[1], out var workspace, out var error, out _) || workspace == null)
    throw new Exception(error);
if (args[0] == "replace-bank" && args.Length == 4) {
    int index=int.Parse(args[2]);var previous=workspace.Project.SoundGroups[index];
    using var stream=File.OpenRead(args[3]);
    using(var zip=new System.IO.Compression.ZipArchive(stream,System.IO.Compression.ZipArchiveMode.Read,true)) {
        using var meta=JsonDocument.Parse(zip.GetEntry("group.json")!.Open());
        if(meta.RootElement.GetProperty("fileName").GetString()!=previous.FileName)
            throw new Exception("Replacement bank filename differs from explicit target");
    }
    stream.Position=0;
    var failure=MexSoundGroup.FromPackage(workspace,stream,out var imported);
    if(failure!=null || imported==null)throw new Exception("Bank replacement failed: "+failure);
    workspace.Project.SoundGroups[index]=imported;workspace.Save(null);
    Console.WriteLine("Replaced explicit bank; caller must bind matching fighter cue IDs");return;
}
if (args[0] == "replace-sample" && args.Length == 5) {
    var bank=workspace.Project.SoundGroups[int.Parse(args[2])];
    var sample=bank.Sounds[int.Parse(args[3])];
    sample.DSP=AudioDecoder.DecodeFile(args[4]);
    sample.Name=Path.GetFileNameWithoutExtension(args[4]);
    workspace.Save(null);
    Console.WriteLine("Replaced one sample; SEM script indices retained");return;
}
if (args[0] == "presentation" && args.Length == 8) {
    var fighter=workspace.Project.Fighters[int.Parse(args[2])];
    if(fighter.Costumes.Count != 4)throw new Exception("Expected four costumes");
    for(int i=0;i<4;i++) {
        using var portrait=File.OpenRead(args[3+i]);
        fighter.Costumes[i].CSPAsset.SetFromImageFile(workspace,portrait);
    }
    using var icon=File.OpenRead(args[7]);
    fighter.Assets.CSSIconAsset.SetFromImageFile(workspace,icon);
    workspace.Save(null);Console.WriteLine("Imported four CSPs and CSS icon");return;
}
if (args[0] == "banners" && args.Length == 5) {
    var fighter=workspace.Project.Fighters[int.Parse(args[2])];
    using var big=File.OpenRead(args[3]);using var small=File.OpenRead(args[4]);
    fighter.Assets.ResultBannerBigAsset.SetFromImageFile(workspace,big);
    fighter.Assets.ResultBannerSmallAsset.SetFromImageFile(workspace,small);
    workspace.Save(null);Console.WriteLine("Imported both results banners");return;
}
if (args[0] == "install" && args.Length == 4) {
    using var stream=File.OpenRead(args[3]);
    // Only install a new, distinct bank; never replace another fighter's group.
    using(var zip=new System.IO.Compression.ZipArchive(stream,System.IO.Compression.ZipArchiveMode.Read,true)) {
        using var meta=JsonDocument.Parse(zip.GetEntry("group.json")!.Open());
        var filename=meta.RootElement.GetProperty("fileName").GetString();
        if(workspace.Project.SoundGroups.Any(g => string.Equals(g.FileName,filename,StringComparison.OrdinalIgnoreCase)))
            throw new IOException("Bank already installed; inspect before resuming");
    }
    stream.Position=0;
    var failure=MexSoundGroup.FromPackage(workspace,stream,out var imported);
    if(failure != null || imported == null) throw new Exception("Sound package import failed: "+failure);
    var index=workspace.Project.AddSoundGroup(imported);
    if(index>=64) throw new Exception("Sound load bitfield capacity exceeded");
    var fighter=workspace.Project.Fighters[int.Parse(args[2])];
    fighter.SoundBank=index;
    fighter.SSMBitfield1=index>=32?1u<<(index-32):0;
    fighter.SSMBitfield2=index<32?1u<<index:0;
    workspace.Save(null);
    Console.WriteLine(JsonSerializer.Serialize(new { bank=index,imported.FileName,fighter.SSMBitfield1,fighter.SSMBitfield2 },json));
    return;
}
var donor = workspace.Project.SoundGroups[int.Parse(args[2])];
if (args[0] == "inspect") {
    Console.WriteLine(JsonSerializer.Serialize(new {
        donor.Name, donor.FileName,
        sounds = donor.Sounds.Select((s,i) => new { index=i, s.Name }),
        scripts = donor.Scripts!.Select((s,i) => new { index=i, s.Name,
            commands=s.Script.Select(c => new { code=c.SemCode.ToString(), c.Value }) })
    },json));
    return;
}
if (args[0] != "pack" || args.Length != 5) throw new ArgumentException("Invalid arguments");
var output = Path.GetFullPath(args[4]);
if (Directory.Exists(output)) throw new IOException("Output already exists; inspect before resuming");
using var manifest = JsonDocument.Parse(File.ReadAllText(args[3]));
var m = manifest.RootElement;
var replacements = m.GetProperty("replacements");
foreach(var sound in donor.Sounds)
    if (!replacements.TryGetProperty(sound.Name,out _)) throw new Exception("Unmapped donor sound: " + sound.Name);
var group = new MexSoundGroup { Name=m.GetProperty("name").GetString()!,
    FileName=m.GetProperty("fileName").GetString()!, Scripts=new ObservableCollection<SemScript>() };
if (Path.GetFileName(group.FileName)!=group.FileName) throw new ArgumentException("Bank name must be a basename");
group.CopyFrom(donor);
var cache = new Dictionary<string,MeleeMedia.Audio.DSP>();
MeleeMedia.Audio.DSP Decode(string path) {
    if (!cache.TryGetValue(path,out var dsp)) cache[path]=dsp=AudioDecoder.DecodeFile(path);
    return dsp;
}
foreach(var sound in group.Sounds) {
    var path = replacements.GetProperty(sound.Name).GetString()!;
    sound.DSP=Decode(path);sound.Name=Path.GetFileNameWithoutExtension(path);
}
var ids=new Dictionary<string,int>();
foreach(var entry in m.GetProperty("append").EnumerateArray()) {
    var path=entry.GetString()!;var name=Path.GetFileNameWithoutExtension(path);
    var index=group.Sounds.ToList().FindIndex(s => s.Name==name);
    if(index<0) {
        index=group.Sounds.Count;
        group.Sounds.Add(new MexSound { Name=name,DSP=Decode(path) });
    }
    var script=new SemScript { Name=name };
    script.Script.Add(new SemCommand(SemCode.Sound,index));
    script.Script.Add(new SemCommand(SemCode.SetVolume,210));
    script.Script.Add(new SemCommand(SemCode.SetPriority,15));
    script.Script.Add(new SemCommand(SemCode.End,0));
    ids.Add(name,group.Scripts!.Count);group.Scripts.Add(script);
}
Directory.CreateDirectory(output);
using(var stream=File.Create(Path.Combine(output,"sound.zip"))) MexSoundGroup.ToPackage(group,stream);
File.WriteAllText(Path.Combine(output,"script-ids.json"),JsonSerializer.Serialize(ids,json));
File.WriteAllText(Path.Combine(output,"build.json"),JsonSerializer.Serialize(new { group.Name,group.FileName,
    sounds=group.Sounds.Count,scripts=group.Scripts!.Count,donorSounds=donor.Sounds.Count,
    donorScripts=donor.Scripts!.Count,sourceManifest=Path.GetFullPath(args[3]) },json));
Console.WriteLine($"Packed {group.Sounds.Count} sounds / {group.Scripts.Count} scripts to {output}");
