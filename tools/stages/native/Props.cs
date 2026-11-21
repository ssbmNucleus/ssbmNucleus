// Single-mesh props baked out of a Colosseum scene (joint transform baked into the vertices),
// re-anchored at their bottom centre and placed by position / yaw / target height.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.GX;
using HSDRaw.Tools;

static partial class Program
{
    static void PlaceProps(JsonElement props, HSD_JOBJ groot, Dictionary<string, HSDRawFile> donorFiles,
        Dictionary<string, Dictionary<HSDStruct, HSDStruct>> memos)
    {
        foreach (var pr in props.EnumerateArray())
        {
            var pf = pr.GetProperty("file").GetString();
            if (!donorFiles.TryGetValue(pf, out var df)) { df = ReadArchive(pf); donorFiles[pf] = df; memos[pf] = new Dictionary<HSDStruct, HSDStruct>(); }
            int pdesc = pr.GetProperty("desc").GetInt32(), pj = pr.GetProperty("joint").GetInt32();
            var root = Scene(df).JOBJDescs[pdesc].RootJoint;
            var worlds = new Dictionary<HSD_JOBJ, Matrix4x4>();
            Worlds(root, Matrix4x4.Identity, worlds);
            var srcJ = root.TreeList[pj];
            var jw = worlds[srcJ];
            var dobjs = srcJ.Dobj.List;

            var all = new List<(HSD_DOBJ d, List<GX_Vertex> tris, GXAttribName[] attrs, HSD_POBJ src)>();
            Vector3 lo = new(float.MaxValue), hi = new(float.MinValue);
            foreach (var d in dobjs)
                foreach (var p in d.Pobj.List)
                {
                    var tris = Triangles(p.ToDisplayList());
                    for (int i = 0; i < tris.Count; i++)
                    {
                        var v = tris[i];
                        var q = Vector3.Transform(new Vector3(v.POS.X, v.POS.Y, v.POS.Z), jw);
                        var n = Vector3.Normalize(Vector3.TransformNormal(new Vector3(v.NRM.X, v.NRM.Y, v.NRM.Z), jw) + new Vector3(1e-6f));
                        v.POS = new GXVector3(q.X, q.Y, q.Z); v.NRM = new GXVector3(n.X, n.Y, n.Z);
                        tris[i] = v;
                        lo = Vector3.Min(lo, q); hi = Vector3.Max(hi, q);
                    }
                    all.Add((d, tris, p.ToGXAttributes().Select(a => a.AttributeName).Where(a => a != GXAttribName.GX_VA_NULL).ToArray(), p));
                }
            var anchor = new Vector3((lo.X + hi.X) / 2, lo.Y, (lo.Z + hi.Z) / 2);
            float height = Math.Max(0.01f, hi.Y - lo.Y);
            float s = pr.TryGetProperty("h", out var hv) ? hv.GetSingle() / height : (pr.TryGetProperty("s", out var sv) ? sv.GetSingle() : 1f);
            var t = pr.GetProperty("t").EnumerateArray().Select(e => e.GetSingle()).ToArray();
            float ry = (pr.TryGetProperty("ry", out var ryv) ? ryv.GetSingle() : 0f) * MathF.PI / 180f;

            HSD_DOBJ first = null, last = null;
            foreach (var (d, tris, attrs, src) in all)
            {
                for (int i = 0; i < tris.Count; i++)
                {
                    var v = tris[i];
                    v.POS = new GXVector3(v.POS.X - anchor.X, v.POS.Y - anchor.Y, v.POS.Z - anchor.Z);
                    tris[i] = v;
                }
                var cf = src.Flags.HasFlag(POBJ_FLAG.CULLFRONT); var cb = src.Flags.HasFlag(POBJ_FLAG.CULLBACK);
                var gen = new POBJ_Generator { CullMode = cf && cb ? GenCullMode.FrontAndBack : cf ? GenCullMode.Front : cb ? GenCullMode.Back : GenCullMode.None,
                    VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
                var pobj = gen.CreatePOBJsFromTriangleList(tris, attrs, null);
                gen.SaveChanges();
                var nd = new HSD_DOBJ { Mobj = Copy(d.Mobj, memos[pf]), Pobj = pobj };
                if (first == null) first = nd; else last.Next = nd;
                last = nd;
            }
            var flags = srcJ.Flags & (JOBJ_FLAG.OPA | JOBJ_FLAG.XLU | JOBJ_FLAG.TEXEDGE | JOBJ_FLAG.LIGHTING);
            Append(groot, new HSD_JOBJ { Flags = flags, SX = s, SY = s, SZ = s, RY = ry, TX = t[0], TY = t[1], TZ = t[2], Dobj = first });
            Console.WriteLine($"prop desc {pdesc} joint {pj}: src size ({hi.X - lo.X:F0},{height:F0},{hi.Z - lo.Z:F0}) scale {s:F2} -> ({(hi.X - lo.X) * s:F0},{height * s:F0},{(hi.Z - lo.Z) * s:F0}) at ({t[0]},{t[1]},{t[2]})");
        }
    }
}
