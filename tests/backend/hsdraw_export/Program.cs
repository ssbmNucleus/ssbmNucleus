using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.GX;
using HSDRaw.Tools;
using HSDRawViewer.Converters;
using HSDRawViewer.Tools.Animation;

// Asset-free integration checks against the actual ModelExporter and IONET SMD
// writer. Run from the repo root: dotnet run --project tests/backend/hsdraw_export -c Release
class Program
{
    static void Require(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    static ModelExportSettings Settings() => new() { ExportTextures = false };

    static HSD_JOBJ Fixture(params string[] names)
    {
        var root = new HSD_JOBJ { SX = 1, SY = 1, SZ = 1 };
        var child = new HSD_JOBJ { SX = 1, SY = 1, SZ = 1 };
        root.AddChild(child);
        var vertices = new List<GX_Vertex> {
            new() { POS = new GXVector3(0, 0, 0), NRM = new GXVector3(0, 0, 1), TEX0 = new GXVector2(0, 0) },
            new() { POS = new GXVector3(1, 0, 0), NRM = new GXVector3(0, 0, 1), TEX0 = new GXVector2(1, 0) },
            new() { POS = new GXVector3(0, 1, 0), NRM = new GXVector3(0, 0, 1), TEX0 = new GXVector2(0, 1) },
        };
        var generator = new POBJ_Generator { UseTriangleStrips = false };
        var polygon = generator.CreatePOBJsFromTriangleList(vertices,
            new[] { GXAttribName.GX_VA_PNMTXIDX, GXAttribName.GX_VA_POS,
                    GXAttribName.GX_VA_NRM, GXAttribName.GX_VA_TEX0 },
            vertices.Select(_ => new[] { root, child }).ToList(),
            vertices.Select(_ => new[] { 0.25f, 0.75f }).ToList());
        generator.SaveChanges();
        HSD_DOBJ previous = null;
        foreach (string name in names)
        {
            var dobj = new HSD_DOBJ {
                ClassName = name, Pobj = polygon,
                Mobj = new HSD_MOBJ { Material = new HSD_Material { Alpha = 1 } },
            };
            if (previous == null) root.Dobj = dobj;
            else previous.Next = dobj;
            previous = dobj;
        }
        return root;
    }

    static ModelExporter Exporter(HSD_JOBJ root) => new(root, Settings(), new JointMap());

    static void Names(HSD_JOBJ root, params string[] expected)
    {
        var sourceNames = root.TreeList.SelectMany(j => j.Dobj?.List ?? new List<HSD_DOBJ>())
            .Select(d => d.ClassName).ToArray();
        for (int repeat = 0; repeat < 2; repeat++)
        {
            var meshes = Exporter(root).Scene.Models[0].Meshes;
            Require(meshes.Select(m => m.Name).SequenceEqual(expected),
                "Unexpected mesh names: " + string.Join(", ", meshes.Select(m => m.Name)));
        }
        Require(root.TreeList.SelectMany(j => j.Dobj?.List ?? new List<HSD_DOBJ>())
            .Select(d => d.ClassName).SequenceEqual(sourceNames), "Source DAT labels changed");
    }

    static uint HashBytes(params HSDStruct[] structs)
    {
        uint hash = 0x811C9DC5;
        foreach (byte b in structs.SelectMany(s => s.GetData()))
            hash = unchecked((hash ^ b) * 0x01000193);
        return hash;
    }

    static int Main()
    {
        var checks = new Dictionary<string, Action> {
            ["unique_and_fallback_names_unchanged"] = () =>
                Names(Fixture("mesh0000", null, "mesh0000_1", "Mesh0000"),
                    "mesh0000", "Joint_0_Object_1", "mesh0000_1", "Mesh0000"),
            ["duplicates_reserve_existing_suffixes"] = () =>
                Names(Fixture("mesh0000", "mesh0000", "mesh0000_1", "mesh0000", "mesh0000_2"),
                    "mesh0000", "mesh0000_3", "mesh0000_1", "mesh0000_4", "mesh0000_2"),
            ["class_label_collides_with_generated_fallback"] = () =>
                Names(Fixture("Joint_0_Object_1", null), "Joint_0_Object_1", "Joint_0_Object_1_1"),
            ["collision_after_single_bind_suffix_across_joints"] = () => {
                var root = Fixture("part_SINGLE");
                var child = root.Children[0];
                child.Dobj = Fixture("part", "part").Dobj;
                Names(root, "part_SINGLE", "part_SINGLE_1", "part_SINGLE_2");
            },
            ["smd_preserves_geometry_and_weights"] = () => {
                var root = Fixture("mesh0000", "mesh0000", "mesh0000_1");
                var meshes = Exporter(root).Scene.Models[0].Meshes;
                Require(meshes.Count == 3 && meshes.All(m => m.Vertices.Count == 3), "Lost geometry");
                foreach (var vertex in meshes.SelectMany(m => m.Vertices))
                {
                    Require(vertex.Envelope.Weights.Select(w => w.BoneName)
                        .SequenceEqual(new[] { "JOBJ_0", "JOBJ_1" }), "Changed bone assignment");
                    Require(vertex.Envelope.Weights.Select(w => w.Weight)
                        .SequenceEqual(new[] { 0.25f, 0.75f }), "Changed vertex weights");
                }
                var directory = Path.Combine(Path.GetTempPath(), "hsdraw-export-" + Guid.NewGuid());
                Directory.CreateDirectory(directory);
                try
                {
                    string actual = Path.Combine(directory, "actual.smd");
                    string control = Path.Combine(directory, "control.smd");
                    ModelExporter.ExportFile(actual, root, Settings(), new JointMap());
                    // The same DAT geometry with already-unique labels must
                    // produce exactly the same skeleton, triangles and weights.
                    ModelExporter.ExportFile(control, Fixture("mesh0000", "mesh0000_2", "mesh0000_1"),
                        Settings(), new JointMap());
                    Require(File.ReadAllBytes(actual).SequenceEqual(File.ReadAllBytes(control)), "SMD payload changed");
                    string[] lines = File.ReadAllLines(actual);
                    int start = Array.IndexOf(lines, "triangles") + 1;
                    Require(start > 0 && Array.IndexOf(lines, "end", start) - start == 12,
                        "SMD must retain all three triangles");
                }
                finally { Directory.Delete(directory, recursive: true); }
            },
            ["material_hash_preserves_shared_acyclic_references"] = () => {
                var parent = new HSDStruct(new byte[] { 1, 2, 3, 4, 5, 6, 7, 8 });
                var shared = new HSDStruct(new byte[] { 9, 10, 11, 12 });
                parent.References.Add(0, shared);
                parent.References.Add(4, shared);
                Require(Exporter(Fixture()).GenerateHash32(parent) == HashBytes(parent, shared, shared),
                    "Shared references must still contribute at each occurrence");
            },
            ["missing_bone_uses_existing_fallback_without_changing_weights"] = () => {
                foreach (float weight in new[] { 0.25f, 1.0f })
                {
                    var root = Fixture("mesh");
                    var envelope = root.Dobj.Pobj.EnvelopeWeights[0];
                    // Preserve the reported envelope count while leaving a
                    // hole at its first joint reference, as in malformed DATs.
                    envelope.SetJOBJAt(0, null);
                    envelope.SetJOBJAt(2, root);
                    envelope.SetWeightAt(0, weight);
                    envelope.SetWeightAt(1, 1 - weight);
                    var mesh = Exporter(root).Scene.Models[0].Meshes[0];
                    Require(mesh.Vertices.Count == 3, "Missing bone removed geometry");
                    foreach (var vertex in mesh.Vertices)
                    {
                        Require(vertex.Envelope.Weights.Select(w => w.BoneName)
                            .SequenceEqual(new[] { "JOBJ_0", "JOBJ_1" }), "Wrong missing-bone fallback");
                        Require(vertex.Envelope.Weights.Select(w => w.Weight)
                            .SequenceEqual(new[] { weight, 1 - weight }), "Missing bone changed weights");
                    }
                }
            },
            ["empty_texture_keeps_mesh_and_valid_texture_links"] = () => {
                var directory = Path.Combine(Path.GetTempPath(), "hsdraw-export-" + Guid.NewGuid());
                Directory.CreateDirectory(directory);
                try
                {
                    foreach (bool hasValidTexture in new[] { false, true })
                    {
                        var root = Fixture("mesh");
                        root.Dobj.Mobj.Textures = new HSD_TOBJ {
                            DiffuseLightmap = true,
                            ImageData = new HSD_Image { Width = 0, Height = 8, Format = GXTexFmt.I4, ImageData = new byte[32] },
                        };
                        if (hasValidTexture)
                            root.Dobj.Mobj.Textures.Next = new HSD_TOBJ {
                                DiffuseLightmap = true,
                                ImageData = new HSD_Image { Width = 8, Height = 8, Format = GXTexFmt.I4, ImageData = new byte[32] },
                            };
                        var exporter = new ModelExporter(root, new ModelExportSettings {
                            Directory = directory + Path.DirectorySeparatorChar,
                        }, new JointMap());
                        Require(exporter.Scene.Models[0].Meshes[0].Vertices.Count == 3, "Empty texture removed geometry");
                        Require(exporter.MaterialTextureMap.Count == (hasValidTexture ? 1 : 0), "Invalid texture sidecar link");
                        if (hasValidTexture)
                        {
                            string texture = exporter.MaterialTextureMap.Values.Single();
                            Require(File.Exists(Path.Combine(directory, texture)), "Missing valid texture PNG");
                            Require(exporter.Scene.Materials[0].DiffuseMap.FilePath == texture, "Wrong diffuse texture link");
                        }
                        else Require(exporter.Scene.Materials[0].DiffuseMap == null, "Dangling diffuse texture link");
                    }
                }
                finally { Directory.Delete(directory, recursive: true); }
            },
            ["material_hash_terminates_on_cycles"] = () => {
                var parent = new HSDStruct(new byte[] { 1, 2, 3, 4 });
                var child = new HSDStruct(new byte[] { 5, 6, 7, 8 });
                parent.References.Add(0, child);
                child.References.Add(0, parent);
                Require(Exporter(Fixture()).GenerateHash32(parent) == HashBytes(parent, child),
                    "Cyclic reference should stop at the active ancestor");
            },
        };
        foreach (var check in checks)
        {
            try { check.Value(); }
            catch (Exception error)
            {
                Console.Error.WriteLine("FAIL " + check.Key + ": " + error);
                return 1;
            }
            Console.WriteLine("PASS " + check.Key);
        }
        Console.WriteLine($"{checks.Count} export checks passed");
        return 0;
    }
}
