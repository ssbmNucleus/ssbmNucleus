// Stage meshes and textures prepared in Blender or custom scripts and hung on the stage's main group.
//  spec "cs": { "meshes": [ { "name", "mesh": triangle file, "tex": image file, "wrap": "clamp"|"repeat"|"mirror",
//                             "mips": true, "colors": false, "cutout": false, "joint": [group, joint] } ] }
//  With "joint" the mesh rides that existing joint of the stage (a moving platform, a form root) instead of hanging on the main group.
//  mesh file: int32 vertex count, then per vertex 9 floats: px py pz  u v  r g b a  (triangle list, stage file units)
//  image file: int32 w, int32 h, then BGRA bytes
// Without "colors" a mesh draws its texture flat (CONSTANT): the light is already in the bake.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.GX;
using HSDRaw.Melee.Gr;
using HSDRaw.Tools;

static partial class Program
{
    static HSD_MOBJ FirstMobj(HSDRawFile f)
    {
        var head = f.Roots.Select(r => r.Data).OfType<SBM_Map_Head>().First();
        foreach (var g in head.ModelGroups.Array)
            foreach (var jo in g.RootNode.TreeList)
                if (jo.Dobj != null)
                    foreach (var d in jo.Dobj.List)
                        if (d.Mobj?.Textures != null) return d.Mobj;
        throw new Exception("no textured material in target");
    }

    static HSD_DOBJ CsDobj(HSD_MOBJ m, List<GX_Vertex> tris, bool colors)
    {
        var gen = new POBJ_Generator { CullMode = GenCullMode.None, VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
        var attrs = colors ? new[] { GXAttribName.GX_VA_POS, GXAttribName.GX_VA_CLR0, GXAttribName.GX_VA_TEX0 }
                           : new[] { GXAttribName.GX_VA_POS, GXAttribName.GX_VA_TEX0 };
        var p = gen.CreatePOBJsFromTriangleList(tris, attrs, null);
        gen.SaveChanges();
        return new HSD_DOBJ { Mobj = m, Pobj = p };
    }

    static bool MarkPath(HSD_JOBJ j, HSD_JOBJ target)
    {
        if (j == target) { j.Flags |= JOBJ_FLAG.ROOT_OPA | JOBJ_FLAG.ROOT_XLU | JOBJ_FLAG.ROOT_TEXEDGE; return true; }
        for (var c = j.Child; c != null; c = c.Next)
            if (MarkPath(c, target)) { j.Flags |= JOBJ_FLAG.ROOT_OPA | JOBJ_FLAG.ROOT_XLU | JOBJ_FLAG.ROOT_TEXEDGE; return true; }
        return false;
    }

    // spec "move_joints": [ { "group", "joint", "dx", "dy", "dz" } ]: stage code reads the point, nothing should show there
    static void MoveJoints(System.Text.Json.JsonElement l, SBM_Map_GOBJ[] groups)
    {
        foreach (var e in l.EnumerateArray())
        {
            var j = groups[e.GetProperty("group").GetInt32()].RootNode.TreeList[e.GetProperty("joint").GetInt32()];
            if (e.TryGetProperty("dx", out var dx)) j.TX += dx.GetSingle();
            if (e.TryGetProperty("dy", out var dy)) j.TY += dy.GetSingle();
            if (e.TryGetProperty("dz", out var dz)) j.TZ += dz.GetSingle();
        }
    }

    // spec "joint_xform": [ { "group", "joint", "t": [x, y, z], "s" } ]: Stadium's screen moves and shrinks as one, panels and live picture with it
    static void JointXform(System.Text.Json.JsonElement l, SBM_Map_GOBJ[] groups)
    {
        foreach (var e in l.EnumerateArray())
        {
            var j = groups[e.GetProperty("group").GetInt32()].RootNode.TreeList[e.GetProperty("joint").GetInt32()];
            var t = e.GetProperty("t").EnumerateArray().Select(v => v.GetSingle()).ToArray();
            float s = e.GetProperty("s").GetSingle();
            j.TX = t[0]; j.TY = t[1]; j.TZ = t[2]; j.SX = j.SY = j.SZ = s;
        }
    }

    // spec "shrink_tex": [ [group, joint, mesh, side] ]: Stadium's panels were painted for a screen five times the size
    static void ShrinkTex(System.Text.Json.JsonElement l, SBM_Map_GOBJ[] groups)
    {
        var done = new HashSet<HSDStruct>();
        foreach (var e in l.EnumerateArray())
        {
            var t = groups[e[0].GetInt32()].RootNode.TreeList[e[1].GetInt32()].Dobj.List[e[2].GetInt32()].Mobj.Textures;
            int side = e[3].GetInt32(), w = t.ImageData.Width, h = t.ImageData.Height;
            if (!done.Add(t._s)) continue;
            var small = CropResize(t.GetDecodedImageData(), w, 0, 0, w, h, side, side);
            t.TlutData = null;
            t.ImageData.Width = (short)side; t.ImageData.Height = (short)side; t.ImageData.Format = GXTexFmt.CMP;
            SingleLevel(t, small, side, side);
        }
    }

    // spec "clear_dobjs": [ [group, joint, [mesh, ...]] ]: some of a joint's meshes go, the rest stay
    static void ClearDobjs(System.Text.Json.JsonElement l, SBM_Map_GOBJ[] groups)
    {
        foreach (var e in l.EnumerateArray())
        {
            var j = groups[e[0].GetInt32()].RootNode.TreeList[e[1].GetInt32()];
            var gone = e[2].EnumerateArray().Select(v => v.GetInt32()).ToHashSet();
            var keep = j.Dobj.List.Where((d, i) => !gone.Contains(i)).ToList();
            for (int i = 0; i < keep.Count; i++) keep[i].Next = i + 1 < keep.Count ? keep[i + 1] : null;
            j.Dobj = keep.Count > 0 ? keep[0] : null;
        }
    }

    // spec "clear_joints": [ [group, joint] ]: vanilla meshes out of a group that keeps its other joints
    static void ClearJoints(System.Text.Json.JsonElement l, SBM_Map_GOBJ[] groups)
    {
        foreach (var e in l.EnumerateArray()) groups[e[0].GetInt32()].RootNode.TreeList[e[1].GetInt32()].Dobj = null;
    }

    // spec "drop_anims": [ groups ]: Yoshi's Story asks group 3 for anim 1 by array index, which only holds in the vanilla layout
    static void DropAnims(System.Text.Json.JsonElement l, SBM_Map_Head head, SBM_Map_GOBJ[] groups)
    {
        foreach (var e in l.EnumerateArray())
        {
            int g = e.GetInt32();
            groups[g].JointAnimations = null;
            groups[g].MaterialAnimations = null;
            head.ModelGroups[g] = groups[g];
        }
    }

    // spec "clear_mat_anims": [ groups ]: a stage's material anims would retarget onto the new materials
    static void ClearMatAnims(System.Text.Json.JsonElement l, SBM_Map_Head head, SBM_Map_GOBJ[] groups)
    {
        foreach (var e in l.EnumerateArray())
        {
            int g = e.GetInt32();
            if (groups[g].MaterialAnimations != null)
                foreach (var ma in groups[g].MaterialAnimations.Array)
                    if (ma != null) foreach (var n in DfsM(ma)) n.MaterialAnimation = null;
            head.ModelGroups[g] = groups[g];
        }
    }

    static void BuildCs(System.Text.Json.JsonElement cs, HSD_JOBJ groot, string targetPath, SBM_Map_GOBJ[] groups)
    {
        var memo = new Dictionary<HSDStruct, HSDStruct>();
        var tmpl = Copy(FirstMobj(ReadArchive(targetPath)), memo);       // flags and PE state only; pixels are replaced
        tmpl.Textures.Next = null;
        tmpl.Textures.TlutData = null;
        Console.WriteLine($"cs template: {tmpl.RenderFlags} pe={(tmpl.PEDesc != null ? $"{tmpl.PEDesc.BlendMode} {tmpl.PEDesc.SrcFactor}/{tmpl.PEDesc.DstFactor}" : "none")}");
        tmpl.PEDesc = null;                                                 // BF's first material blends additively; these are opaque
        HSD_DOBJ first = null, last = null;
        var hung = new Dictionary<(int, int), List<HSD_DOBJ>>();
        foreach (var jm in cs.GetProperty("meshes").EnumerateArray())
        {
            string name = jm.GetProperty("name").GetString();
            bool colors = jm.TryGetProperty("colors", out var ce) && ce.GetBoolean();
            bool mips = !jm.TryGetProperty("mips", out var me) || me.GetBoolean();
            string wrapName = jm.TryGetProperty("wrap", out var we) ? we.GetString() : "clamp";
            var wrap = wrapName == "repeat" ? GXWrapMode.REPEAT : wrapName == "mirror" ? GXWrapMode.MIRROR : GXWrapMode.CLAMP;

            var img = File.ReadAllBytes(jm.GetProperty("tex").GetString());
            int w = BitConverter.ToInt32(img, 0), h = BitConverter.ToInt32(img, 4);
            var px = new byte[w * h * 4];
            Buffer.BlockCopy(img, 8, px, 0, px.Length);
            var tx = NewTobj(tmpl.Textures, px, w, h, wrap, wrap);
            tx.RX = tx.RY = tx.RZ = 0; tx.TX = tx.TY = tx.TZ = 0; tx.SZ = 1;    // the template's own placement: FD's first texture is turned on edge
            if (!mips) SingleLevel(tx, px, w, h);
            bool cutout = jm.TryGetProperty("cutout", out var ct) && ct.GetBoolean();
            tx.Flags = TOBJ_FLAGS.LIGHTMAP_DIFFUSE | TOBJ_FLAGS.COLORMAP_MODULATE | (cutout ? TOBJ_FLAGS.ALPHAMAP_MODULATE : 0);
            tx.Blending = 1;
            tx.TEV = null;
            tx.GXTexGenSrc = GXTexGenSrc.GX_TG_TEX0;
            tx.TexMapID = GXTexMapID.GX_TEXMAP0;
            var m = MobjWith(tmpl, tx);
            m.RenderFlags = (colors ? RENDER_MODE.VERTEX : RENDER_MODE.CONSTANT) | RENDER_MODE.TEX0 | RENDER_MODE.ALPHA_MAT;
            m.Material.DiffuseColor = System.Drawing.Color.White;
            m.Material.AmbientColor = System.Drawing.Color.White;
            m.Material.Alpha = 1;
            if (cutout)                                                     // CMPR's transparent texels are black: a high ref trims the dark fringe
                m.PEDesc = new HSD_PEDesc { Flags = PIXEL_PROCESS_ENABLE.COLOR_UPDATE | PIXEL_PROCESS_ENABLE.ALPHA_UPDATE | PIXEL_PROCESS_ENABLE.COMPARE | PIXEL_PROCESS_ENABLE.ZUPDATE,
                    AlphaRef0 = 200, AlphaComp0 = GXCompareType.GEqual, AlphaOp = GXAlphaOp.And, AlphaRef1 = 0, AlphaComp1 = GXCompareType.Always,
                    BlendMode = GXBlendMode.GX_NONE, DepthFunction = GXCompareType.LEqual };
            noBrighten.Add(m._s);

            var raw = File.ReadAllBytes(jm.GetProperty("mesh").GetString());
            int n = BitConverter.ToInt32(raw, 0);
            var f = new float[n * 9];
            Buffer.BlockCopy(raw, 4, f, 0, f.Length * 4);
            var tris = new List<GX_Vertex>(n);
            float ox = 0, oy = 0, oz = 0;
            if (jm.TryGetProperty("joint", out var jr) && jm.TryGetProperty("minus_joint", out var mj) && mj.GetBoolean())
            {
                var jo = groups[jr[0].GetInt32()].RootNode.TreeList[jr[1].GetInt32()];
                ox = jo.TX; oy = jo.TY; oz = jo.TZ;                         // the mesh is in stage space, the joint carries its own offset
            }
            for (int i = 0; i < n; i++)
            {
                int o = i * 9;
                tris.Add(new GX_Vertex
                {
                    POS = new GXVector3(f[o] - ox, f[o + 1] - oy, f[o + 2] - oz),
                    TEX0 = new GXVector2(f[o + 3], f[o + 4]),
                    CLR0 = new GXColor4(f[o + 5], f[o + 6], f[o + 7], f[o + 8]),
                });
            }
            var d = CsDobj(m, tris, colors);
            if (jm.TryGetProperty("joint", out var je))
            {
                var key = (je[0].GetInt32(), je[1].GetInt32());
                if (!hung.TryGetValue(key, out var hl)) hung[key] = hl = new List<HSD_DOBJ>();
                hl.Add(d);
            }
            else
            {
                if (first == null) first = d; else last.Next = d;
                last = d;
            }
            Console.WriteLine($"cs {name}: {n / 3} tris, {w}x{h} texture{(mips ? " with mips" : "")}");
        }
        if (first != null) Append(groot, new HSD_JOBJ { Flags = JOBJ_FLAG.OPA, SX = 1, SY = 1, SZ = 1, Dobj = first });
        foreach (var kv in hung)
        {
            var root = groups[kv.Key.Item1].RootNode;
            var j = root.TreeList[kv.Key.Item2];
            for (int i = 0; i + 1 < kv.Value.Count; i++) kv.Value[i].Next = kv.Value[i + 1];
            kv.Value[kv.Value.Count - 1].Next = j.Dobj;
            j.Dobj = kv.Value[0];
            j.Flags = (j.Flags & ~(JOBJ_FLAG.LIGHTING | JOBJ_FLAG.SPECULAR | JOBJ_FLAG.XLU | JOBJ_FLAG.BILLBOARD)) | JOBJ_FLAG.OPA;
            MarkPath(root, j);
            Console.WriteLine($"cs: {kv.Value.Count} meshes ride group {kv.Key.Item1} joint {kv.Key.Item2}");
        }
    }

    static void SingleLevel(HSD_TOBJ t, byte[] px, int w, int h)
    {
        t.ImageData.ImageData = GXImageConverter.ToCMP(px, w, h);
        t.ImageData.MipMap = 0;
        t.ImageData.MinLOD = 0;
        t.ImageData.MaxLOD = 0;
        t.LOD = null;
    }
}
