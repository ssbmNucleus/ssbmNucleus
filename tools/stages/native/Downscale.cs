// Downscale big grafted textures (e.g. a Colosseum 1024 atlas seen only from far away) and give them mip chains.
using System;
using System.Collections.Generic;
using System.Linq;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.GX;

static partial class Program
{
    static HSD_Image MakeImage(byte[] px, int w, int h, bool mips, int maxLevels = 99)
    {
        var data = new List<byte>(); int levels = 0, lw = w, lh = h; var cur = px;
        while (true)
        {
            data.AddRange(HSDRaw.Tools.GXImageConverter.ToCMP(cur, lw, lh)); levels++;
            if (!mips || lw <= 8 || lh <= 8 || levels >= maxLevels) break;
            cur = Half(cur, lw, lh); lw /= 2; lh /= 2;
        }
        var img = new HSD_Image { ImageData = data.ToArray(), Width = (short)w, Height = (short)h, Format = GXTexFmt.CMP };
        img.MipMap = levels > 1 ? 1 : 0; img.MinLOD = 0; img.MaxLOD = levels - 1;
        return img;
    }

    static void DownscaleTextures(HSD_JOBJ groot, int min, int to, bool mips)
    {
        var made = new Dictionary<HSDStruct, HSD_Image>();
        int n = 0;
        foreach (var j in groot.TreeList)
        {
            if (j.Dobj == null) continue;
            foreach (var d in j.Dobj.List)
                if (d.Mobj?.Textures != null)
                    foreach (var t in d.Mobj.Textures.List)
                    {
                        var img = t.ImageData; if (img == null || Math.Max(img.Width, img.Height) < min) continue;
                        var buf = img._s.GetReference<HSDAccessor>(0); if (buf == null) continue;
                        if (!made.TryGetValue(buf._s, out var ni))
                        {
                            int w = img.Width, h = img.Height; float k = to / (float)Math.Max(w, h);
                            int nw = Math.Max(8, (int)(w * k)), nh = Math.Max(8, (int)(h * k));
                            var px = CropResize(t.GetDecodedImageData(), w, 0, 0, w, h, nw, nh);
                            ni = MakeImage(px, nw, nh, mips);
                            made[buf._s] = ni;
                        }
                        t.ImageData = ni; t.TlutData = null;
                        if (mips) t.LOD = new HSD_TOBJ_LOD { MinFilter = GXTexFilter.GX_LIN_MIP_LIN, Bias = 0, BiasClamp = false, EnableEdgeLOD = true };
                        n++;
                    }
        }
        Console.WriteLine($"downscaled {made.Count} images (>= {min}) to {to}{(mips ? " with mips" : "")} on {n} texture objects");
    }
}
