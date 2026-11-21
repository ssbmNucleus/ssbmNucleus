// Fountain of Dreams rebuilt from Realgam Colosseum textures: a goblet lathed on FoD's exact collision profile,
// a reflective field-pattern top (FoD's own mirror TObj, which grizumi.c requires), marble platforms on the
// moving platform joints, and copies of them in group 2 (the reflection-only group).
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
    static readonly HashSet<HSDStruct> noBrighten = new();
    static int recvVanilla, recvGroup;

    static void BuildFod(JsonElement fod, SBM_Map_Head head, SBM_Map_GOBJ[] groups,
        Dictionary<string, HSDRawFile> donorFiles, Dictionary<string, Dictionary<HSDStruct, HSDStruct>> memos)
    {
        // every picture is a spot in a Colosseum file, or (a string) a picture of the kind the "cs" step reads
        var path = fod.TryGetProperty("file", out var fe) ? fe.GetString() : null;
        HSDRawFile df = null;
        if (path != null && !donorFiles.TryGetValue(path, out df)) { df = ReadArchive(path); donorFiles[path] = df; memos[path] = new Dictionary<HSDStruct, HSDStruct>(); }
        var descs = df != null ? Scene(df).JOBJDescs.Array : null;
        HSD_TOBJ SrcT(JsonElement e) => descs[e[0].GetInt32()].RootJoint.TreeList[e[1].GetInt32()].Dobj.List[e[2].GetInt32()].Mobj.Textures.List[e[3].GetInt32()];
        HSD_MOBJ SrcM(JsonElement e) => descs[e[0].GetInt32()].RootJoint.TreeList[e[1].GetInt32()].Dobj.List[e[2].GetInt32()].Mobj;
        byte[] Px(JsonElement e, out int w, out int h)
        {
            if (e.ValueKind == JsonValueKind.String)
            {
                var img = File.ReadAllBytes(e.GetString());
                w = BitConverter.ToInt32(img, 0); h = BitConverter.ToInt32(img, 4);
                var o = new byte[w * h * 4];
                Buffer.BlockCopy(img, 8, o, 0, o.Length);
                return o;
            }
            var t = SrcT(e); w = t.ImageData.Width; h = t.ImageData.Height; return t.GetDecodedImageData();
        }

        HSD_MOBJ tmplM;
        if (df != null) tmplM = Copy(SrcM(fod.GetProperty("material")), memos[path]);
        else
        {
            tmplM = Copy(FirstMobj(ReadArchive(fod.GetProperty("template").GetString())), new Dictionary<HSDStruct, HSDStruct>());
            tmplM.Textures.Next = null; tmplM.Textures.TlutData = null; tmplM.PEDesc = null;
        }
        HSD_MOBJ Mat(byte[] px, int w, int h, GXWrapMode ws, GXWrapMode wt)
        {
            var t = NewTobj(tmplM.Textures, px, w, h, ws, wt);
            t.Flags = TOBJ_FLAGS.LIGHTMAP_DIFFUSE | TOBJ_FLAGS.COLORMAP_MODULATE;
            t.Blending = 1; t.TEV = null;
            t.RX = t.RY = t.RZ = 0; t.TX = t.TY = t.TZ = 0; t.SZ = 1;
            t.GXTexGenSrc = GXTexGenSrc.GX_TG_TEX0; t.TexMapID = GXTexMapID.GX_TEXMAP0;
            var m = MobjWith(tmplM, t);
            m.RenderFlags = RENDER_MODE.VERTEX | RENDER_MODE.TEX0;
            noBrighten.Add(m._s);
            return m;
        }
        byte[] Crop(JsonElement e, int dw, int dh)
        {
            var px = Px(e, out int w, out int h);
            if (e.ValueKind == JsonValueKind.String) return CropResize(px, w, 0, 0, w, h, dw, dh);
            int x0 = e.GetArrayLength() > 4 ? e[4].GetInt32() : 0, y0 = e.GetArrayLength() > 4 ? e[5].GetInt32() : 0;
            int x1 = e.GetArrayLength() > 4 ? e[6].GetInt32() : w, y1 = e.GetArrayLength() > 4 ? e[7].GetInt32() : h;
            return CropResize(px, w, x0, y0, x1 - x0, y1 - y0, dw, dh);
        }

        // ---- the field's quarter disc mirrored into one full disc texture ----
        var topE = fod.GetProperty("top");
        const int DS = 512;
        bool wholeDisc = topE.ValueKind == JsonValueKind.String;
        var qpx = Px(topE, out int qw, out int qh);
        float qc = wholeDisc ? 0 : topE[4].GetSingle(), qr = wholeDisc ? 0 : topE[5].GetSingle();      // quarter centre (both axes) and radius in pixels
        var disc = wholeDisc ? qpx : new byte[DS * DS * 4];
        if (!wholeDisc) for (int y = 0; y < DS; y++)
            for (int x = 0; x < DS; x++)
            {
                float dx = Math.Abs((x + 0.5f) / DS * 2 - 1), dy = Math.Abs((y + 0.5f) / DS * 2 - 1);
                float sx = qc - dx * qr, sy = qc - dy * qr;
                int ix = (int)MathF.Floor(sx), iy = (int)MathF.Floor(sy); float tx = sx - ix, ty = sy - iy;
                for (int c = 0; c < 4; c++)
                {
                    float P(int xx, int yy) => qpx[(Math.Clamp(yy, 0, qh - 1) * qw + Math.Clamp(xx, 0, qw - 1)) * 4 + c];
                    float v = P(ix, iy) * (1 - tx) * (1 - ty) + P(ix + 1, iy) * tx * (1 - ty) + P(ix, iy + 1) * (1 - tx) * ty + P(ix + 1, iy + 1) * tx * ty;
                    disc[(y * DS + x) * 4 + c] = (byte)Math.Clamp(c == 3 ? 255 : v, 0, 255);
                }
            }
        if (fod.TryGetProperty("rim_tint", out var rt))
        {
            // the battle field's red (left) / blue (right) sides on an annulus near the ledges (Astra's idea)
            float r0 = rt.GetProperty("r0").GetSingle() / 84.46f, r1 = rt.GetProperty("r1").GetSingle() / 84.46f;
            var red = rt.GetProperty("left").EnumerateArray().Select(e => e.GetSingle()).ToArray();
            var blue = rt.GetProperty("right").EnumerateArray().Select(e => e.GetSingle()).ToArray();
            for (int y = 0; y < DS; y++)
                for (int x = 0; x < DS; x++)
                {
                    float dx = (x + 0.5f) / DS * 2 - 1, dy = (y + 0.5f) / DS * 2 - 1, r = MathF.Sqrt(dx * dx + dy * dy);
                    float m = Math.Clamp(Math.Min(r - r0, r1 - r) / 0.015f, 0, 1);         // soft-edged band
                    m *= Math.Clamp(Math.Abs(dx) / 0.04f, 0, 1);                             // white seam at the centre line
                    if (m <= 0) continue;
                    var k = dx < 0 ? red : blue;
                    int i = (y * DS + x) * 4;   // BGRA
                    disc[i + 2] = (byte)(disc[i + 2] * (1 - m + m * k[0]));
                    disc[i + 1] = (byte)(disc[i + 1] * (1 - m + m * k[1]));
                    disc[i + 0] = (byte)(disc[i + 0] * (1 - m + m * k[2]));
                }
        }
        const GXWrapMode REP = GXWrapMode.REPEAT, CLA = GXWrapMode.CLAMP, MIR = GXWrapMode.MIRROR;
        var mTop = Mat(disc, DS, DS, CLA, CLA);
        var mWall = Mat(Crop(fod.GetProperty("wall"), 512, 256), 512, 256, REP, CLA);
        var mPanel = Mat(Crop(fod.GetProperty("panel"), 256, 256), 256, 256, MIR, MIR);
        var mWhite = Mat(Crop(fod.GetProperty("white"), 256, 64), 256, 64, REP, REP);
        var mGlass = Mat(Crop(fod.GetProperty("glass"), 128, 256), 128, 256, REP, REP);
        var mPlatTop = Mat(Crop(fod.GetProperty("plat_top"), 128, 128), 128, 128, MIR, MIR);
        var mPlatSide = Mat(Crop(fod.GetProperty("plat_side"), 128, 32), 128, 32, REP, CLA);

        var Ld = Vector3.Normalize(new Vector3(-0.35f, 0.85f, 0.4f));
        float Shade(Vector3 n) => 0.5f + 0.55f * Math.Max(0f, Vector3.Dot(Vector3.Normalize(n), Ld));
        GX_Vertex V(Vector3 p, Vector3 n, float u, float v) => new GX_Vertex
        {
            POS = new GXVector3(p.X, p.Y, p.Z), NRM = new GXVector3(n.X, n.Y, n.Z),
            CLR0 = new GXColor4(Shade(n), Shade(n), Shade(n), 1), TEX0 = new GXVector2(u, v), TEX1 = new GXVector2(u, v)
        };

        // ---- top disc on the collision floor: flat to 68.35, lip up to 0.83 by 71.45, flat to the ledges at 84.46 ----
        const float R = 84.46f; const int N = 48;
        float TopY(float r) => r <= 68.35f ? 0f : r >= 71.45f ? 0.83f : 0.83f * (r - 68.35f) / (71.45f - 68.35f);
        var rings = new[] { 0f, 8f, 18f, 30f, 42f, 54f, 64f, 68.35f, 71.45f, 76f, 80.5f, R };
        List<GX_Vertex> Disc(float lift)
        {
            var t = new List<GX_Vertex>();
            for (int i = 0; i + 1 < rings.Length; i++)
                for (int k = 0; k < N; k++)
                {
                    float a0 = k * MathF.Tau / N, a1 = (k + 1) * MathF.Tau / N;
                    Vector3 P(float r, float a) => new(r * MathF.Cos(a), TopY(r) + lift, r * MathF.Sin(a));
                    GX_Vertex Q(float r, float a) { var p = P(r, a); return V(p, Vector3.UnitY, 0.5f + p.X / (2 * R), 0.5f + p.Z / (2 * R)); }
                    Quad(t, Q(rings[i], a0), Q(rings[i], a1), Q(rings[i + 1], a1), Q(rings[i + 1], a0));
                }
            return t;
        }

        // ---- the goblet: FoD's collision profile (r, y) from the ledge down, lathed ----
        float baseY = fod.GetProperty("base_y").GetSingle();
        int tiles = fod.GetProperty("tiles").GetInt32();
        var bands = new List<(HSD_MOBJ m, (float r, float y)[] prof, float uTiles, float vLen)>
        {
            (mWhite, new[] { (R, 0.83f), (84.35f, -5.86f) }, 24, 6.7f),                                       // rim band
            (mWall, new[] { (84.35f, -5.86f), (79.31f, -19.55f), (75.83f, -26.07f), (73.24f, -34.82f), (69.21f, -42.94f), (63.47f, -49.98f), (54.91f, -55.88f) }, tiles, 0),
            (mPanel, new[] { (54.91f, -55.88f), (40.74f, -60.21f), (25.21f, -64.89f), (17.28f, -72.37f), (13.56f, -82.62f), (11.58f, -95.77f) }, 8, 40f),
            (mGlass, new[] { (11.58f, -95.77f), (11.25f, baseY + 34f) }, 2, 72f),
            (mWhite, new[] { (11.25f, baseY + 34f), (14f, baseY + 22f), (26f, baseY + 8f), (34f, baseY + 4f), (34f, baseY - 1f) }, 8, 20f),
        };
        var meshes = new List<HSD_DOBJ> { MakeDobjUV(mTop, Disc(0f)) };
        HSD_DOBJ Lathe(HSD_MOBJ m, (float r, float y)[] prof, float uTiles, float vLen, int N, float cx, float cz, float sx, float sz, float rot)
        {
            var t = new List<GX_Vertex>();
            // arc length along the profile and smooth per-point normals in the (r, y) plane
            var s = new float[prof.Length];
            for (int i = 1; i < prof.Length; i++) s[i] = s[i - 1] + MathF.Sqrt(MathF.Pow(prof[i].r - prof[i - 1].r, 2) + MathF.Pow(prof[i].y - prof[i - 1].y, 2));
            var nrm = new Vector2[prof.Length];
            for (int i = 0; i < prof.Length; i++)
            {
                var sum = Vector2.Zero;
                foreach (var (a, b) in new[] { (i - 1, i), (i, i + 1) })
                {
                    if (a < 0 || b >= prof.Length) continue;
                    var tg = Vector2.Normalize(new Vector2(prof[b].r - prof[a].r, prof[b].y - prof[a].y));
                    sum += new Vector2(-tg.Y, tg.X);
                }
                nrm[i] = Vector2.Normalize(sum);
            }
            float total = vLen > 0 ? vLen : s[^1];
            for (int i = 0; i + 1 < prof.Length; i++)
                for (int k = 0; k < N; k++)
                {
                    float a0 = k * MathF.Tau / N, a1 = (k + 1) * MathF.Tau / N;
                    GX_Vertex Q(int pi, float a, int kk)
                    {
                        float ar = a + rot;
                        var p = new Vector3(cx + sx * prof[pi].r * MathF.Cos(ar), prof[pi].y, cz + sz * prof[pi].r * MathF.Sin(ar));
                        // flat faces on a few-sided prism: face normals; smooth on a round lathe
                        float an = N <= 12 ? (k + 0.5f) * MathF.Tau / N + rot : ar;
                        var n = Vector3.Normalize(new Vector3(nrm[pi].X * MathF.Cos(an) / sx, nrm[pi].Y, nrm[pi].X * MathF.Sin(an) / sz));
                        return V(p, n, kk / (float)N * uTiles, s[pi] / total);
                    }
                    Quad(t, Q(i, a0, k), Q(i, a1, k + 1), Q(i + 1, a1, k + 1), Q(i + 1, a0, k));
                }
            return MakeDobjUV(m, t);
        }
        foreach (var (m, prof, uTiles, vLen) in bands) meshes.Add(Lathe(m, prof, uTiles, vLen, N, 0, 0, 1, 1, 0));
        // extra columns (e.g. the raised podium's pedestal): {tex, center [x,z], sx, sz, sides, rot, u_tiles, v_len, profile [[r,y]...]}
        if (fod.TryGetProperty("columns", out var cols))
            foreach (var c in cols.EnumerateArray())
            {
                var te = c.GetProperty("tex");
                var px = Px(te, out int cw, out int ch);
                if (te.ValueKind != JsonValueKind.String && te.GetArrayLength() > 4) { px = Crop(te, cw, ch); }
                var cm = Mat(px, cw, ch, REP, c.TryGetProperty("v_repeat", out var vr) && vr.GetBoolean() ? REP : CLA);
                var ctr = c.GetProperty("center");
                var prof = c.GetProperty("profile").EnumerateArray().Select(e => (e[0].GetSingle(), e[1].GetSingle())).ToArray();
                int sides = c.TryGetProperty("sides", out var sd) ? sd.GetInt32() : 8;
                meshes.Add(Lathe(cm, prof, c.GetProperty("u_tiles").GetSingle(), c.TryGetProperty("v_len", out var vl) ? vl.GetSingle() : 0,
                    sides, ctr[0].GetSingle(), ctr[1].GetSingle(), c.GetProperty("sx").GetSingle(), c.GetProperty("sz").GetSingle(),
                    (c.TryGetProperty("rot", out var ro) ? ro.GetSingle() : 0) * MathF.PI / 180f));
                if (c.TryGetProperty("cap_top", out var capv) && capv.GetBoolean())
                {
                    // flat lid on the top ring so the hollow prism never shows from above
                    float cx = ctr[0].GetSingle(), cz = ctr[1].GetSingle(), csx = c.GetProperty("sx").GetSingle(), csz = c.GetProperty("sz").GetSingle();
                    float rot0 = (c.TryGetProperty("rot", out var ro2) ? ro2.GetSingle() : 0) * MathF.PI / 180f;
                    var lid = new List<GX_Vertex>();
                    var ctrV = V(new Vector3(cx, prof[0].Item2, cz), Vector3.UnitY, 0.5f, 0.5f);
                    for (int k = 0; k < sides; k++)
                    {
                        Vector3 P(int kk) { float a2 = kk * MathF.Tau / sides + rot0; return new(cx + csx * prof[0].Item1 * MathF.Cos(a2), prof[0].Item2, cz + csz * prof[0].Item1 * MathF.Sin(a2)); }
                        GX_Vertex L(Vector3 p) => V(p, Vector3.UnitY, 0.5f + (p.X - cx) / (2 * csx), 0.5f + (p.Z - cz) / (2 * csx));
                        lid.Add(ctrV); lid.Add(L(P(k))); lid.Add(L(P(k + 1)));
                    }
                    meshes.Add(MakeDobjUV(cm, lid));
                }
            }
        for (int i = 0; i < meshes.Count; i++) meshes[i].Next = i + 1 < meshes.Count ? meshes[i + 1] : null;

        // ---- group 3: vanilla fountain out; keep the mirror material (joint refl) on a new disc ----
        var g3 = groups[3].RootNode; var t3 = g3.TreeList;
        int rj = fod.GetProperty("refl_joint").GetInt32();
        var reflD = t3[rj].Dobj;
        int van3 = recvGroup == 3 ? recvVanilla : t3.Count;   // group 3 holds grafts only when it is the receive group
        for (int j = 0; j < van3; j++) t3[j].Dobj = null;
        Append(g3, new HSD_JOBJ { Flags = JOBJ_FLAG.OPA, SX = 1, SY = 1, SZ = 1, Dobj = meshes[0] });

        var rm = reflD.Mobj;
        var reflTex = rm.Textures;                 // TEX0 = water ripple (vanilla), Next = the mirror image TObj
        var mirror = reflTex.Next;
        var ripple = NewTobj(reflTex, disc, DS, DS, CLA, CLA);
        ripple.Flags = reflTex.Flags; ripple.Blending = 1f; ripple.Next = mirror;
        ripple.GXTexGenSrc = reflTex.GXTexGenSrc; ripple.TexMapID = reflTex.TexMapID;
        rm.Textures = ripple;
        mirror.Blending = fod.TryGetProperty("mirror", out var mb) ? mb.GetSingle() : 0.35f;
        rm.Material.Alpha = fod.TryGetProperty("mirror_alpha", out var ma) ? ma.GetSingle() : 0.7f;
        noBrighten.Add(rm._s);
        var gen = new POBJ_Generator { CullMode = GenCullMode.None, VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
        var rp = gen.CreatePOBJsFromTriangleList(Disc(0.06f), new[] { GXAttribName.GX_VA_POS, GXAttribName.GX_VA_CLR0, GXAttribName.GX_VA_TEX0, GXAttribName.GX_VA_TEX1 }, null);
        gen.SaveChanges();
        reflD.Pobj = rp; reflD.Next = null;
        t3[rj].Dobj = reflD;
        t3[rj].Flags = (t3[rj].Flags & ~(JOBJ_FLAG.OPA | JOBJ_FLAG.TEXEDGE)) | JOBJ_FLAG.XLU;
        // the rest of the goblet on the same new joint as the opaque top
        meshes[0].Next = meshes.Count > 1 ? meshes[1] : null;

        // ---- marble platforms: local -19..19, top 1.5 (the collision lines), on group 3 joints 1-3 and group 2's copies ----
        var plat = new List<HSD_DOBJ>();
        {
            const float X = 19f, Z = 6.5f, T = 1.5f, B = -1.5f;
            var top = new List<GX_Vertex>(); var side = new List<GX_Vertex>();
            Vector3 P(float x, float y, float z) => new(x, y, z);
            for (int k = 0; k < 3; k++)
            {
                float x0 = -X + k * 2 * X / 3, x1 = -X + (k + 1) * 2 * X / 3;
                Quad(top, V(P(x0, T, -Z), Vector3.UnitY, 0, 0), V(P(x1, T, -Z), Vector3.UnitY, 1, 0), V(P(x1, T, Z), Vector3.UnitY, 1, 1), V(P(x0, T, Z), Vector3.UnitY, 0, 1));
                Quad(side, V(P(x0, T, Z), Vector3.UnitZ, 0, 0), V(P(x1, T, Z), Vector3.UnitZ, 1, 0), V(P(x1, B, Z), Vector3.UnitZ, 1, 1), V(P(x0, B, Z), Vector3.UnitZ, 0, 1));
                Quad(side, V(P(x1, T, -Z), -Vector3.UnitZ, 0, 0), V(P(x0, T, -Z), -Vector3.UnitZ, 1, 0), V(P(x0, B, -Z), -Vector3.UnitZ, 1, 1), V(P(x1, B, -Z), -Vector3.UnitZ, 0, 1));
                Quad(side, V(P(x0, B, Z), -Vector3.UnitY, 0, 0), V(P(x1, B, Z), -Vector3.UnitY, 1, 0), V(P(x1, B, -Z), -Vector3.UnitY, 1, 1), V(P(x0, B, -Z), -Vector3.UnitY, 0, 1));
            }
            Quad(side, V(P(X, T, Z), Vector3.UnitX, 0, 0), V(P(X, T, -Z), Vector3.UnitX, 0.34f, 0), V(P(X, B, -Z), Vector3.UnitX, 0.34f, 1), V(P(X, B, Z), Vector3.UnitX, 0, 1));
            Quad(side, V(P(-X, T, -Z), -Vector3.UnitX, 0, 0), V(P(-X, T, Z), -Vector3.UnitX, 0.34f, 0), V(P(-X, B, Z), -Vector3.UnitX, 0.34f, 1), V(P(-X, B, -Z), -Vector3.UnitX, 0, 1));
            plat.Add(MakeDobjUV(mPlatTop, top)); plat.Add(MakeDobjUV(mPlatSide, side));
            plat[0].Next = plat[1];
        }
        foreach (int j in new[] { 1, 2, 3 })
        {
            t3[j].Dobj = plat[0];
            t3[j].Flags = (t3[j].Flags & ~(JOBJ_FLAG.LIGHTING | JOBJ_FLAG.SPECULAR | JOBJ_FLAG.XLU)) | JOBJ_FLAG.OPA;
        }
        var t2 = groups[2].RootNode.TreeList;
        foreach (var jo in t2) jo.Dobj = null;
        foreach (int j in new[] { 1, 2, 3 }) { t2[j].Dobj = plat[0]; t2[j].Flags |= JOBJ_FLAG.OPA; }

        // vanilla material anims on joints that now carry new materials would retarget onto them
        if (groups[3].MaterialAnimations != null)
            foreach (var ma0 in groups[3].MaterialAnimations.Array)
            {
                if (ma0 == null) continue;
                var ml = DfsM(ma0);
                foreach (int j in new[] { 1, 2, 3, rj }) if (j < ml.Count) ml[j].MaterialAnimation = null;
            }
        // the water-column platform model fires particle tracks (spray, a long jet streak): drop them with the column
        int ptcl = 0;
        if (fod.TryGetProperty("drop_platform_ptcl", out var dpp) && dpp.GetBoolean() && groups[4].JointAnimations != null)
            foreach (var ja in groups[4].JointAnimations.Array)
                foreach (var n in DfsAJ(ja))
                {
                    if (n.AOBJ?.FObjDesc == null) continue;
                    var keep = n.AOBJ.FObjDesc.List.Where(t => t.JointTrackType != JointTrackType.HSD_A_J_PTCL && t.JointTrackType != JointTrackType.HSD_A_J_BRANCH).ToList();
                    ptcl += n.AOBJ.FObjDesc.List.Count - keep.Count;
                    for (int i = 0; i < keep.Count; i++) keep[i].Next = i + 1 < keep.Count ? keep[i + 1] : null;
                    n.AOBJ.FObjDesc = keep.Count > 0 ? keep[0] : null;
                }
        if (ptcl > 0) Console.WriteLine($"fod: dropped {ptcl} particle tracks from the platform model");
        Console.WriteLine($"fod: goblet {meshes.Count} meshes, mirror on joint {rj}, platforms on g3 j1-3 + g2 j1-3");
    }

    // like MakeDobj, with TEX1 too when the material has two layers
    static HSD_DOBJ MakeDobjUV(HSD_MOBJ m, List<GX_Vertex> tris)
    {
        var gen = new POBJ_Generator { CullMode = GenCullMode.None, VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
        var p = gen.CreatePOBJsFromTriangleList(tris, new[] { GXAttribName.GX_VA_POS, GXAttribName.GX_VA_NRM, GXAttribName.GX_VA_CLR0, GXAttribName.GX_VA_TEX0 }, null);
        gen.SaveChanges();
        return new HSD_DOBJ { Mobj = m, Pobj = p };
    }
}
