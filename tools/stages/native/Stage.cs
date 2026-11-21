// Island builder (Agate cliff chunk on Dream Land's collision), texture tiles cut from the atlas,
// and the group animation tree that carries Agate's ambient anims + the characters' idle loops.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.GX;
using HSDRaw.Tools;

static partial class Program
{
    // ---- tree walks in HSDRaw TreeList order (pre-order, child before sibling) ----
    static List<HSD_JOBJ> DfsJ(HSD_JOBJ r)
    {
        var l = new List<HSD_JOBJ>();
        void V(HSD_JOBJ n) { for (var c = n; c != null; c = c.Next) { l.Add(c); if (c.Child != null) V(c.Child); } }
        V(r);
        return l;
    }

    static List<HSD_MatAnimJoint> DfsM(HSD_MatAnimJoint r)
    {
        var l = new List<HSD_MatAnimJoint>();
        void V(HSD_MatAnimJoint n) { for (var c = n; c != null; c = c.Next) { l.Add(c); if (c.Child != null) V(c.Child); } }
        V(r);
        return l;
    }

    static void SetLoop(HSD_AnimJoint a)
    {
        for (var c = a; c != null; c = c.Next)
        {
            if (c.AOBJ != null) c.AOBJ.Flags |= AOBJ_Flags.ANIM_LOOP;
            if (c.Child != null) SetLoop(c.Child);
        }
    }

    static void SetLoop(HSD_MatAnimJoint a)
    {
        for (var c = a; c != null; c = c.Next)
        {
            for (var m = c.MaterialAnimation; m != null; m = m.Next)
            {
                if (m.AnimationObject != null) m.AnimationObject.Flags |= AOBJ_Flags.ANIM_LOOP;
                for (var t = m.TextureAnimation; t != null; t = t.Next)
                    if (t.AnimationObject != null) t.AnimationObject.Flags |= AOBJ_Flags.ANIM_LOOP;
            }
            if (c.Child != null) SetLoop(c.Child);
        }
    }

    // drop translate tracks (types 5..7) so a cutscene flight path becomes hovering in place
    static void StripTranslation(HSD_AnimJoint a)
    {
        for (var c = a; c != null; c = c.Next)
        {
            var ao = c.AOBJ;
            if (ao?.FObjDesc != null)
            {
                var keep = ao.FObjDesc.List.Where(f => f.JointTrackType != JointTrackType.HSD_A_J_TRAX && f.JointTrackType != JointTrackType.HSD_A_J_TRAY && f.JointTrackType != JointTrackType.HSD_A_J_TRAZ).ToList();
                for (int i = 0; i < keep.Count; i++) keep[i].Next = i + 1 < keep.Count ? keep[i + 1] : null;
                ao.FObjDesc = keep.Count > 0 ? keep[0] : null;
            }
            if (c.Child != null) StripTranslation(c.Child);
        }
    }

    static int VertCount(HSD_DOBJ d) => d.Pobj == null ? 0 : d.Pobj.List.Sum(p => p.ToDisplayList().Vertices.Count);

    static HSD_AnimJoint MirrorA(HSD_JOBJ j, Dictionary<HSD_JOBJ, HSD_AnimJoint> sub)
    {
        if (j == null) return null;
        var n = new HSD_AnimJoint();
        if (pathAobjs.TryGetValue(j, out var ao)) n.AOBJ = ao;
        n.Child = sub.TryGetValue(j, out var a) ? a : MirrorA(j.Child, sub);
        n.Next = MirrorA(j.Next, sub);
        return n;
    }

    static HSD_MatAnimJoint MirrorM(HSD_JOBJ j, Dictionary<HSD_JOBJ, HSD_MatAnimJoint> sub)
    {
        if (j == null) return null;
        var n = new HSD_MatAnimJoint();
        n.Child = sub.TryGetValue(j, out var a) ? a : MirrorM(j.Child, sub);
        n.Next = MirrorM(j.Next, sub);
        return n;
    }

    // ---- textures ----
    static byte[] CropResize(byte[] src, int sw, int x0, int y0, int cw, int ch, int dw, int dh)
    {
        var dst = new byte[dw * dh * 4];
        for (int y = 0; y < dh; y++)
            for (int x = 0; x < dw; x++)
            {
                float fx = x0 + (x + 0.5f) * cw / dw - 0.5f, fy = y0 + (y + 0.5f) * ch / dh - 0.5f;
                int ix = (int)MathF.Floor(fx), iy = (int)MathF.Floor(fy);
                float tx = fx - ix, ty = fy - iy;
                for (int c = 0; c < 4; c++)
                {
                    float P(int xx, int yy)
                    {
                        xx = Math.Clamp(xx, x0, x0 + cw - 1); yy = Math.Clamp(yy, y0, y0 + ch - 1);
                        return src[(yy * sw + xx) * 4 + c];
                    }
                    float v = P(ix, iy) * (1 - tx) * (1 - ty) + P(ix + 1, iy) * tx * (1 - ty) + P(ix, iy + 1) * (1 - tx) * ty + P(ix + 1, iy + 1) * tx * ty;
                    dst[(y * dw + x) * 4 + c] = (byte)Math.Clamp(v, 0, 255);
                }
            }
        return dst;
    }

    // Blend with a half-shifted copy so the tile wraps without a seam on the chosen axes.
    static byte[] Seamless(byte[] s, int w, int h, bool horiz, bool vert)
    {
        var o = (byte[])s.Clone();
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
            {
                float mx = horiz ? Math.Min(x, w - 1 - x) / (w / 2f) : 1f;
                float my = vert ? Math.Min(y, h - 1 - y) / (h / 2f) : 1f;
                float m = Math.Clamp(Math.Min(mx, my) * 1.6f, 0, 1);
                int sx = horiz ? (x + w / 2) % w : x, sy = vert ? (y + h / 2) % h : y;
                for (int c = 0; c < 4; c++)
                    o[(y * w + x) * 4 + c] = (byte)(s[(y * w + x) * 4 + c] * m + s[(sy * w + sx) * 4 + c] * (1 - m));
            }
        return o;
    }

    static byte[] Half(byte[] s, int w, int h)
    {
        var o = new byte[(w / 2) * (h / 2) * 4];
        for (int y = 0; y < h / 2; y++)
            for (int x = 0; x < w / 2; x++)
                for (int c = 0; c < 4; c++)
                    o[(y * (w / 2) + x) * 4 + c] = (byte)((s[((2 * y) * w + 2 * x) * 4 + c] + s[((2 * y) * w + 2 * x + 1) * 4 + c]
                        + s[((2 * y + 1) * w + 2 * x) * 4 + c] + s[((2 * y + 1) * w + 2 * x + 1) * 4 + c]) / 4);
        return o;
    }

    static HSD_TOBJ NewTobj(HSD_TOBJ template, byte[] px, int w, int h, GXWrapMode wrapS, GXWrapMode wrapT)
    {
        var t = new HSD_TOBJ { _s = new HSDStruct((byte[])template._s.GetData().Clone()) };
        foreach (var r in template._s.References) t._s.References[r.Key] = r.Value;
        t.Next = null;
        t.TlutData = null;
        // full mip chain down to 8x8, CMPR per level, concatenated
        var data = new List<byte>(); int levels = 0; int lw = w, lh = h; var cur = px;
        while (true)
        {
            data.AddRange(HSDRaw.Tools.GXImageConverter.ToCMP(cur, lw, lh)); levels++;
            if (lw <= 8 || lh <= 8) break;
            cur = Half(cur, lw, lh); lw /= 2; lh /= 2;
        }
        t.ImageData = new HSD_Image();
        t.ImageData.ImageData = data.ToArray();
        t.ImageData.Width = (short)w; t.ImageData.Height = (short)h; t.ImageData.Format = GXTexFmt.CMP;
        t.ImageData.MipMap = levels > 1 ? 1 : 0; t.ImageData.MinLOD = 0; t.ImageData.MaxLOD = levels - 1;
        t.LOD = new HSD_TOBJ_LOD { MinFilter = GXTexFilter.GX_LIN_MIP_LIN, Bias = 0, BiasClamp = false, EnableEdgeLOD = true };
        t.WrapS = wrapS; t.WrapT = wrapT;
        t.RepeatS = 1; t.RepeatT = 1; t.SX = 1; t.SY = 1;
        return t;
    }

    static HSD_MOBJ MobjWith(HSD_MOBJ template, HSD_TOBJ tex)
    {
        var m = new HSD_MOBJ { _s = new HSDStruct((byte[])template._s.GetData().Clone()) };
        foreach (var r in template._s.References) m._s.References[r.Key] = r.Value;
        m.Textures = tex;
        return m;
    }

    static HSD_DOBJ MakeDobj(HSD_MOBJ m, List<GX_Vertex> tris)
    {
        var gen = new POBJ_Generator { CullMode = GenCullMode.None, VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
        var p = gen.CreatePOBJsFromTriangleList(tris,
            new[] { GXAttribName.GX_VA_POS, GXAttribName.GX_VA_NRM, GXAttribName.GX_VA_CLR0, GXAttribName.GX_VA_TEX0 }, null);
        gen.SaveChanges();
        return new HSD_DOBJ { Mobj = m, Pobj = p };
    }

    static float islandShade = 1f;   // island vertex shading scale (0.66 when baked lighting is shown x2)
    static GX_Vertex Vx(Vector3 p, Vector3 n, float shade, float u, float v) => new GX_Vertex
    {
        POS = new GXVector3(p.X, p.Y, p.Z), NRM = new GXVector3(n.X, n.Y, n.Z),
        CLR0 = new GXColor4(Math.Min(1f, shade * islandShade), Math.Min(1f, shade * islandShade), Math.Min(1f, shade * islandShade), 1), TEX0 = new GXVector2(u, v)
    };

    static void Quad(List<GX_Vertex> t, GX_Vertex a, GX_Vertex b, GX_Vertex c, GX_Vertex d)
    {
        t.Add(a); t.Add(b); t.Add(c); t.Add(a); t.Add(c); t.Add(d);
    }

    // Dream Land's collision: floor y=0 for |x|<=77.27, walls down to a flat underside at -35.76.
    static float Bot(float x)
    {
        x = Math.Abs(x);
        if (x <= 65.76f) return -35.76f;
        if (x <= 76.34f) return -35.76f + (x - 65.76f) / (76.34f - 65.76f) * (35.76f - 11.04f);
        return -11.04f + (Math.Min(x, 77.27f) - 76.34f) / (77.27f - 76.34f) * 11.04f;
    }

    static void BuildIsland2(JsonElement isl, HSD_JOBJ groot, Dictionary<string, HSDRawFile> donorFiles,
        Dictionary<string, Dictionary<HSDStruct, HSDStruct>> memos)
    {
        var mfile = isl.GetProperty("file").GetString();
        int mdesc = isl.GetProperty("desc").GetInt32(), mj = isl.GetProperty("joint").GetInt32();
        var srcJ = Scene(donorFiles[mfile]).JOBJDescs[mdesc].RootJoint.TreeList[mj];
        var atlasMobj = Copy(srcJ.Dobj.Mobj, memos[mfile]);          // same struct the village uses: one atlas
        var atlasTex = atlasMobj.Textures;
        int aw = atlasTex.ImageData.Width, ah = atlasTex.ImageData.Height;
        var px = atlasTex.GetDecodedImageData();
        byte[] Tile(int x0, int y0, int x1, int y1, int w, int h) => CropResize(px, aw, x0, y0, x1 - x0, y1 - y0, w, h);
        const GXWrapMode MIR = GXWrapMode.MIRROR, CLA = GXWrapMode.CLAMP;
        var mGrass = MobjWith(atlasMobj, NewTobj(atlasTex, Seamless(Tile(470, 8, 935, 152, 256, 128), 256, 128, true, true), 256, 128, GXWrapMode.REPEAT, GXWrapMode.REPEAT));
        var mCliff = MobjWith(atlasMobj, NewTobj(atlasTex, Tile(2, 250, 250, 665, 256, 512), 256, 512, MIR, CLA));
        var mRock = MobjWith(atlasMobj, NewTobj(atlasTex, Tile(2, 470, 250, 668, 128, 128), 128, 128, MIR, MIR));
        islandShade = isl.TryGetProperty("shade", out var shv) ? shv.GetSingle() : 1f;
        var rng = new Random(isl.TryGetProperty("seed", out var sd) ? sd.GetInt32() : 7);
        float Rnd() => (float)rng.NextDouble();

        // ---- rim (top outline, x/z): ledges stay at x=+-77.27; front corners rounded in plan; rounded back holds the tree ----
        const float L = 77.27f, F = 28f, SB = -30f, RC = 8f;
        var rim = new List<Vector2>();
        void Seg(Vector2 a, Vector2 b, float step, Func<Vector2, Vector2> f = null)
        {
            int n = Math.Max(1, (int)MathF.Ceiling(Vector2.Distance(a, b) / step));
            for (int i = 0; i < n; i++) { var p = Vector2.Lerp(a, b, i / (float)n); rim.Add(f == null ? p : f(p)); }
        }
        void Arc(Vector2 c, float a0, float a1, int n) { for (int i = 0; i < n; i++) { float t = a0 + (a1 - a0) * i / n; rim.Add(c + RC * new Vector2(MathF.Cos(t), MathF.Sin(t))); } }
        Seg(new(-L + RC, F), new(L - RC, F), 6f, p => new(p.X, F + 1.2f * MathF.Sin(p.X * 0.11f) + 0.6f * MathF.Sin(p.X * 0.37f + 1)));
        Arc(new(L - RC, F - RC), MathF.PI / 2, 0, 4);
        Seg(new(L, F - RC), new(L, SB), 6f);
        var ctrl = new List<Vector2> { new(L, SB), new(L, SB), new(73, -58), new(55, -86), new(28, -104), new(0, -111), new(-28, -104), new(-55, -86), new(-73, -58), new(-L, SB), new(-L, SB) };
        for (int i = 1; i + 2 < ctrl.Count; i++)
        {
            Vector2 p0 = ctrl[i - 1], p1 = ctrl[i], p2 = ctrl[i + 1], p3 = ctrl[i + 2];
            int n = Math.Max(1, (int)MathF.Ceiling(Vector2.Distance(p1, p2) / 6f));
            for (int k = 0; k < n; k++)
            {
                float t = k / (float)n, t2 = t * t, t3 = t2 * t;
                var q = 0.5f * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
                if (i > 1 && i + 2 < ctrl.Count - 1) q += Vector2.Normalize(q - new Vector2(0, -40)) * 1.6f * MathF.Sin(q.X * 0.21f + q.Y * 0.13f);
                rim.Add(q);
            }
        }
        Seg(new(-L, SB), new(-L, F - RC), 6f);
        Arc(new(-L + RC, F - RC), MathF.PI, MathF.PI / 2, 4);
        int N = rim.Count;
        var c0 = new Vector2(0, -38);
        var nrm = new Vector2[N];
        for (int i = 0; i < N; i++)
        {
            var tng = rim[(i + 1) % N] - rim[(i - 1 + N) % N];
            var n = Vector2.Normalize(new Vector2(tng.Y, -tng.X));
            if (Vector2.Dot(n, rim[i] - c0) < 0) n = -n;
            nrm[i] = n;
        }
        var arc = new float[N + 1];
        for (int i = 0; i < N; i++) arc[i + 1] = arc[i] + Vector2.Distance(rim[i], rim[(i + 1) % N]);

        // smooth rock noise (no per-vertex jitter): bulges and strata that read as one cliff
        float p1n = Rnd() * 6.28f, p2n = Rnd() * 6.28f, p3n = Rnd() * 6.28f, p4n = Rnd() * 6.28f, p5n = Rnd() * 6.28f;
        float Nz(float sArc, float y) => 0.5f * MathF.Sin(sArc * 0.19f + p1n) * MathF.Cos(y * 0.31f + p2n)
                                        + 0.3f * MathF.Sin(sArc * 0.47f + p3n + y * 0.13f)
                                        + 0.2f * MathF.Sin(sArc * 1.1f + p4n) * MathF.Sin(y * 0.9f + p5n);

        // ---- cliff walls: grassy shoulder rolling over the rim, bulging rock, taper toward the bottom ----
        const int R = 8;
        var wall = new List<GX_Vertex>();
        var wp = new Vector3[N, R + 1];
        var wf = new float[N, R + 1];
        for (int i = 0; i < N; i++)
        {
            float hb = -Bot(rim[i].X);
            if (hb > 20) hb -= 2.4f * (0.5f + 0.5f * MathF.Sin(arc[i] * 0.33f + p5n));      // uneven bottom edge (only ever higher)
            bool side = MathF.Abs(nrm[i].X) > 0.8f;                                          // under the ledges: never stick out
            for (int k = 0; k <= R; k++)
            {
                float f = k / (float)R;
                float y = -hb * f;
                float off = 1.5f * MathF.Sin(MathF.PI * Math.Min(f / 0.28f, 1f))             // shoulder
                          - 5.5f * MathF.Pow(f, 1.5f)                                         // taper
                          + 1.4f * Nz(arc[i], y) * Math.Clamp(f * 4f, 0f, 1f);                // rock
                if (side) off = Math.Min(off, 0f);
                var q = rim[i] + nrm[i] * off;
                wp[i, k] = new Vector3(q.X, y, q.Y);
                wf[i, k] = f;
            }
        }
        for (int i = 0; i < N; i++)
        {
            int j = (i + 1) % N;
            float u0 = arc[i] / 42f, u1 = arc[i + 1] / 42f;
            for (int k = 0; k < R; k++)
            {
                GX_Vertex W(int ii, int kk, float u)
                {
                    var p = wp[ii, kk]; float f = wf[ii, kk];
                    float shade = 1.0f - 0.55f * f + 0.06f * Nz(arc[ii] * 1.7f, p.Y * 1.3f);
                    var n3 = new Vector3(nrm[ii].X, 0.5f - f, nrm[ii].Y);                     // up-facing at the shoulder, down at the bottom
                    return Vx(p, Vector3.Normalize(n3), shade, u, Math.Min(0.985f, 0.01f + f * 0.97f));
                }
                Quad(wall, W(i, k, u0), W(j, k, u1), W(j, k + 1, u1), W(i, k + 1, u0));
            }
        }

        // ---- grass top: flat on the collision, even shading (no rings), meets the wall's grassy shoulder at the rim ----
        const int RT = 3;
        var top = new List<GX_Vertex>();
        GX_Vertex T(Vector2 p) => Vx(new Vector3(p.X, 0.01f, p.Y), Vector3.UnitY, 1.0f + 0.05f * Nz(p.X * 0.7f, p.Y * 0.7f), p.X / 64f, p.Y / 48f);
        for (int i = 0; i < N; i++)
        {
            int j = (i + 1) % N;
            for (int r = 0; r < RT; r++)
            {
                float a = r / (float)RT, b = (r + 1) / (float)RT;
                var pa = c0 + (rim[i] - c0) * a; var pb = c0 + (rim[j] - c0) * a;
                var qa = c0 + (rim[i] - c0) * b; var qb = c0 + (rim[j] - c0) * b;
                if (r == 0) { top.Add(T(c0)); top.Add(T(qa)); top.Add(T(qb)); }
                else Quad(top, T(pa), T(pb), T(qb), T(qa));
            }
        }

        // ---- underside: closes the chunk at the wall bottoms ----
        const int RU = 2;
        var under = new List<GX_Vertex>();
        var cU = new Vector2(c0.X, c0.Y);
        for (int i = 0; i < N; i++)
        {
            int j = (i + 1) % N;
            var bi = new Vector2(wp[i, R].X, wp[i, R].Z); var bj = new Vector2(wp[j, R].X, wp[j, R].Z);
            float yi = wp[i, R].Y, yj = wp[j, R].Y;
            GX_Vertex U(Vector2 p, float a, float yEdge) => Vx(new Vector3(p.X, Bot(p.X) * (1 - a) + yEdge * a, p.Y), -Vector3.UnitY, 0.34f, p.X / 22f, p.Y / 22f);
            for (int r = 0; r < RU; r++)
            {
                float a = r / (float)RU, b = (r + 1) / (float)RU;
                var pa = cU + (bi - cU) * a; var pb = cU + (bj - cU) * a;
                var qa = cU + (bi - cU) * b; var qb = cU + (bj - cU) * b;
                if (r == 0) { under.Add(U(cU, 0, yi)); under.Add(U(qa, b, yi)); under.Add(U(qb, b, yj)); }
                else Quad(under, U(pa, a, yi), U(pb, a, yj), U(qb, b, yj), U(qa, b, yi));
            }
        }

        // ---- white roots hanging under the chunk (Agate's bark from the atlas) ----
        var roots = new List<GX_Vertex>();
        bool Inside(Vector2 p)
        {
            bool c = false;
            for (int i = 0, j = N - 1; i < N; j = i++)
                if (((rim[i].Y > p.Y) != (rim[j].Y > p.Y)) && (p.X < (rim[j].X - rim[i].X) * (p.Y - rim[i].Y) / (rim[j].Y - rim[i].Y) + rim[i].X)) c = !c;
            return c;
        }
        int nRoots = isl.TryGetProperty("roots", out var nr) ? nr.GetInt32() : 9;
        const float BX0 = 258 / 1024f, BX1 = 380 / 1024f, BY0 = 388 / 1024f, BY1 = 560 / 1024f;
        for (int rI = 0, tries = 0; rI < nRoots && tries < 400; tries++)
        {
            var s = new Vector2((Rnd() - 0.5f) * 116f, -78f + Rnd() * 98f);
            if (!Inside(s) || Math.Abs(s.X) > 60) continue;
            rI++;
            float len = 10f + Rnd() * 24f, r0 = 1.3f + Rnd() * 1.1f, ph = Rnd() * 6.28f, sx = (Rnd() - 0.5f) * 5f, sz = (Rnd() - 0.5f) * 4f;
            const int SEG = 5, SIDES = 5;
            Vector3 Path(float t) => new Vector3(s.X + sx * MathF.Sin(t * 2.4f + ph) * t, Bot(s.X) + 0.8f - len * t, s.Y + sz * MathF.Cos(t * 2f + ph) * t);
            for (int g = 0; g < SEG; g++)
            {
                float t0 = g / (float)SEG, t1 = (g + 1) / (float)SEG;
                Vector3 a0 = Path(t0), a1 = Path(t1);
                float ra = r0 * MathF.Pow(1 - t0, 0.8f) + 0.2f, rb = r0 * MathF.Pow(1 - t1, 0.8f) + 0.2f;
                for (int k = 0; k < SIDES; k++)
                {
                    float q0 = k * MathF.Tau / SIDES, q1 = (k + 1) * MathF.Tau / SIDES;
                    Vector3 d0 = new(MathF.Cos(q0), 0, MathF.Sin(q0)), d1 = new(MathF.Cos(q1), 0, MathF.Sin(q1));
                    float uu0 = BX0 + (BX1 - BX0) * k / SIDES, uu1 = BX0 + (BX1 - BX0) * (k + 1) / SIDES;
                    float vv0 = BY0 + (BY1 - BY0) * t0, vv1 = BY0 + (BY1 - BY0) * t1;
                    float s0 = 0.78f - 0.25f * t0, s1 = 0.78f - 0.25f * t1;
                    Quad(roots, Vx(a0 + d0 * ra, d0, s0, uu0, vv0), Vx(a0 + d1 * ra, d1, s0, uu1, vv0),
                        Vx(a1 + d1 * rb, d1, s1, uu1, vv1), Vx(a1 + d0 * rb, d0, s1, uu0, vv1));
                }
            }
        }

        // ---- plank platforms on the exact collision lines, boards running front to back ----
        const float PX0 = 517 / 1024f, PX1 = 636 / 1024f, PY0 = 460 / 1024f, PY1 = 768 / 1024f;
        foreach (var (x0, x1, y) in new[] { (-61.39f, -31.73f, 30.14f), (31.70f, 63.07f, 30.24f), (-19.02f, 19.02f, 51.43f) })
        {
            const float TH = 2.6f, ZD = 9f;
            int n = Math.Max(1, (int)MathF.Round((x1 - x0) / 6.5f));
            for (int k = 0; k < n; k++)
            {
                float xa = x0 + (x1 - x0) * k / n, xb = x0 + (x1 - x0) * (k + 1) / n;
                Quad(roots, Vx(new(xa, y, -ZD), Vector3.UnitY, 0.88f, PX0, PY0), Vx(new(xb, y, -ZD), Vector3.UnitY, 0.88f, PX1, PY0),
                    Vx(new(xb, y, ZD), Vector3.UnitY, 0.88f, PX1, PY1), Vx(new(xa, y, ZD), Vector3.UnitY, 0.88f, PX0, PY1));
                Quad(roots, Vx(new(xa, y - TH, -ZD), -Vector3.UnitY, 0.45f, PX0, PY0), Vx(new(xb, y - TH, -ZD), -Vector3.UnitY, 0.45f, PX1, PY0),
                    Vx(new(xb, y - TH, ZD), -Vector3.UnitY, 0.45f, PX1, PY1), Vx(new(xa, y - TH, ZD), -Vector3.UnitY, 0.45f, PX0, PY1));
                Quad(roots, Vx(new(xa, y, ZD), Vector3.UnitZ, 0.72f, PX0, PY1 - 0.02f), Vx(new(xb, y, ZD), Vector3.UnitZ, 0.72f, PX1, PY1 - 0.02f),
                    Vx(new(xb, y - TH, ZD), Vector3.UnitZ, 0.6f, PX1, PY1), Vx(new(xa, y - TH, ZD), Vector3.UnitZ, 0.6f, PX0, PY1));
                Quad(roots, Vx(new(xa, y, -ZD), -Vector3.UnitZ, 0.6f, PX0, PY0), Vx(new(xb, y, -ZD), -Vector3.UnitZ, 0.6f, PX1, PY0),
                    Vx(new(xb, y - TH, -ZD), -Vector3.UnitZ, 0.5f, PX1, PY0 + 0.02f), Vx(new(xa, y - TH, -ZD), -Vector3.UnitZ, 0.5f, PX0, PY0 + 0.02f));
            }
            foreach (var xe in new[] { x0, x1 })
            {
                var nx = new Vector3(xe == x0 ? -1 : 1, 0, 0);
                Quad(roots, Vx(new(xe, y, -ZD), nx, 0.6f, PX0, PY0), Vx(new(xe, y, ZD), nx, 0.6f, PX0, PY1),
                    Vx(new(xe, y - TH, ZD), nx, 0.5f, PX0 + 0.02f, PY1), Vx(new(xe, y - TH, -ZD), nx, 0.5f, PX0 + 0.02f, PY0));
            }
        }

        var dTop = MakeDobj(mGrass, top);
        var dWall = MakeDobj(mCliff, wall);
        var dUnder = MakeDobj(mRock, under);
        var dRoots = MakeDobj(atlasMobj, roots);
        dTop.Next = dWall; dWall.Next = dUnder; dUnder.Next = dRoots;
        Append(groot, new HSD_JOBJ { Flags = JOBJ_FLAG.OPA, SX = 1, SY = 1, SZ = 1, Dobj = dTop });
        Console.WriteLine($"island2: rim {N} pts, top {top.Count / 3} tris, walls {wall.Count / 3}, under {under.Count / 3}, roots+planks {roots.Count / 3}");
    }
}
