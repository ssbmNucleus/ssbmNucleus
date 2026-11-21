using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text.Json;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Melee.Gr;

static partial class Program
{
    // HSDRaw's path constructor opens read/write. Inputs must be read-only here.
    static HSDRawFile ReadArchive(string path) => new HSDRawFile(File.ReadAllBytes(path));

    static SBM_Map_GOBJ[] CheckedGroups(SBM_Map_Head head)
    {
        var groups = head.ModelGroups?.Array ?? Array.Empty<SBM_Map_GOBJ>();
        int declared = head._s.GetInt32(0x0C);
        if (groups.Length != declared)
            throw new InvalidDataException($"Stage declares {declared} model groups but HSDRaw exposes {groups.Length}. " +
                "Use a stage base with its split group table resolved (as in the Stadium examples); do not build a partial table.");
        return groups;
    }

    // Compare only the declared collision header/tables: HSD serialization may
    // change padding and struct boundaries without changing collision data.
    static string CollisionDigest(HSDStruct root)
    {
        if (root == null) return null;
        var header = root.GetData().Take(0x2C).ToArray();
        if (header.Length != 0x2C) throw new InvalidDataException("Short collision header");
        using var ms = new MemoryStream();
        foreach (int pointer in new[] { 0, 8, 0x24 }) Array.Clear(header, pointer, 4);
        ms.Write(header);
        foreach (var table in new[] { (ptr: 0, count: 4, size: 8), (ptr: 8, count: 12, size: 16), (ptr: 0x24, count: 0x28, size: 40) })
        {
            int count = root.GetInt32(table.count);
            if (count < 0 || count > 100000) throw new InvalidDataException("Invalid collision table count");
            int bytes = checked(count * table.size);
            if (bytes == 0) continue;
            if (!root.References.TryGetValue(table.ptr, out var data) || data == null || data.Length < bytes)
                throw new InvalidDataException("Incomplete collision table");
            ms.Write(data.GetData(), 0, bytes);
        }
        return Convert.ToHexString(SHA256.HashData(ms.ToArray())).ToLowerInvariant();
    }

    static object TreeInfo(HSD_JOBJ root)
    {
        // Colosseum instance joints can reference an ancestor/shared subtree.
        // HSDRaw's recursive TreeList assumes a tree; inspect the graph once.
        var joints = new List<HSD_JOBJ>();
        var seen = new HashSet<HSDStruct>();
        var pending = new Stack<HSD_JOBJ>();
        if (root != null) pending.Push(root);
        while (pending.Count > 0)
        {
            var j = pending.Pop();
            if (!seen.Add(j._s)) continue;
            joints.Add(j);
            if (j.Next != null) pending.Push(j.Next);
            if (j.Child != null) pending.Push(j.Child);
        }
        int meshes = 0, polygons = 0, particles = 0;
        var textures = new HashSet<HSDStruct>();
        foreach (var j in joints)
        {
            if (j.Flags.HasFlag(JOBJ_FLAG.PTCL)) { particles++; continue; }
            if (j.Flags.HasFlag(JOBJ_FLAG.INSTANCE)) continue;
            foreach (var d in j.Dobj?.List ?? new List<HSD_DOBJ>())
            {
                meshes++;
                polygons += d.Pobj?.List.Count ?? 0;
                foreach (var t in d.Mobj?.Textures?.List ?? new List<HSD_TOBJ>())
                    if (t.ImageData != null) textures.Add(t.ImageData._s);
            }
        }
        return new { joints = joints.Count, meshes, polygon_objects = polygons,
                     texture_images = textures.Count, particle_joints = particles };
    }

    static int Inspect(string path)
    {
        var f = ReadArchive(path);
        var head = f.Roots.Select(r => r.Data).OfType<SBM_Map_Head>().FirstOrDefault();
        var result = new Dictionary<string, object> {
            ["file"] = System.IO.Path.GetFullPath(path), ["bytes"] = new FileInfo(path).Length,
            ["roots"] = f.Roots.Select(r => r.Name).ToArray(),
            ["kind"] = head == null ? "hsd_archive" : "melee_stage",
        };
        var collision = f.Roots.FirstOrDefault(r => r.Name == "coll_data");
        result["collision_digest"] = CollisionDigest(collision?.Data?._s);
        if (head != null)
        {
            var groups = CheckedGroups(head);
            result["groups"] = groups.Select((g, i) => new {
                index = i, tree = TreeInfo(g.RootNode),
                joint_animations = g.JointAnimations?.Array.Length ?? 0,
                material_animations = g.MaterialAnimations?.Array.Length ?? 0,
                collision_links = g.CollisionLinkCount, collision_links2 = g.CollisionLinkCount2,
            }).ToArray();
        }
        if (f.Roots.Any(r => r.Name == "scene_data"))
        {
            result["kind"] = "scene_data";
            result["descriptors"] = Scene(f).JOBJDescs.Array.Select((d, i) => new {
                index = i, tree = TreeInfo(d.RootJoint),
                joint_animations = d.JointAnimations?.Length ?? 0,
                material_animations = d.MaterialAnimations?.Length ?? 0,
            }).ToArray();
        }
        Console.WriteLine(JsonSerializer.Serialize(result));
        return 0;
    }
}
