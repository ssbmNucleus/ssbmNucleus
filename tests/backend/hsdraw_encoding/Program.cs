using System;
using System.Collections.Generic;
using System.Reflection;
using System.IO;
using System.Linq;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.GX;
using HSDRaw.Tools;

class Program
{
    static void Require(bool condition, string message)
    { if (!condition) throw new Exception(message); }

    static ushort Index(POBJ_Generator generator, float[] values)
    { return (ushort)typeof(POBJ_Generator).GetMethod("GetIndex", BindingFlags.NonPublic | BindingFlags.Instance).Invoke(generator, new object[] {GXAttribName.GX_VA_NBT, values}); }

    static int Main()
    {
        var checks = new Dictionary<string, Action> {
            ["cloned_small_texture_keeps_gpu_alignment"] = () => {
                foreach (int size in new[] {32, 64}) {
                    var pixels = Enumerable.Range(0, size).Select(i => (byte)(i + 1)).ToArray();
                    var source = new HSD_Image {Width=8, Height=8, ImageData=pixels};
                    var clone = new HSD_Image {_s=source._s.DeepClone()};
                    Require(!ReferenceEquals(source._s.References[0], clone._s.References[0]), "clone shares mutable texture storage");
                    var archive = new HSDRawFile();
                    archive.Roots.Add(new HSDRootNode {Name="cloned_image", Data=clone});
                    byte[] bytes;
                    using (var stream = new MemoryStream()) {
                        archive.Save(stream, optimize:false);
                        bytes=stream.ToArray();
                    }
                    var readback = new HSDRawFile(bytes);
                    var buffer = readback.Roots[0].Data._s.References[0];
                    int offset=readback.GetOriginalDataOffset(buffer);
                    Require(offset >= 0 && offset % 32 == 0, "cloned texture serialized at a non-GX-aligned address: " + offset);
                    Require(bytes.Skip(32 + offset).Take(size).SequenceEqual(pixels), "clone changed texture bytes");
                }
            },
            ["nonfinite_vertex_attribute_refused"] = () => {
                foreach (var value in new[]{float.NaN, float.PositiveInfinity, float.NegativeInfinity}) {
                    bool refused=false;
                    try { GX_AttributeCompressor.GenerateBuffer(new GX_Attribute{AttributeName=GXAttribName.GX_VA_POS}, new List<float[]>{new float[]{value,0,0}}); }
                    catch (ArgumentException) { refused=true; }
                    Require(refused, "nonfinite attribute silently changed to zero");
                }
            },
            ["zero_buffer_retains_index_width"] = () => {
                var attr = new GX_Attribute{AttributeName=GXAttribName.GX_VA_POS};
                var values = new List<float[]>();
                for(int i=0;i<257;i++) values.Add(new float[3]);
                GX_AttributeCompressor.GenerateBuffer(attr,values);
                Require(attr.AttributeType==GXAttribType.GX_INDEX16,"zero buffer cannot address index 256");
            },
            ["hash_collision_preserves_distinct_attributes"] = () => {
                var a = new float[9]; var b = new float[9]; b[0] = 1;
                Require(POBJ_Generator.GetApproximateFloatArrayHashCode(a) == POBJ_Generator.GetApproximateFloatArrayHashCode(b), "fixture must collide");
                var gen = new POBJ_Generator();
                Require(Index(gen, a) != Index(gen, b), "hash collision merged different values");
            },
            ["scratch_array_mutation_preserves_stored_value"] = () => {
                var gen = new POBJ_Generator(); var a = new float[9];
                var first = Index(gen, a); a[0] = 2;
                Require(Index(gen, a) != first && Index(gen, new float[9]) == first, "scratch array corrupted key/data");
            },
            ["index16_overflow_refused"] = () => {
                var gen = new POBJ_Generator();
                for (int i = 0; i <= ushort.MaxValue; i++) Require(Index(gen, new float[]{i}) == i, "unexpected index");
                try { Index(gen, new float[]{65536}); } catch (TargetInvocationException e) when (e.InnerException is InvalidOperationException) { return; }
                throw new Exception("index silently wrapped");
            },
            ["quantization_rounds_like_error_estimate"] = () => {
                var attr = new GX_Attribute {AttributeName = GXAttribName.GX_VA_POS};
                var values = new List<float[]> {new float[]{20, 0, 0}};
                for (int i=1; i<=1024; i++) values.Add(new float[]{i*.000001f, -i*.000001f, 0});
                GX_AttributeCompressor.GenerateBuffer(attr, values);
                double step = Math.Pow(2, -attr.Scale);
                Require(attr.CompType != GXCompType.Float, "fixture must quantize");
                for (int row=0; row<values.Count; row++) {
                    var actual = attr.GetDecodedDataAt(row);
                    for (int i=0; i<3; i++) Require(Math.Abs(actual[i]-values[row][i]) <= step/2 + 1e-8, "writer exceeds estimated half-step error");
                }
            },
            ["small_values_use_valid_fractional_bits"] = () => {
                var attr = new GX_Attribute {AttributeName = GXAttribName.GX_VA_POS};
                GX_AttributeCompressor.GenerateBuffer(attr, new List<float[]>{new float[]{1e-12f,-1e-12f,0}});
                Require(attr.Scale <= 31, "fractional bit count overflowed GX field");
            },
            ["fractional_bit_31_decode_has_positive_divisor"] = () => {
                var attr = new GX_Attribute {AttributeName=GXAttribName.GX_VA_POS};
                GX_AttributeCompressor.GenerateBuffer(attr,new List<float[]>{new float[]{1,0,0}});
                attr.Scale=31;
                var values=attr.GetDecodedDataAt(0);
                Require(values[0]>0, "signed C# shift inverted the values");
            }
        };
        int failures=0;
        foreach (var pair in checks) {
            try {pair.Value(); Console.WriteLine("PASS "+pair.Key);}
            catch(Exception e) {failures++; Console.WriteLine("FAIL "+pair.Key+": "+e.Message);}
        }
        Console.WriteLine($"{checks.Count-failures}/{checks.Count} passed");
        return failures==0 ? 0 : 1;
    }
}
