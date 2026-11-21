// Authored looping flight paths: a closed Catmull-Rom through control points, sampled into linear keys
// for TRAX/TRAY/TRAZ and ROTY (facing along the motion), on a joint that carries the flying model.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.GX;
using HSDRaw.Tools;

static partial class Program
{
    static readonly Dictionary<HSD_JOBJ, HSD_AOBJ> pathAobjs = new();

    static HSD_AOBJ PathAobj(JsonElement pth)
    {
        var pts = pth.GetProperty("points").EnumerateArray().Select(e => new Vector3(e[0].GetSingle(), e[1].GetSingle(), e[2].GetSingle())).ToList();
        int frames = pth.GetProperty("frames").GetInt32();
        int step = pth.TryGetProperty("step", out var st) ? st.GetInt32() : 10;
        float yawOff = (pth.TryGetProperty("yaw_offset", out var yo) ? yo.GetSingle() : 0f) * MathF.PI / 180f;
        int n = pts.Count;
        // arc-length parameterisation so the speed is even along the loop
        Vector3 Cr(float u)
        {
            int i = (int)MathF.Floor(u); float t = u - i;
            Vector3 P(int k) => pts[((k % n) + n) % n];
            var p0 = P(i - 1); var p1 = P(i); var p2 = P(i + 1); var p3 = P(i + 2);
            return 0.5f * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t);
        }
        const int S = 2000;
        var samp = new Vector3[S + 1]; var len = new float[S + 1];
        for (int i = 0; i <= S; i++) { samp[i] = Cr(i * n / (float)S); if (i > 0) len[i] = len[i - 1] + Vector3.Distance(samp[i], samp[i - 1]); }
        Vector3 At(float frac)
        {
            float L = frac * len[S]; int k = Array.BinarySearch(len, L); if (k < 0) k = ~k;
            k = Math.Clamp(k, 1, S); float f = (L - len[k - 1]) / Math.Max(1e-5f, len[k] - len[k - 1]);
            return Vector3.Lerp(samp[k - 1], samp[k], f);
        }
        var kx = new List<FOBJKey>(); var ky = new List<FOBJKey>(); var kz = new List<FOBJKey>(); var kr = new List<FOBJKey>();
        float prevYaw = float.NaN;
        for (int fr = 0; fr <= frames; fr += step)
        {
            float frac = (fr % frames) / (float)frames;
            var p = At(frac);
            var d = At((frac + 0.002f) % 1f) - At((frac + 0.998f) % 1f);
            float yaw = MathF.Atan2(d.X, d.Z) + yawOff;
            if (!float.IsNaN(prevYaw)) while (yaw - prevYaw > MathF.PI) yaw -= MathF.Tau;
            if (!float.IsNaN(prevYaw)) while (yaw - prevYaw < -MathF.PI) yaw += MathF.Tau;
            prevYaw = yaw;
            kx.Add(new FOBJKey { Frame = fr, Value = p.X, InterpolationType = GXInterpolationType.HSD_A_OP_LIN });
            ky.Add(new FOBJKey { Frame = fr, Value = p.Y, InterpolationType = GXInterpolationType.HSD_A_OP_LIN });
            kz.Add(new FOBJKey { Frame = fr, Value = p.Z, InterpolationType = GXInterpolationType.HSD_A_OP_LIN });
            kr.Add(new FOBJKey { Frame = fr, Value = yaw, InterpolationType = GXInterpolationType.HSD_A_OP_LIN });
        }
        var ao = new HSD_AOBJ { Flags = AOBJ_Flags.ANIM_LOOP, EndFrame = frames };
        ao.AddTrack((byte)JointTrackType.HSD_A_J_TRAX, kx);
        ao.AddTrack((byte)JointTrackType.HSD_A_J_TRAY, ky);
        ao.AddTrack((byte)JointTrackType.HSD_A_J_TRAZ, kz);
        ao.AddTrack((byte)JointTrackType.HSD_A_J_ROTY, kr);
        Console.WriteLine($"  path: {n} control points, {frames} frames, {kx.Count} keys per track, length {len[S]:F0}");
        return ao;
    }
}
