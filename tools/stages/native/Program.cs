// Prototype: graft Colosseum scene_data models into a Melee stage file.
//   probe <rdat> <desc> [joint...]     print materials/textures/attributes
//   build <spec.json>                  vanilla stage -> Agate-dressed stage
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.GX;
using HSDRaw.Melee.Gr;
using HSDRaw.Tools;

static partial class Program
{
    // Preserves sharing (same as StageScenery.Clone), so a shared atlas is written once.
    static HSDStruct Clone(HSDStruct s, Dictionary<HSDStruct, HSDStruct> memo)
    {
        if (s == null) return null;
        if (memo.TryGetValue(s, out var prev)) return prev;
        var c = new HSDStruct((byte[])s.GetData().Clone())
        {
            Align = s.Align, CanBeBuffer = s.CanBeBuffer,
            CanBeDuplicate = s.CanBeDuplicate, IsBufferAligned = s.IsBufferAligned
        };
        memo[s] = c;
        foreach (var r in s.References) c.References[r.Key] = Clone(r.Value, memo);
        return c;
    }

    static T Copy<T>(T a, Dictionary<HSDStruct, HSDStruct> memo) where T : HSDAccessor, new()
        => a == null ? null : new T { _s = Clone(a._s, memo) };

    static HSD_SOBJ Scene(HSDRawFile f)
    {
        var d = f.Roots.First(r => r.Name == "scene_data").Data;
        return d as HSD_SOBJ ?? new HSD_SOBJ { _s = d._s };
    }

    static void Append(HSD_JOBJ parent, HSD_JOBJ child)
    {
        if (parent.Child == null) { parent.Child = child; return; }
        var l = parent.Child;
        while (l.Next != null) l = l.Next;
        l.Next = child;
    }

    // ---- world placement, regions, triangle cuts ----
    static System.Numerics.Matrix4x4 Local(HSD_JOBJ j) =>
        System.Numerics.Matrix4x4.CreateScale(j.SX, j.SY, j.SZ)
        * System.Numerics.Matrix4x4.CreateRotationX(j.RX)
        * System.Numerics.Matrix4x4.CreateRotationY(j.RY)
        * System.Numerics.Matrix4x4.CreateRotationZ(j.RZ)
        * System.Numerics.Matrix4x4.CreateTranslation(j.TX, j.TY, j.TZ);

    static void Worlds(HSD_JOBJ j, System.Numerics.Matrix4x4 parent, Dictionary<HSD_JOBJ, System.Numerics.Matrix4x4> outp)
    {
        for (var c = j; c != null; c = c.Next)
        {
            var w = Local(c) * parent;
            outp[c] = w;
            if (c.Child != null) Worlds(c.Child, w, outp);
        }
    }

    record Box(float x0, float x1, float y0, float y1, float z0, float z1)
    {
        public bool Has(System.Numerics.Vector3 p) => p.X >= x0 && p.X <= x1 && p.Y >= y0 && p.Y <= y1 && p.Z >= z0 && p.Z <= z1;
        public static Box From(JsonElement e) => new(e[0].GetSingle(), e[1].GetSingle(), e[2].GetSingle(), e[3].GetSingle(), e[4].GetSingle(), e[5].GetSingle());
    }

    static bool Rigid(HSD_POBJ p) => p.EnvelopeWeights == null && !p.Flags.HasFlag(POBJ_FLAG.ENVELOPE) && !p.Flags.HasFlag(POBJ_FLAG.SHAPEANIM);

    // triangles of a decoded display list (vertex order kept)
    static List<GX_Vertex> Triangles(GX_DisplayList dl)
    {
        var tris = new List<GX_Vertex>();
        int off = 0;
        foreach (var g in dl.Primitives)
        {
            var v = dl.Vertices.GetRange(off, g.Count);
            off += g.Count;
            switch (g.PrimitiveType)
            {
                case GXPrimitiveType.Triangles:
                    for (int i = 0; i + 2 < v.Count; i += 3) { tris.Add(v[i]); tris.Add(v[i + 1]); tris.Add(v[i + 2]); }
                    break;
                case GXPrimitiveType.TriangleStrip:
                    for (int i = 0; i + 2 < v.Count; i++)
                        if (i % 2 == 0) { tris.Add(v[i]); tris.Add(v[i + 1]); tris.Add(v[i + 2]); }
                        else { tris.Add(v[i + 1]); tris.Add(v[i]); tris.Add(v[i + 2]); }
                    break;
                case GXPrimitiveType.TriangleFan:
                    for (int i = 1; i + 1 < v.Count; i++) { tris.Add(v[0]); tris.Add(v[i]); tris.Add(v[i + 1]); }
                    break;
                case GXPrimitiveType.Quads:
                    for (int i = 0; i + 3 < v.Count; i += 4) { tris.Add(v[i]); tris.Add(v[i + 1]); tris.Add(v[i + 2]); tris.Add(v[i + 2]); tris.Add(v[i + 3]); tris.Add(v[i]); }
                    break;
            }
        }
        return tris;
    }

    static (System.Numerics.Vector3 lo, System.Numerics.Vector3 hi) Bounds(HSD_DOBJ d, System.Numerics.Matrix4x4 w)
    {
        var lo = new System.Numerics.Vector3(float.MaxValue); var hi = new System.Numerics.Vector3(float.MinValue);
        foreach (var p in d.Pobj?.List ?? new List<HSD_POBJ>())
            foreach (var v in p.ToDisplayList().Vertices)
            {
                var q = System.Numerics.Vector3.Transform(new System.Numerics.Vector3(v.POS.X, v.POS.Y, v.POS.Z), w);
                lo = System.Numerics.Vector3.Min(lo, q); hi = System.Numerics.Vector3.Max(hi, q);
            }
        return (lo, hi);
    }

    static GX_Vertex Lerp(GX_Vertex a, GX_Vertex b, float t)
    {
        GXVector3 L3(GXVector3 p, GXVector3 q) => new GXVector3(p.X + (q.X - p.X) * t, p.Y + (q.Y - p.Y) * t, p.Z + (q.Z - p.Z) * t);
        GXVector2 L2(GXVector2 p, GXVector2 q) => new GXVector2(p.X + (q.X - p.X) * t, p.Y + (q.Y - p.Y) * t);
        GXColor4 LC(GXColor4 p, GXColor4 q) => new GXColor4(p.R + (q.R - p.R) * t, p.G + (q.G - p.G) * t, p.B + (q.B - p.B) * t, p.A + (q.A - p.A) * t);
        var v = a;
        v.POS = L3(a.POS, b.POS); v.NRM = L3(a.NRM, b.NRM);
        v.CLR0 = LC(a.CLR0, b.CLR0); v.CLR1 = LC(a.CLR1, b.CLR1);
        v.TEX0 = L2(a.TEX0, b.TEX0); v.TEX1 = L2(a.TEX1, b.TEX1); v.TEX2 = L2(a.TEX2, b.TEX2);
        return v;
    }

    // Split a convex polygon by f(p) >= 0 (inside) / < 0 (outside); f is evaluated on world positions.
    static (List<(GX_Vertex v, System.Numerics.Vector3 w)> inside, List<(GX_Vertex v, System.Numerics.Vector3 w)> outside)
        Split(List<(GX_Vertex v, System.Numerics.Vector3 w)> poly, Func<System.Numerics.Vector3, float> f)
    {
        var ins = new List<(GX_Vertex, System.Numerics.Vector3)>(); var outs = new List<(GX_Vertex, System.Numerics.Vector3)>();
        for (int i = 0; i < poly.Count; i++)
        {
            var a = poly[i]; var b = poly[(i + 1) % poly.Count];
            float fa = f(a.w), fb = f(b.w);
            if (fa >= 0) ins.Add(a); else outs.Add(a);
            if ((fa >= 0) != (fb >= 0))
            {
                float t = fa / (fa - fb);
                var m = (Lerp(a.v, b.v, t), a.w + (b.w - a.w) * t);
                ins.Add(m); outs.Add(m);
            }
        }
        return (ins.Count >= 3 ? ins : new(), outs.Count >= 3 ? outs : new());
    }

    // Exact subtraction of the boxes from each triangle: straight cut edges, attributes interpolated, winding kept.
    static bool flipCull = Environment.GetEnvironmentVariable("COLOGRAFT_FLIP_CULL") == "1";
    static float darkCut = 0f;
    static Box darkBox = null;
    static HSD_POBJ CutPobjs(HSD_POBJ first, System.Numerics.Matrix4x4 w, List<Box> regions, ref int cutTris)
    {
        HSD_POBJ head = null, tail = null;
        foreach (var p in first.List)
        {
            HSD_POBJ result = p;
            if (Rigid(p))
            {
                var tris = Triangles(p.ToDisplayList());
                var keep = new List<GX_Vertex>();
                bool changed = false;
                for (int i = 0; i + 2 < tris.Count; i += 3)
                {
                    var pieces = new List<List<(GX_Vertex v, System.Numerics.Vector3 w)>> {
                        Enumerable.Range(0, 3).Select(k => (tris[i + k], System.Numerics.Vector3.Transform(new System.Numerics.Vector3(tris[i + k].POS.X, tris[i + k].POS.Y, tris[i + k].POS.Z), w))).ToList() };
                    bool touched = false;
                    foreach (var r in regions)
                    {
                        var faces = new Func<System.Numerics.Vector3, float>[] { q => q.X - r.x0, q => r.x1 - q.X, q => q.Y - r.y0, q => r.y1 - q.Y, q => q.Z - r.z0, q => r.z1 - q.Z };
                        var next = new List<List<(GX_Vertex v, System.Numerics.Vector3 w)>>();
                        foreach (var poly in pieces)
                        {
                            var rest = poly;
                            foreach (var f in faces)
                            {
                                var (ins, outs) = Split(rest, f);
                                if (outs.Count > 0) next.Add(outs);
                                rest = ins;
                                if (rest.Count == 0) break;
                            }
                            if (rest.Count > 0) touched = true;   // part of it was inside this box and is dropped
                        }
                        pieces = next;
                    }
                    var cen = (System.Numerics.Vector3.Transform(new System.Numerics.Vector3(tris[i].POS.X, tris[i].POS.Y, tris[i].POS.Z), w)
                             + System.Numerics.Vector3.Transform(new System.Numerics.Vector3(tris[i + 1].POS.X, tris[i + 1].POS.Y, tris[i + 1].POS.Z), w)
                             + System.Numerics.Vector3.Transform(new System.Numerics.Vector3(tris[i + 2].POS.X, tris[i + 2].POS.Y, tris[i + 2].POS.Z), w)) / 3f;
                    if (darkCut > 0 && pieces.Count > 0 && (darkBox == null || darkBox.Has(cen)))
                    {
                        float lum = (tris[i].CLR0.R + tris[i].CLR0.G + tris[i].CLR0.B + tris[i + 1].CLR0.R + tris[i + 1].CLR0.G + tris[i + 1].CLR0.B
                                   + tris[i + 2].CLR0.R + tris[i + 2].CLR0.G + tris[i + 2].CLR0.B) / 9f;
                        if (lum < darkCut) { pieces.Clear(); touched = true; }   // cave interiors: baked near-black
                    }
                    if (touched) { cutTris++; changed = true; }
                    foreach (var poly in pieces)
                        for (int k = 1; k + 1 < poly.Count; k++) { keep.Add(poly[0].v); keep.Add(poly[k].v); keep.Add(poly[k + 1].v); }
                }
                if (!changed) result = p;
                else if (keep.Count == 0) result = null;
                else
                {
                    var attrs = p.ToGXAttributes().Select(a => a.AttributeName).Where(a => a != GXAttribName.GX_VA_NULL).ToArray();
                    var cf = p.Flags.HasFlag(POBJ_FLAG.CULLFRONT); var cb = p.Flags.HasFlag(POBJ_FLAG.CULLBACK);
                    var cull = cf && cb ? GenCullMode.FrontAndBack : cf ? GenCullMode.Front : cb ? GenCullMode.Back : GenCullMode.None;
                    if (flipCull) cull = cull == GenCullMode.Front ? GenCullMode.Back : cull == GenCullMode.Back ? GenCullMode.Front : cull;
                    var gen = new POBJ_Generator { CullMode = cull, VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
                    result = gen.CreatePOBJsFromTriangleList(keep, attrs, null);
                    gen.SaveChanges();
                }
            }
            if (result == null) continue;
            var last = result; while (last.Next != null) last = last.Next;
            if (head == null) head = result; else tail.Next = result;
            tail = last;
        }
        if (tail != null) tail.Next = null;
        return head;
    }

    // One-sided triangles no camera can ever face are dropped ("unseen": the box every eye stays inside, file units, and the game only looks toward -z,
    // so an eye sees nothing south of itself). A triangle stays if any eye in the box north-to-south of it stands on its showing side.
    // HSDRaw's CULLFRONT flag is the game's CULLBACK: such a face shows from where its vertices run clockwise, the -n side of (b-a)x(c-a).
    // NOT a way to shrink a file: a mesh that loses some triangles is rebuilt with vertex buffers of its own and comes out heavier than the cut saved
    // (Phenac City 2026-11-11: 16% of its triangles gone, the file 185 KB bigger). Unused there; it would thin what an outline pass has to line.
    static HSD_POBJ UnseenPobjs(HSD_POBJ first, System.Numerics.Matrix4x4 w, Box eye, float sign, ref int gone, ref int all)
    {
        HSD_POBJ head = null, tail = null;
        foreach (var p in first.List)
        {
            HSD_POBJ result = p;
            bool cf = p.Flags.HasFlag(POBJ_FLAG.CULLFRONT), cb = p.Flags.HasFlag(POBJ_FLAG.CULLBACK);
            if (Rigid(p) && (cf ^ cb))
            {
                float side = (cf ? -1f : 1f) * sign;
                var tris = Triangles(p.ToDisplayList());
                var keep = new List<GX_Vertex>();
                for (int i = 0; i + 2 < tris.Count; i += 3)
                {
                    var a = System.Numerics.Vector3.Transform(new System.Numerics.Vector3(tris[i].POS.X, tris[i].POS.Y, tris[i].POS.Z), w);
                    var b = System.Numerics.Vector3.Transform(new System.Numerics.Vector3(tris[i + 1].POS.X, tris[i + 1].POS.Y, tris[i + 1].POS.Z), w);
                    var c = System.Numerics.Vector3.Transform(new System.Numerics.Vector3(tris[i + 2].POS.X, tris[i + 2].POS.Y, tris[i + 2].POS.Z), w);
                    var n = System.Numerics.Vector3.Cross(b - a, c - a) * side;
                    float z0 = Math.Max(eye.z0, Math.Min(a.Z, Math.Min(b.Z, c.Z)));
                    bool seen = false;
                    if (z0 <= eye.z1)
                        foreach (var x in new[] { eye.x0, eye.x1 }) foreach (var y in new[] { eye.y0, eye.y1 }) foreach (var z in new[] { z0, eye.z1 })
                            if (System.Numerics.Vector3.Dot(new System.Numerics.Vector3(x, y, z) - a, n) > 0) seen = true;
                    all++;
                    if (seen) { keep.Add(tris[i]); keep.Add(tris[i + 1]); keep.Add(tris[i + 2]); } else gone++;
                }
                if (keep.Count == 0) result = null;
                else if (keep.Count < tris.Count)
                {
                    var attrs = p.ToGXAttributes().Select(q => q.AttributeName).Where(q => q != GXAttribName.GX_VA_NULL).ToArray();
                    var gen = new POBJ_Generator { CullMode = cf ? GenCullMode.Front : GenCullMode.Back, VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
                    result = gen.CreatePOBJsFromTriangleList(keep, attrs, null);
                    gen.SaveChanges();
                }
            }
            else if (Rigid(p)) all += Triangles(p.ToDisplayList()).Count / 3;
            if (result == null) continue;
            var last = result; while (last.Next != null) last = last.Next;
            if (head == null) head = result; else tail.Next = result;
            tail = last;
        }
        if (tail != null) tail.Next = null;
        return head;
    }

    static readonly HashSet<HSDStruct> bakedMats = new HashSet<HSDStruct>();

    static List<HSD_AnimJoint> DfsAJ(HSD_AnimJoint root)
    {
        var list = new List<HSD_AnimJoint>();
        void Visit(HSD_AnimJoint node)
        {
            for (var current = node; current != null; current = current.Next)
            { list.Add(current); if (current.Child != null) Visit(current.Child); }
        }
        Visit(root);
        return list;
    }

    static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "probe") return Probe(args);
        if (args.Length > 1 && args[0] == "inspect") return Inspect(args[1]);
        if (args.Length > 1 && args[0] == "build") return Build(args[1]);
        Console.WriteLine("usage: probe <rdat> <desc> [joint...] | build <spec.json>");
        return 2;
    }

    static int Probe(string[] args)
    {
        var f = ReadArchive(args[1]);
        var root = Scene(f).JOBJDescs[int.Parse(args[2])].RootJoint;
        var want = args.Skip(3).Select(int.Parse).ToHashSet();
        var list = root.TreeList;
        var modes = new Dictionary<string, int>();
        Console.WriteLine($"root flags={root.Flags} joints={list.Count}");
        for (int j = 0; j < list.Count; j++)
        {
            var jo = list[j];
            if (jo.Dobj == null) continue;
            int d = 0;
            foreach (var dobj in jo.Dobj.List)
            {
                var m = dobj.Mobj;
                var key = m?.RenderFlags.ToString() ?? "none";
                modes[key] = modes.TryGetValue(key, out var n) ? n + 1 : 1;
                if (want.Contains(j))
                {
                    Console.WriteLine($"joint {j} dobj {d} jflags={jo.Flags} T=({jo.TX:F1},{jo.TY:F1},{jo.TZ:F1}) S=({jo.SX:F2},{jo.SY:F2},{jo.SZ:F2})");
                    Console.WriteLine($"  mobj {m?.RenderFlags} amb={m?.Material?.AmbientColor} dif={m?.Material?.DiffuseColor} alpha={m?.Material?.Alpha} pe={(m?.PEDesc != null)}");
                    if (m?.Textures != null)
                        foreach (var t in m.Textures.List)
                            Console.WriteLine($"  tobj {t.ImageData?.Width}x{t.ImageData?.Height} {t.ImageData?.Format} flags={t.Flags} S=({t.SX},{t.SY}) T=({t.TX},{t.TY}) wrap={t.WrapS}/{t.WrapT} rep={t.RepeatS}/{t.RepeatT} blend={t.Blending}");
                    if (dobj.Pobj != null)
                        foreach (var p in dobj.Pobj.List)
                        {
                            var dl = p.ToDisplayList();
                            var attrs = string.Join(",", p.ToGXAttributes().Select(a => $"{a.AttributeName}:{a.CompType}"));
                            double r = 0, g = 0, b = 0, al = 0, amin = 9; int c = 0;
                            foreach (var v in dl.Vertices) { r += v.CLR0.R; g += v.CLR0.G; b += v.CLR0.B; al += v.CLR0.A; amin = Math.Min(amin, v.CLR0.A); c++; }
                            var cattr = p.ToGXAttributes().FirstOrDefault(a => a.AttributeName == GXAttribName.GX_VA_CLR0);
                            Console.WriteLine($"  pobj flags={p.Flags} verts={dl.Vertices.Count} attrs={attrs} clr0type={(cattr != null ? ((int)cattr.CompType).ToString() + "/" + cattr.AttributeType : "-")} avgclr=({r / Math.Max(1, c):F2},{g / Math.Max(1, c):F2},{b / Math.Max(1, c):F2}) alpha avg={al / Math.Max(1, c):F2} min={amin:F2}");
                        }
                }
                d++;
            }
        }
        foreach (var kv in modes.OrderByDescending(k => k.Value)) Console.WriteLine($"mode x{kv.Value}: {kv.Key}");
        return 0;
    }

    static int Build(string specPath)
    {
        var spec = JsonDocument.Parse(File.ReadAllText(specPath)).RootElement;
        var file = ReadArchive(spec.GetProperty("target").GetString());
        var head = file.Roots.Select(r => r.Data).OfType<SBM_Map_Head>().First();
        var groups = CheckedGroups(head);

        // Dream Land's code never assumes these meshes exist (decomp: grMaterial walks are null-safe).
        foreach (var g in spec.GetProperty("clear_groups").EnumerateArray().Select(e => e.GetInt32()))
            foreach (var jo in groups[g].RootNode.TreeList) jo.Dobj = null;

        int recv = spec.GetProperty("receive_group").GetInt32();
        var groot = groups[recv].RootNode;
        recvGroup = recv;
        recvVanilla = groot.TreeList.Count;   // joints the stage code may index; everything grafted is appended after
        const JOBJ_FLAG RootAll = JOBJ_FLAG.ROOT_OPA | JOBJ_FLAG.ROOT_XLU | JOBJ_FLAG.ROOT_TEXEDGE;
        groot.Flags |= RootAll;

        // one wrapper per placement (e.g. 0 = village, 1 = the tree group kept at stage level)
        var wrappers = new List<(HSD_JOBJ j, System.Numerics.Matrix4x4 m)>();
        foreach (var w in spec.TryGetProperty("wrappers", out var wrs) ? wrs.EnumerateArray().ToArray() : new JsonElement[0])
        {
            var t = w.GetProperty("t").EnumerateArray().Select(e => e.GetSingle()).ToArray();
            float s = w.GetProperty("s").GetSingle();
            var wj = new HSD_JOBJ { Flags = RootAll, SX = s, SY = s, SZ = s, TX = t[0], TY = t[1], TZ = t[2] };
            Append(groot, wj);
            wrappers.Add((wj, System.Numerics.Matrix4x4.CreateScale(s) * System.Numerics.Matrix4x4.CreateTranslation(t[0], t[1], t[2])));
        }

        float keepIfLarger = spec.TryGetProperty("keep_if_larger", out var kil) ? kil.GetSingle() : float.MaxValue;
        float cutMaxDiag = spec.TryGetProperty("cut_max_diag", out var cmd) ? cmd.GetSingle() : float.MaxValue;
        // meshes smaller than this are never sliced: kept whole, or dropped whole if their centre is in a cut region
        float cutMinDiag = spec.TryGetProperty("cut_min_diag", out var cmn) ? cmn.GetSingle() : 0f;
        float hideMaxDiag = spec.TryGetProperty("hide_max_diag", out var hmd) ? hmd.GetSingle() : 0f;
        var hideRegions = spec.TryGetProperty("hide_regions", out var hr) ? hr.EnumerateArray().Select(Box.From).ToList() : new List<Box>();
        var cutRegions = spec.TryGetProperty("cut_regions", out var cr) ? cr.EnumerateArray().Select(Box.From).ToList() : new List<Box>();
        Box report = spec.TryGetProperty("report", out var rp) ? Box.From(rp) : null;
        Box unseen = spec.TryGetProperty("unseen", out var use) ? Box.From(use) : null;
        float unseenSign = spec.TryGetProperty("unseen_sign", out var uss) ? uss.GetSingle() : 1f;
        int unseenGone = 0, unseenAll = 0;
        // Colosseum's untextured translucent shadow cards use a blend Melee doesn't reproduce: they draw as dark boxes
        bool hideShadowCards = spec.TryGetProperty("hide_untextured_xlu", out var hux) && hux.GetBoolean();
        darkCut = spec.TryGetProperty("dark_cut", out var dc) ? dc.GetSingle() : 0f;
        darkBox = spec.TryGetProperty("dark_box", out var db) ? Box.From(db) : null;

        var memos = new Dictionary<string, Dictionary<HSDStruct, HSDStruct>>();
        var donorFiles = new Dictionary<string, HSDRawFile>();
        var animSubs = new Dictionary<HSD_JOBJ, HSD_AnimJoint>();
        var matSubs = new Dictionary<HSD_JOBJ, HSD_MatAnimJoint>();
        foreach (var d in spec.GetProperty("donors").EnumerateArray())
        {
            var path = d.GetProperty("file").GetString();
            if (!donorFiles.TryGetValue(path, out var df))
            {
                df = ReadArchive(path);
                donorFiles[path] = df;
                memos[path] = new Dictionary<HSDStruct, HSDStruct>();
            }
            int desc = d.GetProperty("desc").GetInt32();
            int wi = d.TryGetProperty("wrapper", out var wv) ? wv.GetInt32() : 0;
            var src = Scene(df).JOBJDescs[desc].RootJoint;
            var memo = memos[path];
            if (d.TryGetProperty("fresh", out var fr) && fr.GetBoolean())
            {
                // second copy of a desc: new joints/meshes/polys, but textures and materials stay shared
                var own = new HashSet<HSDStruct>();
                foreach (var sj in src.TreeList)
                {
                    own.Add(sj._s);
                    if (sj.Dobj != null) foreach (var sd in sj.Dobj.List)
                    {
                        own.Add(sd._s);
                        if (sd.Pobj != null) foreach (var sp in sd.Pobj.List) own.Add(sp._s);
                    }
                }
                memo = memo.Where(kv => !own.Contains(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
            }
            var clone = Copy(src, memo);
            HSD_AnimJoint animClone = null; HSD_MatAnimJoint matClone = null;
            if (d.TryGetProperty("anim", out var an) && an.GetBoolean())
            {
                var jd = Scene(df).JOBJDescs[desc];
                int ai = d.TryGetProperty("anim_index", out var aiv) ? aiv.GetInt32() : 0;
                bool wantJ = !d.TryGetProperty("joint_anim", out var wj) || wj.GetBoolean();   // doors etc. live here
                bool wantM = !d.TryGetProperty("mat_anim", out var wm) || wm.GetBoolean();     // water scroll, blinks, fades
                if (wantJ && jd.JointAnimations != null && jd.JointAnimations.Length > ai) animClone = Copy(jd.JointAnimations[ai], memo);
                if (wantM && jd.MaterialAnimations != null && jd.MaterialAnimations.Length > ai) matClone = Copy(jd.MaterialAnimations[ai], memo);
                if (d.TryGetProperty("loop", out var lp) && lp.GetBoolean()) { if (animClone != null) SetLoop(animClone); if (matClone != null) SetLoop(matClone); }
                if (animClone != null && d.TryGetProperty("pin", out var pn) && pn.GetBoolean()) StripTranslation(animClone);
            }
            if (memo != memos[path]) foreach (var kv in memo) if (!memos[path].ContainsKey(kv.Key)) memos[path][kv.Key] = kv.Value;
            // Colosseum INSTANCE joints (shared subtrees) become real subtrees before anything walks the tree (Colo.cs, from colograft_ps)
            if (d.TryGetProperty("flatten", out var flt) && flt.GetBoolean()) Console.WriteLine($"  desc {desc}: flattened {FlattenInstances(clone, matClone, animClone)} instance joints");
            if (d.TryGetProperty("bake_envelopes", out var bev) && bev.GetBoolean()) Console.WriteLine($"  desc {desc}: baked {BakeEnvelopes(clone, matClone, animClone)} skinned joints rigid");
            // Colosseum particle anchors: the JOBJ union (0x10) holds particle data, not a DObj. Clearing only the flag makes
            // Melee load that data as a DObj ("pobj: unexected type" panic), so drop the pointer with the flag.
            if (d.TryGetProperty("strip_ptcl", out var spt) && spt.GetBoolean())
                foreach (var jj in clone.TreeList)
                    if (jj.Flags.HasFlag(JOBJ_FLAG.PTCL)) { jj._s.SetReference(0x10, null); jj._s.SetInt32(0x10, 0); jj.Flags &= ~JOBJ_FLAG.PTCL; }
            var tl = clone.TreeList;
            if (!DfsJ(clone).SequenceEqual(tl)) Console.WriteLine($"  WARN desc {desc}: TreeList order differs from pre-order walk");
            List<HSD_MatAnimJoint> mlist = matClone != null ? DfsM(matClone) : null;
            if (mlist != null && mlist.Count != tl.Count) { Console.WriteLine($"  WARN desc {desc}: matanim tree {mlist.Count} vs joints {tl.Count}; material anims dropped"); matClone = null; mlist = null; }
            bool stripCubes = d.TryGetProperty("strip_cubes", out var sc) && sc.GetBoolean();
            if (d.TryGetProperty("drop_tex1", out var dt1) && dt1.GetBoolean())
            {
                // Colosseum's reflection / extension-lightmap second layer draws dark in Melee: keep only TEX0
                var seenM = new HashSet<HSDStruct>();
                foreach (var jj in tl) if (jj.Dobj != null) foreach (var dd in jj.Dobj.List)
                    if (dd.Mobj?.Textures?.Next != null && seenM.Add(dd.Mobj._s))
                    {
                        dd.Mobj.Textures.Next = null;
                        dd.Mobj.RenderFlags &= ~(RENDER_MODE.TEX1 | RENDER_MODE.TEX2 | RENDER_MODE.TEX3);
                    }
                Console.WriteLine($"  desc {desc}: dropped the second texture layer on {seenM.Count} materials");
            }
            if (d.TryGetProperty("bake_lit", out var bl) && bl.GetBoolean())
            {
                // vertex-coloured lit materials (the elder tree) carry Colosseum's baked shading in their vertex colours:
                // draw them unlit like the terrain (and let brighten_baked give them the same x2)
                var seenM = new HashSet<HSDStruct>();
                foreach (var jj in tl) if (jj.Dobj != null) foreach (var dd in jj.Dobj.List)
                    if (dd.Mobj != null && dd.Mobj.RenderFlags.HasFlag(RENDER_MODE.VERTEX) && dd.Mobj.RenderFlags.HasFlag(RENDER_MODE.DIFFUSE) && seenM.Add(dd.Mobj._s))
                        dd.Mobj.RenderFlags &= ~(RENDER_MODE.DIFFUSE | RENDER_MODE.SPECULAR);
                Console.WriteLine($"  desc {desc}: {seenM.Count} lit vertex-colour materials drawn with baked shading");
            }
            if (d.TryGetProperty("ambient", out var amv))
            {
                // Dream Land's ambient light is full white; Colosseum's is ~30% grey. Scale lit materials' ambient to match.
                float k = amv.GetSingle(); var seenM = new HashSet<HSDStruct>();
                foreach (var jj in tl) if (jj.Dobj != null) foreach (var dd in jj.Dobj.List)
                    if (dd.Mobj?.Material != null && dd.Mobj.RenderFlags.HasFlag(RENDER_MODE.DIFFUSE) && seenM.Add(dd.Mobj._s))
                    {
                        var c = dd.Mobj.Material.AmbientColor;
                        dd.Mobj.Material.AmbientColor = System.Drawing.Color.FromArgb(c.A, (int)(c.R * k), (int)(c.G * k), (int)(c.B * k));
                    }
                Console.WriteLine($"  desc {desc}: ambient x{k} on {seenM.Count} lit materials");
            }
            if (d.TryGetProperty("tone", out var tn))
            {
                float ta = tn[0].GetSingle(), td = tn[1].GetSingle(); var seenM = new HashSet<HSDStruct>();
                foreach (var jj in tl) if (jj.Dobj != null) foreach (var dd in jj.Dobj.List)
                    if (dd.Mobj?.Material != null && dd.Mobj.RenderFlags.HasFlag(RENDER_MODE.DIFFUSE) && seenM.Add(dd.Mobj._s))
                    {
                        int a = (int)(255 * ta), b = (int)(255 * td);
                        dd.Mobj.Material.AmbientColor = System.Drawing.Color.FromArgb(255, a, a, a);
                        dd.Mobj.Material.DiffuseColor = System.Drawing.Color.FromArgb(255, b, b, b);
                    }
                Console.WriteLine($"  desc {desc}: toned {seenM.Count} lit materials");
            }
            if (d.TryGetProperty("decode_ci4", out var dci) && dci.GetBoolean())
            {
                // Celebi's CI4 swatches drew black in Melee (CI8 was fine): store them unpaletted instead
                var seenT = new HashSet<HSDStruct>(); int conv = 0;
                foreach (var jj in tl) if (jj.Dobj != null) foreach (var dd in jj.Dobj.List) if (dd.Mobj?.Textures != null)
                    foreach (var tt in dd.Mobj.Textures.List)
                        if (tt.ImageData != null && seenT.Add(tt._s) &&
                            (tt.ImageData.Format == GXTexFmt.CI4 ||
                             ((tt.ImageData.Format == GXTexFmt.CMP || tt.ImageData.Format == GXTexFmt.CI8) && (tt.ImageData.Width <= 8 || tt.ImageData.Height <= 8))))
                        {
                            var px = tt.GetDecodedImageData();
                            int w = tt.ImageData.Width, h = tt.ImageData.Height;
                            bool alpha = false; for (int i = 3; i < px.Length; i += 4) if (px[i] < 250) { alpha = true; break; }
                            var img = new HSD_Image();
                            tt.ImageData = img;
                            tt.EncodeImageData(px, w, h, alpha ? GXTexFmt.RGB5A3 : GXTexFmt.RGB565, GXTlutFmt.RGB565);
                            tt.TlutData = null;
                            conv++;
                        }
                Console.WriteLine($"  desc {desc}: {conv} CI4/tiny textures -> direct colour");
            }
            if (d.TryGetProperty("unlit", out var ul) && ul.GetBoolean())
            {
                // skip lighting: colour = material colour x texture (Celebi's body went black under lighting)
                var seen = new HashSet<HSDStruct>();
                foreach (var jj in tl) if (jj.Dobj != null) foreach (var dd in jj.Dobj.List) if (dd.Mobj != null && seen.Add(dd.Mobj._s))
                {
                    dd.Mobj.RenderFlags &= ~(RENDER_MODE.DIFFUSE | RENDER_MODE.SPECULAR);
                    if (dd.Mobj.Material != null) { dd.Mobj.Material.DiffuseColor = System.Drawing.Color.White; dd.Mobj.Material.AmbientColor = System.Drawing.Color.White; }
                }
                Console.WriteLine($"  desc {desc}: {seen.Count} materials unlit");
            }
            if (d.TryGetProperty("tex_modulate", out var tm) && tm.GetBoolean())
            {
                // Melee doesn't draw Colosseum's COLORMAP_BLEND textures the same way (Celebi came out black): use modulate
                int changed = 0;
                foreach (var jj in tl) if (jj.Dobj != null) foreach (var dd in jj.Dobj.List) if (dd.Mobj?.Textures != null)
                    foreach (var tt in dd.Mobj.Textures.List)
                    {
                        int f = (int)tt.Flags, f0 = f;
                        if ((f & 0xF0000) == (3 << 16)) f = (f & ~0xF0000) | (4 << 16);
                        if ((f & 0xF00000) == (2 << 20)) f = (f & ~0xF00000) | (3 << 20);
                        if (f != f0) { tt.Flags = (TOBJ_FLAGS)f; changed++; }
                    }
                Console.WriteLine($"  desc {desc}: {changed} textures blend -> modulate");
            }
            HSD_JOBJ parentJ; System.Numerics.Matrix4x4 baseM;
            if (d.TryGetProperty("place", out var pl))
            {
                var pt = pl.GetProperty("t").EnumerateArray().Select(e => e.GetSingle()).ToArray();
                float psx = 1f, psy = 1f, psz = 1f;
                if (pl.TryGetProperty("s", out var psv))
                {
                    if (psv.ValueKind == JsonValueKind.Array) { psx = psv[0].GetSingle(); psy = psv[1].GetSingle(); psz = psv[2].GetSingle(); }
                    else psx = psy = psz = psv.GetSingle();
                }
                float ps = psx;
                float ry = (pl.TryGetProperty("ry", out var ryv) ? ryv.GetSingle() : 0f) * MathF.PI / 180f;
                parentJ = new HSD_JOBJ { Flags = RootAll, SX = psx, SY = psy, SZ = psz, RY = ry, TX = pt[0], TY = pt[1], TZ = pt[2] };
                if (d.TryGetProperty("path", out var pth))
                {
                    // a looping flight path: groot -> path joint (authored TRA + ROTY keys) -> the place joint (local offset)
                    var pathJ = new HSD_JOBJ { Flags = RootAll, SX = 1, SY = 1, SZ = 1 };
                    Append(groot, pathJ);
                    pathAobjs[pathJ] = PathAobj(pth);
                    Append(pathJ, parentJ);
                }
                else Append(groot, parentJ);
                baseM = System.Numerics.Matrix4x4.CreateScale(psx, psy, psz) * System.Numerics.Matrix4x4.CreateRotationY(ry) * System.Numerics.Matrix4x4.CreateTranslation(pt[0], pt[1], pt[2]);
            }
            else { parentJ = wrappers[wi].j; baseM = wrappers[wi].m; }
            var worlds = new Dictionary<HSD_JOBJ, System.Numerics.Matrix4x4>();
            Worlds(clone, baseM, worlds);
            if (d.TryGetProperty("bake_light", out var bkl) && bkl.GetBoolean())
            {
                // Lit vertex-coloured materials (the elder tree, white roots) get Colosseum's lighting baked into
                // their vertex colours (Agate's scene: ambient 0.3, sun 1.0 upper-left, fill 0.3 below, back 0.5)
                // and are then drawn unlit; brighten_baked's x2 stage applies, so the bake is stored at half.
                var L = new[] { (Vector3.Normalize(new Vector3(-45.6f, 81.9f, 44f)), 1.0f),
                                (Vector3.Normalize(new Vector3(22.4f, -40.1f, 39f)), 0.3f),
                                (Vector3.Normalize(new Vector3(48.4f, 81.9f, -9f)), 0.5f) };
                var mats = new HashSet<HSDStruct>(); int baked = 0;
                for (int j2 = 0; j2 < tl.Count; j2++)
                {
                    var jo2 = tl[j2];
                    if (jo2.Dobj == null) continue;
                    var jw2 = worlds[jo2];
                    foreach (var dd in jo2.Dobj.List)
                    {
                        var m = dd.Mobj;
                        if (m == null || !m.RenderFlags.HasFlag(RENDER_MODE.VERTEX) || dd.Pobj == null) continue;
                        if (!m.RenderFlags.HasFlag(RENDER_MODE.DIFFUSE) && !bakedMats.Contains(m._s)) continue;   // shared with an earlier copy
                        float ambM = (m.Material?.AmbientColor.R ?? 128) / 255f * 0.3f;
                        HSD_POBJ head2 = null, tail2 = null;
                        foreach (var p in dd.Pobj.List)
                        {
                            HSD_POBJ np = p;
                            var attrs = p.ToGXAttributes().Select(a => a.AttributeName).Where(a => a != GXAttribName.GX_VA_NULL).ToArray();
                            if (Rigid(p) && attrs.Contains(GXAttribName.GX_VA_NRM) && attrs.Contains(GXAttribName.GX_VA_CLR0))
                            {
                                var tris = Triangles(p.ToDisplayList());
                                for (int i = 0; i < tris.Count; i++)
                                {
                                    var v = tris[i];
                                    var n = Vector3.Normalize(Vector3.TransformNormal(new Vector3(v.NRM.X, v.NRM.Y, v.NRM.Z), jw2) + new Vector3(1e-6f));
                                    float dsum = 0; foreach (var (ldir, k) in L) dsum += k * Math.Max(0f, Vector3.Dot(n, ldir));
                                    float F(float c) => Math.Clamp((ambM + 2f * c * dsum) * 0.5f, 0f, 1f);   // Colosseum doubles vertex colour here too
                                    v.CLR0 = new GXColor4(F(v.CLR0.R), F(v.CLR0.G), F(v.CLR0.B), v.CLR0.A);
                                    tris[i] = v;
                                }
                                var cf = p.Flags.HasFlag(POBJ_FLAG.CULLFRONT); var cb = p.Flags.HasFlag(POBJ_FLAG.CULLBACK);
                                var gen = new POBJ_Generator { CullMode = cf && cb ? GenCullMode.FrontAndBack : cf ? GenCullMode.Front : cb ? GenCullMode.Back : GenCullMode.None,
                                    VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
                                np = gen.CreatePOBJsFromTriangleList(tris, attrs, null);
                                gen.SaveChanges();
                                baked++;
                            }
                            var last = np; while (last.Next != null) last = last.Next;
                            if (head2 == null) head2 = np; else tail2.Next = np;
                            tail2 = last;
                        }
                        tail2.Next = null;
                        dd.Pobj = head2;
                        mats.Add(m._s);
                    }
                }
                foreach (var jo2 in tl) if (jo2.Dobj != null) foreach (var dd in jo2.Dobj.List)
                    if (dd.Mobj != null && mats.Contains(dd.Mobj._s)) dd.Mobj.RenderFlags &= ~(RENDER_MODE.DIFFUSE | RENDER_MODE.SPECULAR);
                bakedMats.UnionWith(mats);
                Console.WriteLine($"  desc {desc}: baked Colosseum lighting into {baked} polygon sets ({mats.Count} materials)");
            }
            HashSet<(int, int)> only = null;
            if (d.TryGetProperty("only", out var on))
            {
                only = new HashSet<(int, int)>();
                foreach (var e in on.EnumerateArray()) only.Add((e[0].GetInt32(), e[1].GetInt32()));
            }
            bool allowCut = !d.TryGetProperty("cut", out var cu) || cu.GetBoolean();

            var hideSet = new HashSet<(int, int)>();
            if (d.TryGetProperty("hide", out var hide))
                foreach (var e in hide.EnumerateArray()) hideSet.Add((e[0].GetInt32(), e[1].GetInt32()));
            var protect = new HashSet<int>();
            if (d.TryGetProperty("protect", out var pr)) foreach (var e in pr.EnumerateArray()) protect.Add(e.GetInt32());

            int dropped = 0, kept = 0, cutMeshes = 0, cutTris = 0, regionHidden = 0;
            for (int j = 0; j < tl.Count; j++)
            {
                var jo = tl[j];
                if (jo.Dobj == null) continue;
                var jw = worlds[jo];
                var keepList = new List<HSD_DOBJ>();
                var keptIdx = new List<int>();
                var all = jo.Dobj.List;
                for (int o = 0; o < all.Count; o++)
                {
                    var dobj = all[o];
                    var (lo, hi) = Bounds(dobj, jw);
                    var size = hi - lo; float diag = size.Length();
                    var ctr = (lo + hi) / 2;
                    bool huge = diag > keepIfLarger;
                    if (only != null && !only.Contains((j, o))) { dropped++; continue; }
                    // Colosseum characters carry collision proxies: untextured meshes, often on HIDDEN joints (Melee draws them anyway)
                    // (skinned untextured meshes are real parts: Marill's eyes and mouth)
                    if (stripCubes && (jo.Flags.HasFlag(JOBJ_FLAG.HIDDEN) || (dobj.Mobj?.Textures == null && dobj.Pobj != null
                        && dobj.Pobj.List.All(Rigid) && VertCount(dobj) <= 36))) { dropped++; continue; }
                    if (report != null && lo.X <= report.x1 && hi.X >= report.x0 && lo.Y <= report.y1 && hi.Y >= report.y0 && lo.Z <= report.z1 && hi.Z >= report.z0)
                        Console.WriteLine($"  [{desc}:{j}:{o}] ctr=({ctr.X:F0},{ctr.Y:F0},{ctr.Z:F0}) size=({size.X:F0},{size.Y:F0},{size.Z:F0}) {(hideSet.Contains((j, o)) ? "HIDE-LIST" : "")}{(protect.Contains(j) ? " PROTECT" : "")} {dobj.Mobj?.RenderFlags} tex={dobj.Mobj?.Textures?.ImageData?.Width}");
                    if (hideSet.Contains((j, o)) && !huge) { dropped++; continue; }
                    if (!protect.Contains(j) && diag < hideMaxDiag && hideRegions.Any(r => r.Has(ctr))) { regionHidden++; continue; }
                    bool xlu = dobj.Mobj != null && dobj.Mobj.RenderFlags.HasFlag(RENDER_MODE.XLU);
                    if (hideShadowCards && xlu && !huge && !protect.Contains(j) && dobj.Mobj.Textures == null) { regionHidden++; continue; }
                    bool touches = cutRegions.Any(r => lo.X <= r.x1 && hi.X >= r.x0 && lo.Y <= r.y1 && hi.Y >= r.y0 && lo.Z <= r.z1 && hi.Z >= r.z0);
                    if (allowCut && !protect.Contains(j) && !huge && xlu && touches) { regionHidden++; continue; }
                    if (allowCut && !protect.Contains(j) && diag < cutMinDiag && cutRegions.Any(r => r.Has(ctr))) { regionHidden++; continue; }
                    if (allowCut && !protect.Contains(j) && !xlu && diag >= cutMinDiag && diag < cutMaxDiag && cutRegions.Count > 0 && dobj.Pobj != null)
                    {
                        int before = cutTris;
                        dobj.Pobj = CutPobjs(dobj.Pobj, jw, cutRegions, ref cutTris);
                        if (cutTris > before) cutMeshes++;
                        if (dobj.Pobj == null) { dropped++; continue; }
                    }
                    if (unseen != null && !xlu && dobj.Pobj != null)
                    {
                        dobj.Pobj = UnseenPobjs(dobj.Pobj, jw, unseen, unseenSign, ref unseenGone, ref unseenAll);
                        if (dobj.Pobj == null) { dropped++; continue; }
                    }
                    keepList.Add(dobj); keptIdx.Add(o); kept++;
                }
                if (keepList.Count == 0) jo.Dobj = null;
                else
                {
                    for (int i = 0; i < keepList.Count; i++) keepList[i].Next = i + 1 < keepList.Count ? keepList[i + 1] : null;
                    jo.Dobj = keepList[0];
                }
                // material anims are per DObj: keep the ones whose DObj survived, in the same order
                if (mlist != null && keepList.Count != all.Count && mlist[j].MaterialAnimation != null)
                {
                    var mas = mlist[j].MaterialAnimation.List;
                    var km = keptIdx.Where(i => i < mas.Count).Select(i => mas[i]).ToList();
                    for (int i = 0; i < km.Count; i++) km[i].Next = i + 1 < km.Count ? km[i + 1] : null;
                    mlist[j].MaterialAnimation = km.Count > 0 ? km[0] : null;
                }
            }
            if (d.TryGetProperty("mat_alpha", out var mav))
            {
                var seenM = new HashSet<HSDStruct>();
                foreach (var jj in tl) if (jj.Dobj != null) foreach (var dd in jj.Dobj.List)
                    if (dd.Mobj?.Material != null && dd.Mobj.RenderFlags.HasFlag(RENDER_MODE.XLU) && seenM.Add(dd.Mobj._s)) dd.Mobj.Material.Alpha = mav.GetSingle();
                Console.WriteLine($"  desc {desc}: material alpha {mav.GetSingle()} on {seenM.Count} translucent materials");
            }
            if (d.TryGetProperty("vtx_scale", out var vsc))
                Console.WriteLine($"  desc {desc}: vertex colour x{vsc.GetSingle()} on {VtxScale(tl, vsc.GetSingle(), new HashSet<HSDStruct>())} polygon sets");
            if (d.TryGetProperty("water_scroll", out var wsc))
                Console.WriteLine($"  desc {desc}: water scroll on {WaterScroll(wsc, clone, tl, worlds, ref matClone, wsc.TryGetProperty("size", out var wsz) ? wsz.GetInt32() : 128)} meshes");
            // each donor gets its own holder so a root's sibling chain never merges with another donor's
            var holder = new HSD_JOBJ { Flags = RootAll, SX = 1, SY = 1, SZ = 1, Child = clone };
            Append(parentJ, holder);
            if (animClone != null) animSubs[holder] = animClone;
            if (matClone != null) matSubs[holder] = matClone;
            Console.WriteLine($"donor desc {desc}: {tl.Count} joints, kept {kept}, dropped {dropped}, region-hidden {regionHidden}, cut {cutTris} tris in {cutMeshes} meshes");
        }

        if (unseen != null) Console.WriteLine($"unseen: {unseenGone} of {unseenAll} one-sided triangles face no camera and are gone");
        if (spec.TryGetProperty("downscale", out var dsE)) DownscaleTextures(groot, dsE[0].GetInt32(), dsE[1].GetInt32(), dsE.GetArrayLength() < 3 || dsE[2].GetBoolean());
        if (spec.TryGetProperty("fod", out var fodE)) BuildFod(fodE, head, groups, donorFiles, memos);
        if (spec.TryGetProperty("bf", out var bfE)) BuildBf(bfE, groot, donorFiles, memos);
        if (spec.TryGetProperty("clear_joints", out var cjE)) ClearJoints(cjE, groups);
        if (spec.TryGetProperty("cs", out var csE)) BuildCs(csE, groot, spec.GetProperty("target").GetString(), groups);
        if (spec.TryGetProperty("move_joints", out var mjE)) MoveJoints(mjE, groups);
        if (spec.TryGetProperty("joint_xform", out var jxE)) JointXform(jxE, groups);
        if (spec.TryGetProperty("clear_dobjs", out var cdE)) ClearDobjs(cdE, groups);
        if (spec.TryGetProperty("shrink_tex", out var stE)) ShrinkTex(stE, groups);
        if (spec.TryGetProperty("clear_mat_anims", out var cmaE)) ClearMatAnims(cmaE, head, groups);
        if (spec.TryGetProperty("drop_anims", out var daE)) DropAnims(daE, head, groups);
        if (spec.TryGetProperty("strip_ptcl_groups", out var spg)) StripPtcl(head, groups, spg.EnumerateArray().Select(e => e.GetInt32()));
        if (spec.TryGetProperty("island2", out var isl2)) BuildIsland2(isl2, groot, donorFiles, memos);
        else if (spec.TryGetProperty("island", out var isl))
        {
            var mfile = isl.GetProperty("file").GetString();
            int mdesc = isl.GetProperty("desc").GetInt32(), mj = isl.GetProperty("joint").GetInt32(), md = isl.GetProperty("dobj").GetInt32();
            var srcJ = Scene(donorFiles[mfile]).JOBJDescs[mdesc].RootJoint.TreeList[mj];
            var srcD = srcJ.Dobj.List[md];
            var mobj = Copy(srcD.Mobj, memos[mfile]);   // shares the atlas image with the grafted village
            var clr = isl.GetProperty("color").EnumerateArray().Select(e => e.GetSingle()).ToArray();
            var tris = IslandTris(new GXColor4(clr[0], clr[1], clr[2], 1));
            var gen = new POBJ_Generator { CullMode = GenCullMode.None };
            var attrs = new List<GXAttribName> { GXAttribName.GX_VA_POS, GXAttribName.GX_VA_NRM };
            if (isl.GetProperty("use_clr0").GetBoolean()) attrs.Add(GXAttribName.GX_VA_CLR0);
            attrs.Add(GXAttribName.GX_VA_TEX0);
            var pobj = gen.CreatePOBJsFromTriangleList(tris, attrs.ToArray(), null);
            gen.SaveChanges();
            var dobj = new HSD_DOBJ { Mobj = mobj, Pobj = pobj };
            var jflags = JOBJ_FLAG.OPA | (srcJ.Flags & JOBJ_FLAG.LIGHTING);
            Append(groot, new HSD_JOBJ { Flags = jflags, SX = 1, SY = 1, SZ = 1, Dobj = dobj });
            Console.WriteLine($"island: {tris.Count / 3} tris, joint flags {jflags}, src mobj {srcD.Mobj.RenderFlags}");
        }

        if (animSubs.Count > 0 || matSubs.Count > 0 || pathAobjs.Count > 0)
        {
            // one looping animation for the whole group; Dream Land's code starts anim 0 of group 5 on load
            var ja = new HSDNullPointerArrayAccessor<HSD_AnimJoint>(); ja.Set(0, MirrorA(groot, animSubs));
            var ma = new HSDNullPointerArrayAccessor<HSD_MatAnimJoint>(); ma.Set(0, MirrorM(groot, matSubs));
            groups[recv].JointAnimations = ja;
            groups[recv].MaterialAnimations = ma;
            head.ModelGroups[recv] = groups[recv];   // groups are embedded copies: write the edited one back
            Console.WriteLine($"group {recv} anims: {animSubs.Count} joint, {matSubs.Count} material");
        }

        if (spec.TryGetProperty("props", out var props)) PlaceProps(props, groot, donorFiles, memos);

        if (spec.TryGetProperty("brighten_baked", out var bb) && bb.GetBoolean())
        {
            // Colosseum shows its baked vertex lighting about twice as bright as Melee does. Per unlit vertex-coloured
            // material, give the texture its own copy with a custom colour stage: TEXC x2 (clamped) before the
            // colormap multiply with the vertex colour. Image data stays shared, so this costs nothing in memory.
            var seenM = new HashSet<HSDStruct>(); int n = 0;
            foreach (var jo in groot.TreeList)
            {
                if (jo.Dobj == null) continue;
                foreach (var dd in jo.Dobj.List)
                {
                    var m = dd.Mobj;
                    if (m?.Textures == null || !seenM.Add(m._s) || noBrighten.Contains(m._s)) continue;
                    if (!m.RenderFlags.HasFlag(RENDER_MODE.VERTEX) || m.RenderFlags.HasFlag(RENDER_MODE.DIFFUSE)) continue;
                    var src = m.Textures;
                    var t = new HSD_TOBJ { _s = new HSDStruct((byte[])src._s.GetData().Clone()) };
                    foreach (var r in src._s.References) t._s.References[r.Key] = r.Value;
                    t.TEV = new HSD_TOBJ_TEV
                    {
                        color_op = TevColorOp.GX_TEV_ADD, color_bias = TevBias.GX_TB_ZERO, color_scale = TevScale.GX_CS_SCALE_2, color_clamp = true,
                        color_a_in = TOBJ_TEV_CC.GX_CC_ZERO, color_b_in = TOBJ_TEV_CC.GX_CC_ZERO, color_c_in = TOBJ_TEV_CC.GX_CC_ZERO, color_d_in = TOBJ_TEV_CC.GX_CC_TEXC,
                        active = TOBJ_TEVREG_ACTIVE.COLOR_TEV
                    };
                    m.Textures = t; n++;
                }
            }
            Console.WriteLine($"brightened {n} baked-lit materials (texture x2 stage)");
        }

        if (spec.TryGetProperty("fog", out var fg))
        {
            var col = fg.GetProperty("color").EnumerateArray().Select(e => e.GetInt32()).ToArray();
            int fgi = fg.TryGetProperty("group", out var fgg) ? fgg.GetInt32() : recv;
            groups[fgi].Fog = new HSD_FogDesc { Type = FogType.PerspectiveLinear, Start = fg.GetProperty("start").GetSingle(),
                End = fg.GetProperty("end").GetSingle(), Color = System.Drawing.Color.FromArgb(255, col[0], col[1], col[2]) };
            head.ModelGroups[fgi] = groups[fgi];
            Console.WriteLine($"group {fgi} fog {groups[fgi].Fog.Start}..{groups[fgi].Fog.End}");
        }

        if (spec.TryGetProperty("scene_lights", out var sl))
        {
            var lf = sl.GetString();
            if (!donorFiles.TryGetValue(lf, out var lfile)) { lfile = ReadArchive(lf); donorFiles[lf] = lfile; memos[lf] = new Dictionary<HSDStruct, HSDStruct>(); }
            var src = Scene(lfile).Lights;
            var arr = new HSDNullPointerArrayAccessor<HSD_Light>();
            int n = 0;
            foreach (var l in src.Array)
            {
                var o = l.LightObject;
                if (o == null || o._s.Length < 0x18) continue;
                var type = (int)o.Flags & 3;           // 0 ambient, 1 infinite, 2 point, 3 spot
                if (type > 1) continue;
                var c = Copy(l, memos[lf]);
                c.AnimPointer = null;
                arr.Set(n++, c);
            }
            groups[recv].Lights = arr;
            head.ModelGroups[recv] = groups[recv];
            Console.WriteLine($"group {recv} lights: {n} from {lf}");
        }

        if (spec.TryGetProperty("item_frames", out var itf))
        {
            // A stage's own item drawn as one flat card (Yoshi's Story's Shy Guy: itemdata -> article -> model, a 4-vertex quad) shows one of a few pictures:
            // the card's own texture and the frames of its material animation (article -> states -> image table). Every picture the article holds is replaced,
            // frame i by images[i], any beyond the list by the last. Pictures are .img files (int32 w, int32 h, BGRA), stored RGB5A3 as the card's were.
            var art = file.Roots.First(r => r.Name == "itemdata").Data._s.References[itf.GetProperty("article").GetInt32() * 4].References[0x04];
            var paths = itf.GetProperty("images").EnumerateArray().Select(e => e.GetString()).ToArray();
            var found = new List<HSDStruct>();
            var seen = new HashSet<HSDStruct>();
            void Find(HSDStruct st)
            {
                if (!seen.Add(st)) return;
                // an image desc: 24 bytes, its data at 0x00, then width and height as shorts and the format
                if (st.Length == 24 && st.References.Count == 1 && st.References.ContainsKey(0) && st.GetInt16(4) > 0 && st.GetInt16(6) > 0
                    && st.References[0].Length >= st.GetInt16(4) * st.GetInt16(6)) { found.Add(st); return; }
                foreach (var r in st.References.OrderBy(k => k.Key)) Find(r.Value);
            }
            if (art.References.TryGetValue(0x0C, out var itStates)) Find(itStates);     // the animation's frames first, in their own order
            int frames = found.Count;
            Find(art.References[0x10]);                                                 // then the card's own texture, if it is not one of them
            for (int i = 0; i < found.Count; i++)
            {
                var bytes = File.ReadAllBytes(paths[Math.Min(i < frames ? i : 0, paths.Length - 1)]);
                int w = BitConverter.ToInt32(bytes, 0), h = BitConverter.ToInt32(bytes, 4);
                var px = new byte[w * h * 4];
                Array.Copy(bytes, 8, px, 0, px.Length);
                var tmp = new HSD_TOBJ { ImageData = new HSD_Image() };
                tmp.EncodeImageData(px, w, h, GXTexFmt.RGB5A3, GXTlutFmt.RGB565);
                var img = new HSD_Image { _s = found[i] };
                Console.WriteLine($"item picture {i}: {img.Width}x{img.Height} {img.Format} -> {w}x{h} RGB5A3");
                img.ImageData = tmp.ImageData.ImageData; img.Width = (short)w; img.Height = (short)h; img.Format = GXTexFmt.RGB5A3;
            }
        }

        if (spec.TryGetProperty("item_card", out var itc))
        {
            // A two-faced card for a stage item that is one flat quad (Yoshi's Story's Shy Guy). The game turns the card half round when the item flies the
            // other way, so a one-faced card shows its picture mirrored then: fine for a face, wrong for lettering. Here the quad is drawn twice, once seen
            // only from its front ("front" pictures) and once only from its back ("back" pictures, which the turn mirrors on screen: give them already
            // mirrored wherever they must read true). Each list is the frames of the card's material animation, in order; the second face gets a copy of it.
            var art = file.Roots.First(r => r.Name == "itemdata").Data._s.References[itc.GetProperty("article").GetInt32() * 4].References[0x04];
            var front = itc.GetProperty("front").EnumerateArray().Select(e => e.GetString()).ToArray();
            var back = itc.GetProperty("back").EnumerateArray().Select(e => e.GetString()).ToArray();
            bool swap = itc.TryGetProperty("swap_faces", out var sw) && sw.GetBoolean();
            void SetImage(HSDStruct st, string path)
            {
                var bytes = File.ReadAllBytes(path);
                int w = BitConverter.ToInt32(bytes, 0), h = BitConverter.ToInt32(bytes, 4);
                var px = new byte[w * h * 4];
                Array.Copy(bytes, 8, px, 0, px.Length);
                // CMPR: a quarter of RGB5A3's bytes, so the pictures can be bigger. Its alpha is one bit, which a picture that is solid or absent loses nothing by.
                var img = new HSD_Image { _s = st };
                img.ImageData = GXImageConverter.ToCMP(px, w, h); img.Width = (short)w; img.Height = (short)h; img.Format = GXTexFmt.CMP;
                img.MipMap = 0; img.MinLOD = 0; img.MaxLOD = 0;
            }
            var card = new HSD_JOBJ { _s = art.References[0x10].References[0x00] }.TreeList.First(j => j.Dobj != null);
            var a = card.Dobj;
            var b = Copy(a, new Dictionary<HSDStruct, HSDStruct>());
            b.Next = null; a.Next = b;
            // HSDRaw's names are the reverse of the game's: its CULLFRONT is 0x8000, which the game reads as POBJ_CULLBACK (draw the front, cull the back)
            foreach (var p in a.Pobj.List) p.Flags = (p.Flags & ~(POBJ_FLAG.CULLFRONT | POBJ_FLAG.CULLBACK)) | (swap ? POBJ_FLAG.CULLFRONT : POBJ_FLAG.CULLBACK);
            foreach (var p in b.Pobj.List) p.Flags = (p.Flags & ~(POBJ_FLAG.CULLFRONT | POBJ_FLAG.CULLBACK)) | (swap ? POBJ_FLAG.CULLBACK : POBJ_FLAG.CULLFRONT);
            SetImage(a.Mobj.Textures.ImageData._s, front[0]);
            SetImage(b.Mobj.Textures.ImageData._s, back[0]);
            // the animation: MatAnimJoint tree -> the card joint's MatAnim {next, aobj, texanim, renderanim} -> TexAnim's image table at 0x0C
            HSDStruct FindMatAnim(HSDStruct mj)
            {
                if (mj == null) return null;
                if (mj.References.TryGetValue(0x08, out var m)) return m;
                mj.References.TryGetValue(0x00, out var child); mj.References.TryGetValue(0x04, out var next);
                return FindMatAnim(child) ?? FindMatAnim(next);
            }
            var ma = FindMatAnim(art.References[0x0C].References[0x04]);
            var mb = Clone(ma, new Dictionary<HSDStruct, HSDStruct>());
            ma.SetReferenceStruct(0x00, mb);
            int n = 0;
            foreach (var (m, pics) in new[] { (ma, front), (mb, back) })
            {
                var tbl = m.References[0x08].References[0x0C];
                foreach (var r in tbl.References.OrderBy(k => k.Key)) { SetImage(r.Value, pics[Math.Min(r.Key / 4, pics.Length - 1)]); n++; }
            }
            if (itc.TryGetProperty("turn_test", out var tt0) && tt0.GetBoolean()) card.RY = (float)Math.PI;      // a test build: the card as it is when the game has turned it
            Console.WriteLine($"item card: two faces, {n} animation frames, front {front[0]}");
        }

        if (spec.TryGetProperty("plit_from", out var pf))
        {
            // The fighters are not lit by the groups' lights but by the stage file's own list, map_plit (ftCo_8009F4A4 reads it through
            // Ground_801C49B4). Battlefield's is a half-grey ambient with a pink light from below: right for its night sky, wrong on a map in
            // full sun. Another stage's list is taken whole.
            var src = ReadArchive(pf.GetString());
            var from = src.Roots.First(r => r.Name == "map_plit");
            file.Roots.First(r => r.Name == "map_plit").Data = from.Data;
            Console.WriteLine($"map_plit (the fighters' lights) from {pf.GetString()}");
        }

        if (spec.TryGetProperty("drop_image_roots", out var dir) && dir.GetBoolean())
        {
            // Dream Land exports its texture images as public symbols; the game only looks up map_head, coll_data,
            // grGroundParam, itemdata, ALDYakuAll, map_ptcl, map_texg, yakumono_param, map_plit, quake_model_set.
            // Data still referenced elsewhere stays; unreferenced images (the 512 KB background) drop out.
            int before = file.Roots.Count;
            file.Roots.RemoveAll(r => r.Name.EndsWith("_image") || r.Name.EndsWith("_tlut") || r.Name.EndsWith("_tlut_desc"));
            Console.WriteLine($"dropped {before - file.Roots.Count} image root symbols");
        }

        if (spec.TryGetProperty("drop_roots", out var drr))
            foreach (var nm in drr.EnumerateArray().Select(e => e.GetString()))
                Console.WriteLine($"dropped root {nm}: {file.Roots.RemoveAll(r => r.Name == nm)}");

        var outPath = spec.GetProperty("out").GetString();
        Directory.CreateDirectory(Path.GetDirectoryName(outPath));
        file.Save(outPath);
        Console.WriteLine($"saved {outPath} {new FileInfo(outPath).Length} bytes");
        return 0;
    }

    // Dream Land island on the exact collision outline + three plank platforms, UVs into Agate's atlas (pixels).
    static List<GX_Vertex> IslandTris(GXColor4 clr)
    {
        var tris = new List<GX_Vertex>();
        void Quad((float x, float y, float z)[] p, (float u, float v)[] uv, (float x, float y, float z) n)
        {
            GX_Vertex V(int i) => new GX_Vertex
            {
                POS = new GXVector3(p[i].x, p[i].y, p[i].z),
                NRM = new GXVector3(n.x, n.y, n.z),
                CLR0 = clr,
                TEX0 = new GXVector2(uv[i].u / 1024f, uv[i].v / 1024f)
            };
            tris.Add(V(0)); tris.Add(V(1)); tris.Add(V(2));
            tris.Add(V(0)); tris.Add(V(2)); tris.Add(V(3));
        }
        var GRASS = (u0: 470f, v0: 8f, u1: 935f, v1: 152f);
        var CLIFF = (u0: 2f, v0: 382f, u1: 250f, v1: 668f);
        var ROCK = (u0: 2f, v0: 470f, u1: 250f, v1: 668f);
        var PLANK = (u0: 515f, v0: 458f, u1: 638f, v1: 770f);
        const float L = 77.27f, Z = 28f;
        var outl = new (float x, float y)[] { (77.27f, 0f), (76.34f, -11.04f), (65.76f, -35.76f), (0f, -35.76f) };
        float Bottom(float x)
        {
            x = Math.Abs(x);
            for (int i = 0; i + 1 < outl.Length; i++)
                if (outl[i + 1].x <= x && x <= outl[i].x)
                    return outl[i].y + (outl[i + 1].y - outl[i].y) * (outl[i].x - x) / (outl[i].x - outl[i + 1].x);
            return -35.76f;
        }

        // grass top
        for (int i = 0; i < 6; i++)
        {
            float xa = -L + i * 2 * L / 6, xb = -L + (i + 1) * 2 * L / 6;
            foreach (var (za, zb) in new[] { (-Z, 0f), (0f, Z) })
                Quad(new[] { (xa, 0.01f, za), (xb, 0.01f, za), (xb, 0.01f, zb), (xa, 0.01f, zb) },
                     new[] { (GRASS.u0, GRASS.v0), (GRASS.u1, GRASS.v0), (GRASS.u1, GRASS.v1), (GRASS.u0, GRASS.v1) }, (0, 1, 0));
        }

        // cliff front face, 20-unit rows clipped to the collision outline
        for (int r = 0; r < 2; r++)
        {
            float ya = -20f * r, yb = ya - 20f;
            var R = r == 0 ? CLIFF : ROCK;
            for (int i = 0; i < 8; i++)
            {
                float xa = -L + i * 2 * L / 8, xb = -L + (i + 1) * 2 * L / 8;
                float ba = Math.Max(yb, Bottom(xa)), bb = Math.Max(yb, Bottom(xb));
                if (ba >= ya - 0.01f && bb >= ya - 0.01f) continue;
                float va = R.v0 + (ya - ba) / 20f * (R.v1 - R.v0), vb = R.v0 + (ya - bb) / 20f * (R.v1 - R.v0);
                Quad(new[] { (xa, ya, Z), (xb, ya, Z), (xb, bb, Z), (xa, ba, Z) },
                     new[] { (R.u0, R.v0), (R.u1, R.v0), (R.u1, vb), (R.u0, va) }, (0, 0, 1));
            }
        }

        // side walls and underside along the collision outline
        var full = new (float x, float y)[] { (-77.27f, 0f), (-76.34f, -11.04f), (-65.76f, -35.76f), (65.76f, -35.76f), (76.34f, -11.04f), (77.27f, 0f) };
        for (int i = 0; i + 1 < full.Length; i++)
        {
            var a = full[i]; var b = full[i + 1];
            float len = MathF.Sqrt((b.x - a.x) * (b.x - a.x) + (b.y - a.y) * (b.y - a.y));
            // ~20-unit tiles along the wall, 2 tiles across the depth: the rock never stretches
            int segs = Math.Max(1, (int)MathF.Round(len / 20f));
            float nx = (b.y - a.y) / len, ny = -(b.x - a.x) / len;   // outward for this clockwise walk
            float vspan = Math.Min(1f, len / segs / 20f) * (ROCK.v1 - ROCK.v0);
            for (int k = 0; k < segs; k++)
            {
                float t0 = k / (float)segs, t1 = (k + 1) / (float)segs;
                float x0 = a.x + (b.x - a.x) * t0, y0 = a.y + (b.y - a.y) * t0;
                float x1 = a.x + (b.x - a.x) * t1, y1 = a.y + (b.y - a.y) * t1;
                foreach (var (za, zb) in new[] { (Z, 0f), (0f, -Z) })
                    Quad(new[] { (x0, y0, za), (x1, y1, za), (x1, y1, zb), (x0, y0, zb) },
                         new[] { (ROCK.u0, ROCK.v0), (ROCK.u0, ROCK.v0 + vspan), (ROCK.u1, ROCK.v0 + vspan), (ROCK.u1, ROCK.v0) }, (nx, ny, 0f));
            }
        }

        // planks on the exact platform lines (the right one is 0.1 higher, as in vanilla)
        foreach (var (x0, x1, y) in new[] { (-61.39f, -31.73f, 30.14f), (31.70f, 63.07f, 30.24f), (-19.02f, 19.02f, 51.43f) })
        {
            var uv = new[] { (PLANK.u0, PLANK.v0), (PLANK.u0, PLANK.v1), (PLANK.u1, PLANK.v1), (PLANK.u1, PLANK.v0) };
            for (int k = 0; k < 3; k++)
            {
                float xa = x0 + k * (x1 - x0) / 3, xb = x0 + (k + 1) * (x1 - x0) / 3;
                Quad(new[] { (xa, y, 8f), (xb, y, 8f), (xb, y - 2.2f, 8f), (xa, y - 2.2f, 8f) }, uv, (0, 0, 1));
                Quad(new[] { (xa, y, -8f), (xb, y, -8f), (xb, y, 8f), (xa, y, 8f) }, uv, (0, 1, 0));
                Quad(new[] { (xa, y - 2.2f, -8f), (xb, y - 2.2f, -8f), (xb, y - 2.2f, 8f), (xa, y - 2.2f, 8f) }, uv, (0, -1, 0));
            }
        }
        return tris;
    }
}
