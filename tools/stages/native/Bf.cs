// Battlefield = Phenac Stadium lobby.
//  - BuildBf: the floating stage on Battlefield's exact collision (top y=0 to the ledges at +-85.5, the jagged underside,
//    three platforms), dressed in the lobby's own materials: cream stone floor with the walkway's blue-diamond medallion,
//    a meander frieze lip, sandstone block walls, chamfered slab platforms. New joints appended to group 6.
//  - VtxScale: Colosseum shows baked vertex colour at ~2x (walls average 0.4 -> 0.8 on screen); scale CLR0 itself.
//  - Water scroll: Colosseum scrolls its waterfalls from code, not from material anims; author looping TRAU/TRAV
//    texture anims per water DObj (fall direction from the UV gradient).
//  - StripPtcl: the space backgrounds' particle tracks (star sparkles) out of the cycling background groups.
using System;
using System.Collections.Generic;
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
    // ---------------------------------------------------------------- vertex colour scale
    static int VtxScale(List<HSD_JOBJ> tl, float k, HashSet<HSDStruct> seenD)
    {
        int n = 0;
        foreach (var jo in tl)
        {
            if (jo.Dobj == null) continue;
            foreach (var dd in jo.Dobj.List)
            {
                var m = dd.Mobj;
                if (m == null || dd.Pobj == null || !seenD.Add(dd._s)) continue;
                if (!m.RenderFlags.HasFlag(RENDER_MODE.VERTEX) || m.RenderFlags.HasFlag(RENDER_MODE.DIFFUSE)) continue;
                HSD_POBJ head = null, tail = null;
                foreach (var p in dd.Pobj.List)
                {
                    HSD_POBJ np = p;
                    var attrs = p.ToGXAttributes().Select(a => a.AttributeName).Where(a => a != GXAttribName.GX_VA_NULL).ToArray();
                    if (Rigid(p) && attrs.Contains(GXAttribName.GX_VA_CLR0))
                    {
                        var tris = Triangles(p.ToDisplayList());
                        for (int i = 0; i < tris.Count; i++)
                        {
                            var v = tris[i];
                            v.CLR0 = new GXColor4(Math.Min(1f, v.CLR0.R * k), Math.Min(1f, v.CLR0.G * k), Math.Min(1f, v.CLR0.B * k), v.CLR0.A);
                            tris[i] = v;
                        }
                        var cf = p.Flags.HasFlag(POBJ_FLAG.CULLFRONT); var cb = p.Flags.HasFlag(POBJ_FLAG.CULLBACK);
                        var gen = new POBJ_Generator { CullMode = cf && cb ? GenCullMode.FrontAndBack : cf ? GenCullMode.Front : cb ? GenCullMode.Back : GenCullMode.None,
                            VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
                        np = gen.CreatePOBJsFromTriangleList(tris, attrs, null);
                        gen.SaveChanges();
                        n++;
                    }
                    var last = np; while (last.Next != null) last = last.Next;
                    if (head == null) head = np; else tail.Next = np;
                    tail = last;
                }
                tail.Next = null;
                dd.Pobj = head;
            }
        }
        return n;
    }

    // ---------------------------------------------------------------- water scroll
    static HSD_MatAnimJoint MirrorMJ(HSD_JOBJ j)
    {
        if (j == null) return null;
        return new HSD_MatAnimJoint { Child = MirrorMJ(j.Child), Next = MirrorMJ(j.Next) };
    }

    static HSD_AOBJ ScrollAobj(int frames, float du, float dv)
    {
        var ao = new HSD_AOBJ { Flags = AOBJ_Flags.ANIM_LOOP, EndFrame = frames };
        if (du != 0) ao.AddTrack((byte)TexTrackType.HSD_A_T_TRAU, new List<FOBJKey> {
            new FOBJKey { Frame = 0, Value = 0, InterpolationType = GXInterpolationType.HSD_A_OP_LIN },
            new FOBJKey { Frame = frames, Value = du, InterpolationType = GXInterpolationType.HSD_A_OP_LIN } });
        if (dv != 0) ao.AddTrack((byte)TexTrackType.HSD_A_T_TRAV, new List<FOBJKey> {
            new FOBJKey { Frame = 0, Value = 0, InterpolationType = GXInterpolationType.HSD_A_OP_LIN },
            new FOBJKey { Frame = frames, Value = dv, InterpolationType = GXInterpolationType.HSD_A_OP_LIN } });
        return ao;
    }

    // average world-space gradient of u and v along "down" over a DObj's triangles (area weighted)
    static (float gu, float gv, bool vertical) UvFall(HSD_DOBJ d, Matrix4x4 w, Vector3 dirW)
    {
        double su = 0, sv = 0, area = 0, vert = 0;
        foreach (var p in d.Pobj.List)
        {
            var t = Triangles(p.ToDisplayList());
            for (int i = 0; i + 2 < t.Count; i += 3)
            {
                Vector3 P(int k) => Vector3.Transform(new Vector3(t[i + k].POS.X, t[i + k].POS.Y, t[i + k].POS.Z), w);
                var p0 = P(0); var e1 = P(1) - p0; var e2 = P(2) - p0;
                var nrm = Vector3.Cross(e1, e2); float a = nrm.Length() / 2; if (a < 1e-4f) continue;
                nrm /= (2 * a);
                float du1 = t[i + 1].TEX0.X - t[i].TEX0.X, du2 = t[i + 2].TEX0.X - t[i].TEX0.X;
                float dv1 = t[i + 1].TEX0.Y - t[i].TEX0.Y, dv2 = t[i + 2].TEX0.Y - t[i].TEX0.Y;
                // gradient G (in plane) with G.e1 = d1, G.e2 = d2
                float a11 = Vector3.Dot(e1, e1), a12 = Vector3.Dot(e1, e2), a22 = Vector3.Dot(e2, e2);
                float det = a11 * a22 - a12 * a12; if (Math.Abs(det) < 1e-8f) continue;
                Vector3 G(float d1, float d2) { float c1 = (d1 * a22 - d2 * a12) / det, c2 = (d2 * a11 - d1 * a12) / det; return c1 * e1 + c2 * e2; }
                var down = dirW; var dIn = down - Vector3.Dot(down, nrm) * nrm;
                if (dIn.LengthSquared() < 1e-6f) continue;
                dIn = Vector3.Normalize(dIn);
                su += a * Vector3.Dot(G(du1, du2), dIn); sv += a * Vector3.Dot(G(dv1, dv2), dIn);
                area += a; vert += a * (1 - Math.Abs(nrm.Y));
            }
        }
        if (area <= 0) return (0, 0, false);
        return ((float)(su / area), (float)(sv / area), vert / area > 0.5);
    }

    // inject scroll anims for DObjs whose first texture is the given water image; returns count
    static int WaterScroll(JsonElement ws, HSD_JOBJ clone, List<HSD_JOBJ> tl, Dictionary<HSD_JOBJ, Matrix4x4> worlds,
        ref HSD_MatAnimJoint matClone, int waterSize)
    {
        // speeds in file units per frame; 1 texture repeat per loop so the wrap is seamless
        float fallSpeed = ws.TryGetProperty("fall_speed", out var fsp) ? fsp.GetSingle() : 3f;
        float poolSpeed = ws.TryGetProperty("pool_speed", out var psp) ? psp.GetSingle() : 0.4f;
        float fallSign = ws.TryGetProperty("flip", out var fl) && fl.GetBoolean() ? -1f : 1f;
        int Frames(float g, float speed) => Math.Clamp((int)MathF.Round(1f / Math.Max(1e-6f, Math.Abs(g) * speed)), 30, 20000);
        if (matClone == null) matClone = MirrorMJ(clone);
        var ml = DfsM(matClone);
        if (ml.Count != tl.Count) { Console.WriteLine($"  WARN water scroll: matanim tree {ml.Count} vs joints {tl.Count}"); return 0; }
        int n = 0;
        var seen = new HashSet<HSDStruct>();
        for (int j = 0; j < tl.Count; j++)
        {
            var jo = tl[j];
            if (jo.Dobj == null) continue;
            var dl = jo.Dobj.List;
            for (int k = 0; k < dl.Count; k++)
            {
                var t0 = dl[k].Mobj?.Textures;
                // Colosseum gives every TObj its own image header: match the water by shape instead (XLU, two layers, 128x128)
                if (t0?.ImageData == null || t0.Next == null || !dl[k].Mobj.RenderFlags.HasFlag(RENDER_MODE.XLU)) continue;
                if (t0.ImageData.Width != waterSize || t0.ImageData.Height != waterSize) continue;
                // make sure the per-DObj list reaches index k
                var mas = ml[j].MaterialAnimation?.List ?? new List<HSD_MatAnim>();
                while (mas.Count <= k) mas.Add(new HSD_MatAnim());
                for (int i = 0; i < mas.Count; i++) mas[i].Next = i + 1 < mas.Count ? mas[i + 1] : null;
                ml[j].MaterialAnimation = mas[0];
                // Colosseum's look: material blue with white caustic veins. Melee's BLEND at 1.0 replaces the colour with the
                // texture, and the second MODULATE layer darkens it; blend half way and (optionally) drop the second layer.
                var wm = dl[k].Mobj;
                if (ws.TryGetProperty("blend", out var wbl)) t0.Blending = wbl.GetSingle();
                if (ws.TryGetProperty("modulate", out var wmo) && wmo.GetBoolean())
                {
                    // material blue x caustic x caustic: saturated sheets with bright veins, like Colosseum's renders
                    int f = (int)t0.Flags;
                    if ((f & 0xF0000) == (3 << 16)) f = (f & ~0xF0000) | (4 << 16);
                    t0.Flags = (TOBJ_FLAGS)f;
                }
                if (ws.TryGetProperty("alpha", out var wal) && wm.Material != null) wm.Material.Alpha = wal.GetSingle();
                if (ws.TryGetProperty("color_scale", out var wcs) && wm.Material != null)
                {
                    var c = wm.Material.DiffuseColor; float q = wcs.GetSingle();
                    wm.Material.DiffuseColor = System.Drawing.Color.FromArgb(c.A, (int)(c.R * q), (int)(c.G * q), (int)(c.B * q));
                }
                if (ws.TryGetProperty("drop_tex1", out var wdt) && wdt.GetBoolean() && t0.Next != null)
                {
                    t0.Next = null;
                    wm.RenderFlags &= ~(RENDER_MODE.TEX1 | RENDER_MODE.TEX2 | RENDER_MODE.TEX3);
                }
                var (gu, gv, vertical) = UvFall(dl[k], worlds[jo], -Vector3.UnitY);
                if (!vertical) (gu, gv, _) = UvFall(dl[k], worlds[jo], Vector3.UnitX);
                bool useU = Math.Abs(gu) >= Math.Abs(gv);
                float g = useU ? gu : gv;
                HSD_TexAnim head = null, tail = null;
                int layer = 0;
                var info = new List<string>();
                foreach (var tt in t0.List)
                {
                    // pattern moves toward increasing uv when T grows (tobj.c: uv' = S R (uv - T)), i.e. down the fall
                    float sp = (vertical ? fallSpeed : poolSpeed) * (layer == 0 ? 1f : 0.6f);
                    int fr = Frames(g, sp);
                    float amt = Math.Sign(g == 0 ? 1 : g) * fallSign;
                    // the second layer of a pool drifts across the first
                    bool u2 = vertical ? useU : (layer == 0 ? useU : !useU);
                    var ao = ScrollAobj(fr, u2 ? amt : 0, u2 ? 0 : amt);
                    info.Add($"L{layer}:{(u2 ? "U" : "V")}{amt:+0;-0}/{fr}f");
                    var ta = new HSD_TexAnim { GXTexMapID = tt.TexMapID, AnimationObject = ao };
                    if (head == null) head = ta; else tail.Next = ta;
                    tail = ta; layer++;
                }
                Console.WriteLine($"    water j{j}:{k} {(vertical ? "fall" : "pool")} g={g:F5} {string.Join(" ", info)}");
                mas[k].TextureAnimation = head;
                n++;
            }
        }
        return n;
    }

    // ---------------------------------------------------------------- particle tracks out of the background groups
    static void StripPtcl(SBM_Map_Head head, SBM_Map_GOBJ[] groups, IEnumerable<int> gl)
    {
        foreach (var gi in gl)
        {
            if (groups[gi].JointAnimations == null) continue;
            int n = 0;
            foreach (var ja in groups[gi].JointAnimations.Array)
                foreach (var nd in DfsAJ(ja))
                {
                    if (nd.AOBJ?.FObjDesc == null) continue;
                    var keep = nd.AOBJ.FObjDesc.List.Where(t => t.JointTrackType != JointTrackType.HSD_A_J_PTCL).ToList();
                    n += nd.AOBJ.FObjDesc.List.Count - keep.Count;
                    for (int i = 0; i < keep.Count; i++) keep[i].Next = i + 1 < keep.Count ? keep[i + 1] : null;
                    nd.AOBJ.FObjDesc = keep.Count > 0 ? keep[0] : null;
                }
            Console.WriteLine($"group {gi}: dropped {n} particle tracks");
        }
    }

    // ---------------------------------------------------------------- the stage model
    static List<Vector2> EarClip(List<Vector2> poly)
    {
        // poly counter-clockwise; returns triangle vertex list
        var idx = Enumerable.Range(0, poly.Count).ToList();
        var outp = new List<Vector2>();
        float Cross(Vector2 a, Vector2 b, Vector2 c) => (b.X - a.X) * (c.Y - a.Y) - (b.Y - a.Y) * (c.X - a.X);
        bool Inside(Vector2 p, Vector2 a, Vector2 b, Vector2 c) => Cross(a, b, p) >= -1e-5f && Cross(b, c, p) >= -1e-5f && Cross(c, a, p) >= -1e-5f;
        int guard = 0;
        while (idx.Count > 3 && guard++ < 10000)
        {
            bool cut = false;
            for (int i = 0; i < idx.Count; i++)
            {
                var a = poly[idx[(i - 1 + idx.Count) % idx.Count]]; var b = poly[idx[i]]; var c = poly[idx[(i + 1) % idx.Count]];
                if (Cross(a, b, c) <= 1e-6f) continue;
                bool any = false;
                foreach (var q in idx) { var p = poly[q]; if (p == a || p == b || p == c) continue; if (Inside(p, a, b, c)) { any = true; break; } }
                if (any) continue;
                outp.Add(a); outp.Add(b); outp.Add(c);
                idx.RemoveAt(i); cut = true; break;
            }
            if (!cut) break;
        }
        if (idx.Count == 3) { outp.Add(poly[idx[0]]); outp.Add(poly[idx[1]]); outp.Add(poly[idx[2]]); }
        return outp;
    }

    static List<Vector2> ClipY(List<Vector2> poly, float y, bool keepAbove)
    {
        var o = new List<Vector2>();
        for (int i = 0; i < poly.Count; i++)
        {
            var a = poly[i]; var b = poly[(i + 1) % poly.Count];
            bool ia = keepAbove ? a.Y >= y : a.Y <= y, ib = keepAbove ? b.Y >= y : b.Y <= y;
            if (ia) o.Add(a);
            if (ia != ib) { float t = (y - a.Y) / (b.Y - a.Y); o.Add(new Vector2(a.X + (b.X - a.X) * t, y)); }
        }
        return o;
    }

    static void BuildBf(JsonElement bf, HSD_JOBJ groot, Dictionary<string, HSDRawFile> donorFiles,
        Dictionary<string, Dictionary<HSDStruct, HSDStruct>> memos)
    {
        var path = bf.GetProperty("file").GetString();
        if (!donorFiles.TryGetValue(path, out var df)) { df = ReadArchive(path); donorFiles[path] = df; memos[path] = new Dictionary<HSDStruct, HSDStruct>(); }
        var descs = Scene(df).JOBJDescs.Array;
        HSD_DOBJ SrcD(JsonElement e) => descs[e[0].GetInt32()].RootJoint.TreeList[e[1].GetInt32()].Dobj.List[e[2].GetInt32()];
        var tmpl = Copy(SrcD(bf.GetProperty("material")).Mobj, memos[path]);        // VERTEX | TEX0 unlit, atlas
        var atlasT = SrcD(bf.GetProperty("atlas")).Mobj.Textures;
        var wallT = SrcD(bf.GetProperty("wall_tex")).Mobj.Textures;
        int aw = atlasT.ImageData.Width; var apx = atlasT.GetDecodedImageData();
        int ww = wallT.ImageData.Width; var wpx = wallT.GetDecodedImageData();
        byte[] A(int x0, int y0, int x1, int y1, int w, int h) => CropResize(apx, aw, x0, y0, x1 - x0, y1 - y0, w, h);
        byte[] W(int x0, int y0, int x1, int y1, int w, int h) => CropResize(wpx, ww, x0, y0, x1 - x0, y1 - y0, w, h);
        const GXWrapMode REP = GXWrapMode.REPEAT, CLA = GXWrapMode.CLAMP, MIR = GXWrapMode.MIRROR;
        HSD_MOBJ M(byte[] px, int w, int h, GXWrapMode s, GXWrapMode t)
        {
            var tx = NewTobj(tmpl.Textures, px, w, h, s, t);
            tx.Flags = TOBJ_FLAGS.LIGHTMAP_DIFFUSE | TOBJ_FLAGS.COLORMAP_MODULATE; tx.Blending = 1; tx.TEV = null;
            tx.GXTexGenSrc = GXTexGenSrc.GX_TG_TEX0; tx.TexMapID = GXTexMapID.GX_TEXMAP0;
            var m = MobjWith(tmpl, tx);
            m.RenderFlags = RENDER_MODE.VERTEX | RENDER_MODE.TEX0 | RENDER_MODE.ALPHA_MAT;
            noBrighten.Add(m._s);
            return m;
        }
        JsonElement R(string k) => bf.GetProperty(k);
        int[] I4(string k) => R(k).EnumerateArray().Select(e => e.GetInt32()).ToArray();

        // ---- textures (pixel boxes in the lobby atlas / wall sheet come from the spec) ----
        var tile = I4("top_tile"); var med = I4("medallion"); var fr = I4("frieze"); var wb = I4("wall_box"); var pt = I4("plat_tile");
        // top: tiles with the walkway's blue-diamond medallion in the middle (512 x 256 over x +-85.5, z +-Z)
        var top = new byte[512 * 256 * 4];
        var tpx = A(tile[0], tile[1], tile[2], tile[3], 128, 128);
        for (int y = 0; y < 256; y++) for (int x = 0; x < 512; x++) for (int c = 0; c < 4; c++) top[(y * 512 + x) * 4 + c] = tpx[((y % 128) * 128 + (x % 128)) * 4 + c];
        int mw = R("medallion_px").GetInt32(), mh = mw * (med[3] - med[1]) / (med[2] - med[0]);
        var mpx = A(med[0], med[1], med[2], med[3], mw, mh);
        for (int y = 0; y < mh; y++) for (int x = 0; x < mw; x++)
        {
            int dx = 256 - mw / 2 + x, dy = 128 - mh / 2 + y;
            if (dx < 0 || dy < 0 || dx >= 512 || dy >= 256) continue;
            for (int c = 0; c < 4; c++) top[(dy * 512 + dx) * 4 + c] = mpx[(y * mw + x) * 4 + c];
        }
        var mTop = M(top, 512, 256, CLA, CLA);
        var mFrieze = M(A(fr[0], fr[1], fr[2], fr[3], 256, 128), 256, 128, REP, CLA);
        var mWall = M(Seamless(W(wb[0], wb[1], wb[2], wb[3], 256, 256), 256, 256, true, true), 256, 256, REP, REP);
        var mPlat = M(Seamless(A(pt[0], pt[1], pt[2], pt[3], 128, 128), 128, 128, true, true), 128, 128, REP, REP);
        var eb = bf.TryGetProperty("emblem_box", out var ebx) ? ebx.EnumerateArray().Select(e => e.GetInt32()).ToArray() : med;
        var mMed = M(A(eb[0], eb[1], eb[2], eb[3], 256, 256), 256, 256, CLA, CLA);

        float Z = R("depth").GetSingle();                 // front face at +Z, back at -Z
        float band = R("band").GetSingle();               // frieze lip height below the top
        float wallTile = R("wall_tile").GetSingle();      // world units per wall texture repeat
        float friezeLen = R("frieze_len").GetSingle();
        var Ld = Vector3.Normalize(new Vector3(-0.4f, 0.8f, 0.6f));
        float Sh(Vector3 n, float lo, float hi) => lo + (hi - lo) * Math.Max(0f, Vector3.Dot(Vector3.Normalize(n), Ld));
        GX_Vertex V(Vector3 p, Vector3 n, float shade, float u, float v) => new GX_Vertex
        {
            POS = new GXVector3(p.X, p.Y, p.Z), NRM = new GXVector3(n.X, n.Y, n.Z),
            CLR0 = new GXColor4(Math.Clamp(shade, 0, 1), Math.Clamp(shade, 0, 1), Math.Clamp(shade * 0.97f, 0, 1), 1), TEX0 = new GXVector2(u, v)
        };

        // collision outline, counter-clockwise when seen from the front (+z): left ledge, down the left underside, ..., top
        var right = new List<Vector2> { new(85.5f, 0), new(81.22f, -7.5f), new(44.5f, -22.5f), new(47.5f, -26.5f), new(41f, -31f), new(38f, -36f), new(36.5f, -43.5f), new(13f, -50f), new(12.89f, -39.07f) };
        var outline = new List<Vector2>();
        // CCW (y up, x right): start at top-left, go down the left side, across the bottom, up the right side, back along the top
        outline.Add(new(-85.5f, 0));
        for (int i = 1; i < right.Count; i++) outline.Add(new(-right[i].X, right[i].Y));
        for (int i = right.Count - 1; i >= 1; i--) outline.Add(right[i]);
        outline.Add(new(85.5f, 0));

        var tFront = new List<GX_Vertex>(); var tBand = new List<GX_Vertex>(); var tWall = new List<GX_Vertex>(); var tTop = new List<GX_Vertex>();
        var tPlat = new List<GX_Vertex>(); var tMed = new List<GX_Vertex>();
        float yMin = -50f;
        // front and back faces: frieze band above y=-band, block wall below
        foreach (var (z, nz) in new[] { (Z, 1f), (-Z, -1f) })
        {
            var body = ClipY(outline, -band, false);
            var tri = EarClip(body);
            for (int i = 0; i + 2 < tri.Count; i += 3)
            {
                var idx = nz > 0 ? new[] { 0, 1, 2 } : new[] { 0, 2, 1 };
                foreach (var k in idx)
                {
                    var q = tri[i + k];
                    float f = (q.Y + band) / (yMin + band);                 // 0 at the band, 1 at the bottom
                    tFront.Add(V(new(q.X, q.Y, z), new(0, 0, nz), 0.92f - 0.42f * f, q.X / wallTile, -q.Y / wallTile));
                }
            }
            var bp = ClipY(outline, -band, true);
            var btri = EarClip(bp);
            for (int i = 0; i + 2 < btri.Count; i += 3)
            {
                var idx = nz > 0 ? new[] { 0, 1, 2 } : new[] { 0, 2, 1 };
                foreach (var k in idx) { var q = btri[i + k]; tBand.Add(V(new(q.X, q.Y, z), new(0, 0, nz), 0.98f, q.X / friezeLen, -q.Y / band)); }
            }
        }
        // walls along the outline (not the top edge), split at the band line so the lip gets the frieze
        for (int i = 0; i < outline.Count; i++)
        {
            var a = outline[i]; var b = outline[(i + 1) % outline.Count];
            if (Math.Abs(a.Y) < 1e-4f && Math.Abs(b.Y) < 1e-4f) continue;          // the top edge
            var d = b - a; float len = d.Length();
            var n2 = Vector2.Normalize(new Vector2(d.Y, -d.X));                       // outward for a CCW outline
            var n = new Vector3(n2.X, n2.Y, 0);
            float shade = n2.Y < -0.5f ? 0.42f : Sh(n, 0.5f, 0.85f);
            var target = (n2.Y > -0.3f && Math.Max(a.Y, b.Y) > -band - 0.01f) ? tBand : tWall;
            int segs = Math.Max(1, (int)MathF.Ceiling(len / 10f));
            for (int s = 0; s < segs; s++)
            {
                var p0 = a + d * (s / (float)segs); var p1 = a + d * ((s + 1) / (float)segs);
                float s0 = (s / (float)segs) * len, s1 = ((s + 1) / (float)segs) * len;
                GX_Vertex Q(Vector2 p, float z, float sArc) => target == tBand
                    ? V(new(p.X, p.Y, z), n, 0.9f, (z + Z) / friezeLen, -p.Y / band)
                    : V(new(p.X, p.Y, z), n, shade, (z + Z) / wallTile, sArc / wallTile);
                // outward-facing winding (GX front faces are clockwise on screen)
                target.Add(Q(p0, Z, s0)); target.Add(Q(p1, -Z, s1)); target.Add(Q(p1, Z, s1));
                target.Add(Q(p0, Z, s0)); target.Add(Q(p0, -Z, s0)); target.Add(Q(p1, -Z, s1));
            }
        }
        // top: the floor slab with the medallion, y = 0
        {
            int nx = 12, nzs = 4;
            for (int i = 0; i < nx; i++) for (int k = 0; k < nzs; k++)
            {
                float x0 = -85.5f + 171f * i / nx, x1 = -85.5f + 171f * (i + 1) / nx, z0 = -Z + 2 * Z * k / nzs, z1 = -Z + 2 * Z * (k + 1) / nzs;
                GX_Vertex T(float x, float z) => V(new(x, 0, z), Vector3.UnitY, 1.0f, (x + 85.5f) / 171f, (z + Z) / (2 * Z));
                tTop.Add(T(x0, z0)); tTop.Add(T(x1, z0)); tTop.Add(T(x1, z1));
                tTop.Add(T(x0, z0)); tTop.Add(T(x1, z1)); tTop.Add(T(x0, z1));
            }
        }
        // front emblem: the blue diamond inlaid in the face, just proud of it
        {
            var em = R("emblem").EnumerateArray().Select(e => e.GetSingle()).ToArray();   // x half-width, y top, y bottom
            float hx = em[0], y0 = em[1], y1 = em[2], z = Z + 0.15f;
            GX_Vertex E(float x, float y, float u, float v) => V(new(x, y, z), Vector3.UnitZ, 0.95f, u, v);
            tMed.Add(E(-hx, y0, 0, 0)); tMed.Add(E(hx, y1, 1, 1)); tMed.Add(E(hx, y0, 1, 0));
            tMed.Add(E(-hx, y0, 0, 0)); tMed.Add(E(-hx, y1, 0, 1)); tMed.Add(E(hx, y1, 1, 1));
        }
        // platforms: slabs on the exact lines, chamfered underside
        float PZ = R("plat_depth").GetSingle(), PT = R("plat_thick").GetSingle();
        foreach (var (x0, x1, y) in new[] { (-72f, -25f, 34f), (25f, 72f, 34f), (-23.5f, 23.5f, 68f) })
        {
            float c = 1.6f;                                                           // chamfer inset at the bottom
            Vector3[] topR = { new(x0, y, -PZ), new(x1, y, -PZ), new(x1, y, PZ), new(x0, y, PZ) };
            Vector3[] midR = { new(x0, y - PT * 0.55f, -PZ), new(x1, y - PT * 0.55f, -PZ), new(x1, y - PT * 0.55f, PZ), new(x0, y - PT * 0.55f, PZ) };
            Vector3[] botR = { new(x0 + c, y - PT, -PZ + c), new(x1 - c, y - PT, -PZ + c), new(x1 - c, y - PT, PZ - c), new(x0 + c, y - PT, PZ - c) };
            // top
            GX_Vertex TP(Vector3 p) => V(p, Vector3.UnitY, 1.0f, p.X / 16f, p.Z / 16f);
            tPlat.Add(TP(topR[0])); tPlat.Add(TP(topR[1])); tPlat.Add(TP(topR[2])); tPlat.Add(TP(topR[0])); tPlat.Add(TP(topR[2])); tPlat.Add(TP(topR[3]));
            // bottom
            GX_Vertex BP(Vector3 p) => V(p, -Vector3.UnitY, 0.4f, p.X / 16f, p.Z / 16f);
            tPlat.Add(BP(botR[0])); tPlat.Add(BP(botR[2])); tPlat.Add(BP(botR[1])); tPlat.Add(BP(botR[0])); tPlat.Add(BP(botR[3])); tPlat.Add(BP(botR[2]));
            // sides: frieze band (top -> mid), chamfer (mid -> bottom)
            for (int e = 0; e < 4; e++)
            {
                int e1 = (e + 1) % 4;
                var nOut = Vector3.Normalize(Vector3.Cross(topR[e1] - topR[e], Vector3.UnitY));
                if (Vector3.Dot(nOut, (topR[e] + topR[e1]) / 2 - new Vector3((x0 + x1) / 2, y, 0)) < 0) nOut = -nOut;
                float L = (topR[e1] - topR[e]).Length();
                float sh = Sh(nOut, 0.6f, 0.95f);
                GX_Vertex F(Vector3 p, float u, float v) => V(p, nOut, sh, u, v);
                tBand.Add(F(topR[e], 0, 0)); tBand.Add(F(midR[e1], L / friezeLen, 1)); tBand.Add(F(topR[e1], L / friezeLen, 0));
                tBand.Add(F(topR[e], 0, 0)); tBand.Add(F(midR[e], 0, 1)); tBand.Add(F(midR[e1], L / friezeLen, 1));
                var nCh = Vector3.Normalize(nOut - Vector3.UnitY * 0.8f);
                GX_Vertex C(Vector3 p, float u, float v) => V(p, nCh, sh * 0.62f, u, v);
                tPlat.Add(C(midR[e], 0, 0)); tPlat.Add(C(botR[e1], L / 16f, 0.2f)); tPlat.Add(C(midR[e1], L / 16f, 0));
                tPlat.Add(C(midR[e], 0, 0)); tPlat.Add(C(botR[e], 0, 0.2f)); tPlat.Add(C(botR[e1], L / 16f, 0.2f));
            }
        }
        var meshes = new List<HSD_DOBJ> { MakeDobjCull(mTop, tTop), MakeDobjCull(mFrieze, tBand), MakeDobjCull(mWall, tFront), MakeDobjCull(mWall, tWall),
            MakeDobjCull(mPlat, tPlat), MakeDobjCull(mMed, tMed) };
        for (int i = 0; i < meshes.Count; i++) meshes[i].Next = i + 1 < meshes.Count ? meshes[i + 1] : null;
        Append(groot, new HSD_JOBJ { Flags = JOBJ_FLAG.OPA, SX = 1, SY = 1, SZ = 1, Dobj = meshes[0] });
        Console.WriteLine($"bf stage: top {tTop.Count / 3}, band {tBand.Count / 3}, faces {tFront.Count / 3}, walls {tWall.Count / 3}, platforms {tPlat.Count / 3} tris");
    }

    // MakeDobj with back-face culling (one-sided, like the rest of the stage geometry)
    static HSD_DOBJ MakeDobjCull(HSD_MOBJ m, List<GX_Vertex> tris)
    {
        var gen = new POBJ_Generator { CullMode = GenCullMode.None, VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
        var p = gen.CreatePOBJsFromTriangleList(tris, new[] { GXAttribName.GX_VA_POS, GXAttribName.GX_VA_NRM, GXAttribName.GX_VA_CLR0, GXAttribName.GX_VA_TEX0 }, null);
        gen.SaveChanges();
        return new HSD_DOBJ { Mobj = m, Pobj = p };
    }
}
