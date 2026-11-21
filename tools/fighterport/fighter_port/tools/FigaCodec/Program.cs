// Strict native FigaTree encoder for whole locomotion clips (all nodes fresh).
// Same key/SLP policy as the accepted HelperCodec/GroundCodec: fixed 0.0001
// quantization, explicit outgoing SLP when in/out slopes differ, incoming SLP
// before a LIN key that follows a cubic interval. Anchor clones reuse the
// exact HSD_Track object of the source joint so packed buffers are shared.
using HSDRaw;
using HSDRaw.Common.Animation;
using HSDRaw.Tools;
using HSDRaw.Tools.Melee;
using System.Text.Json;

void Audit(HSD_FigaTree t,string path) {
 var rows=t.Nodes.SelectMany((n,i)=>n.Tracks.Select(x=>new{joint=i,type=x.TrackType,keys=x.ToFOBJ().GetDecodedKeys().Select(k=>new{frame=k.Frame,value=k.Value,tan=k.Tan,op=(int)k.InterpolationType})}));
 File.WriteAllText(path,JsonSerializer.Serialize(new{end=t.FrameCount,nodes=t.Nodes.Count,channels=rows}));
}
try {
if(args[0]=="audit") {
 if(File.Exists(args[2]))throw new IOException("New output required");
 var f=new HSDRawFile(args[1]); Audit(new HSD_FigaTree{_s=f.Roots[0].Data._s},args[2]);return;
}
if(args[0]!="encode")throw new ArgumentException("encode <baseline-AJ> <curves.json> <out-dir> [symbol] | audit <figatree.dat> <out.json>");
var aj=new FighterAJManager(File.ReadAllBytes(args[1]));
using var doc=JsonDocument.Parse(File.ReadAllText(args[2]));
var allowed=new[]{1,2,3,5,6,7,8,9,10};
foreach(var clip in doc.RootElement.EnumerateArray()) {
 string name=clip.GetProperty("symbol").GetString()!;
 if(args.Length>4 && name!=args[4])continue;
 string symbol=aj.GetAnimationSymbols().Single(s=>s.EndsWith("_"+name+"_figatree"));
 string path=Path.Combine(args[3],name+".uncompacted.dat");
 if(File.Exists(path))throw new IOException("New output required: "+path);
 // Keep the baseline clip's FigaTree header/type; replace nodes and frame count.
 var file=new HSDRawFile(aj.GetAnimationData(symbol));var tree=new HSD_FigaTree{_s=file.Roots[0].Data._s};
 int count=clip.GetProperty("nodes").GetInt32();
 if(count<1||count>254)throw new Exception("Invalid node count");
 var nodes=Enumerable.Range(0,count).Select(_=>new FigaTreeNode()).ToList();
 var made=new Dictionary<(int,int),HSD_Track>();
 foreach(var channel in clip.GetProperty("channels").EnumerateArray()) {
  int joint=channel.GetProperty("joint").GetInt32(),type=channel.GetProperty("type").GetInt32();
  if(joint<0||joint>=count||!allowed.Contains(type))throw new Exception($"Invalid channel {joint}/{type}");
  if(nodes[joint].Tracks.Any(t=>(int)t.TrackType==type))throw new Exception($"Track already exists {joint}/{type}");
  if(channel.TryGetProperty("clone_of",out var cloneOf)) {
   int sourceJoint=cloneOf.GetInt32();
   if(!made.TryGetValue((sourceJoint,type),out var shared))throw new Exception($"Clone source missing {sourceJoint}/{type}; order channels source-first");
   nodes[joint].Tracks.Add(shared);made[(joint,type)]=shared;continue;
  }
  var input=channel.GetProperty("keys").EnumerateArray().ToArray();var keys=new List<FOBJKey>();
  for(int i=0;i<input.Length;i++) {
   var x=input[i];float f=x.GetProperty("time").GetSingle(),v=x.GetProperty("value").GetSingle();
   float ins=x.GetProperty("in_slope").GetSingle(),outs=x.GetProperty("out_slope").GetSingle();bool lin=x.GetProperty("outgoing").GetString()=="linear";
   if(lin&&i>0&&input[i-1].GetProperty("outgoing").GetString()=="fixed")keys.Add(new FOBJKey{Frame=f-1,Tan=ins,InterpolationType=GXInterpolationType.HSD_A_OP_SLP});
   keys.Add(new FOBJKey{Frame=f,Value=v,Tan=ins,InterpolationType=lin?GXInterpolationType.HSD_A_OP_LIN:GXInterpolationType.HSD_A_OP_SPL});
   if(!lin&&i+1<input.Length&&Math.Abs(ins-outs)>0.000001f)keys.Add(new FOBJKey{Frame=input[i+1].GetProperty("time").GetSingle()-1,Tan=outs,InterpolationType=GXInterpolationType.HSD_A_OP_SLP});
  }
  float quantization=channel.TryGetProperty("quantization",out var q)?q.GetSingle():0.0001f;
  if(!float.IsFinite(quantization)||quantization<=0||quantization>0.01f)throw new Exception("Explicit quantization must be in (0,0.01]");
  if(input.Any(k=>k.GetProperty("time").GetSingle()!=MathF.Truncate(k.GetProperty("time").GetSingle())))throw new Exception("Packed FOBJ delta times are integers; fractional keys are not supported");
  var track=new HSD_Track(FOBJFrameEncoder.EncodeFrames(keys,(byte)type,quantization));
  nodes[joint].Tracks.Add(track);made[(joint,type)]=track;
 }
 tree.FrameCount=clip.GetProperty("end").GetSingle();tree.Nodes=nodes;file.Roots[0].Data=tree;
 using var ms=new MemoryStream();file.Save(ms);File.WriteAllBytes(path,ms.ToArray());
 Audit(tree,Path.Combine(args[3],name+".raw.json"));Console.WriteLine(name+" "+new FileInfo(path).Length);
}
} catch(Exception ex) { Console.Error.WriteLine(ex); Environment.ExitCode=1; }
