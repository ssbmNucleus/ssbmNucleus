// Phenac City (Pokemon Stadium): Colosseum INSTANCE joints flattened into real subtrees, plus the probe for them.
// Colosseum draws repeated props (palms, lamps) as JOBJ_INSTANCE joints whose child pointer REFERENCES a subtree
// elsewhere in the desc (Melee: jobj.c HSD_JObjDispAll draws child with jobj->mtx * inverse(child->mtx), i.e. the
// referenced subtree's root placed at the instance joint). HSDRaw's TreeList and every recursive walk here loop on
// them, so each instance becomes a plain joint whose child is a copy of the referenced subtree with identity TRS.
// Copies get new JOBJ structs but share the DOBJ chains (descs are read-only templates for the loader).
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.GX;
using HSDRaw.Tools;

static partial class Program
{
    const JOBJ_FLAG RootFlags = JOBJ_FLAG.ROOT_OPA | JOBJ_FLAG.ROOT_XLU | JOBJ_FLAG.ROOT_TEXEDGE;

    static HSD_JOBJ CopyJointNode(HSD_JOBJ s)
    {
        var c = new HSD_JOBJ { _s = new HSDStruct((byte[])s._s.GetData().Clone()) };
        foreach (var r in s._s.References) c._s.References[r.Key] = r.Value;
        return c;
    }

    // copy src and its descendants (not src.Next); instance joints inside are copied as instances (flattened later)
    static HSD_JOBJ CopyJointTree(HSD_JOBJ src, Dictionary<HSD_JOBJ, HSD_JOBJ> map)
    {
        var c = CopyJointNode(src);
        map[c] = src;
        c.Next = null;
        if (!src.Flags.HasFlag(JOBJ_FLAG.INSTANCE) && src.Child != null)
        {
            HSD_JOBJ head = null, tail = null;
            for (var k = src.Child; k != null; k = k.Next)
            {
                var kc = CopyJointTree(k, map);
                if (head == null) head = kc; else tail.Next = kc;
                tail = kc;
            }
            c.Child = head;
        }
        return c;
    }

    static T CopyAnimTree<T>(T src, bool withNext) where T : HSDTreeAccessor<T>, new()
    {
        if (src == null) return null;
        var c = new T { _s = new HSDStruct((byte[])src._s.GetData().Clone()) };
        foreach (var r in src._s.References) c._s.References[r.Key] = r.Value;
        c.Child = CopyAnimTree(src.Child, true);
        c.Next = withNext ? CopyAnimTree(src.Next, true) : null;
        return c;
    }

    // pair each joint with its anim node (same shape; instance joints' children are not mirrored)
    static void PairAnim<T>(HSD_JOBJ j, T a, Dictionary<HSD_JOBJ, T> outp) where T : HSDTreeAccessor<T>, new()
    {
        for (; j != null; j = j.Next, a = a?.Next)
        {
            if (a != null) outp[j] = a;
            if (!j.Flags.HasFlag(JOBJ_FLAG.INSTANCE) && j.Child != null) PairAnim(j.Child, a?.Child, outp);
        }
    }

    static int FlattenInstances(HSD_JOBJ root, HSD_MatAnimJoint mroot, HSD_AnimJoint aroot)
    {
        var mp = new Dictionary<HSD_JOBJ, HSD_MatAnimJoint>(); if (mroot != null) PairAnim(root, mroot, mp);
        var ap = new Dictionary<HSD_JOBJ, HSD_AnimJoint>(); if (aroot != null) PairAnim(root, aroot, ap);
        int n = 0;
        void W(HSD_JOBJ first, List<HSD_JOBJ> anc)
        {
            for (var c = first; c != null; c = c.Next)
            {
                if (c.Flags.HasFlag(JOBJ_FLAG.INSTANCE))
                {
                    var target = c.Child;
                    var map = new Dictionary<HSD_JOBJ, HSD_JOBJ>();
                    var copy = CopyJointTree(target, map);
                    copy.TX = copy.TY = copy.TZ = 0; copy.RX = copy.RY = copy.RZ = 0; copy.SX = copy.SY = copy.SZ = 1;
                    c.Flags &= ~JOBJ_FLAG.INSTANCE;
                    c.Flags |= RootFlags;
                    foreach (var a in anc) a.Flags |= RootFlags;
                    c.Child = copy;
                    // anims of the referenced subtree follow the copy (the copy's own root has identity TRS: drop its root tracks)
                    if (mp.TryGetValue(target, out var mt) && mp.TryGetValue(c, out var mc)) mc.Child = CopyAnimTree(mt, false);
                    if (ap.TryGetValue(target, out var at) && ap.TryGetValue(c, out var ac))
                    {
                        var acopy = CopyAnimTree(at, false);
                        acopy.AOBJ = null;
                        ac.Child = acopy;
                    }
                    // re-pair the new nodes so nested instances inside the copy also find their anims
                    if (mp.TryGetValue(c, out var mc2) && mc2.Child != null) PairAnim(copy, mc2.Child, mp);
                    if (ap.TryGetValue(c, out var ac2) && ac2.Child != null) PairAnim(copy, ac2.Child, ap);
                    n++;
                    W(copy, new List<HSD_JOBJ>(anc) { c });
                }
                else if (c.Child != null) W(c.Child, new List<HSD_JOBJ>(anc) { c });
            }
        }
        W(root, new List<HSD_JOBJ>());
        return n;
    }

    // Envelope (skinned) meshes baked rigid on their own joint: Colosseum palms store their vertices local to the
    // skeleton-root joint, so dropping the weights shows the bind pose there. Bone-only subtrees are pruned.
    static int BakeEnvelopes(HSD_JOBJ root, HSD_MatAnimJoint mroot, HSD_AnimJoint aroot)
    {
        var mp = new Dictionary<HSD_JOBJ, HSD_MatAnimJoint>(); if (mroot != null) PairAnim(root, mroot, mp);
        var ap = new Dictionary<HSD_JOBJ, HSD_AnimJoint>(); if (aroot != null) PairAnim(root, aroot, ap);
        int baked = 0;
        var bakedD = new HashSet<HSDStruct>();
        bool HasMesh(HSD_JOBJ j) { for (var c = j; c != null; c = c.Next) { if (c.Dobj != null || (c.Child != null && HasMesh(c.Child))) return true; } return false; }
        foreach (var j in root.TreeList)
        {
            if (j.Dobj == null) continue;
            bool any = false;
            foreach (var d in j.Dobj.List)
            {
                if (bakedD.Contains(d._s)) { any = true; continue; }   // shared with an instance copy baked earlier
                if (d.Pobj == null || d.Pobj.List.All(Rigid)) continue;
                HSD_POBJ head = null, tail = null;
                foreach (var p in d.Pobj.List)
                {
                    HSD_POBJ np = p;
                    if (!Rigid(p))
                    {
                        var attrs = p.ToGXAttributes().Select(x => x.AttributeName).Where(x => x != GXAttribName.GX_VA_NULL && x != GXAttribName.GX_VA_PNMTXIDX
                            && x != GXAttribName.GX_VA_TEX0MTXIDX && x != GXAttribName.GX_VA_TEX1MTXIDX).ToArray();
                        var tris = Triangles(p.ToDisplayList());
                        // The bind pose, as the renders' dumper works it out (tools/renders_v2/colodump): a vertex blended between bones is stored in the
                        // skeleton root's space and stays; a vertex bound to one bone alone is stored in THAT bone's space, and goes to the root's by the
                        // bone's bind matrix (the inverse of its inverse world transform). colograft_ps left those where they were, which folded every
                        // palm frond into a zigzag: unnoticed from round one's distance.
                        var envs = p.EnvelopeWeights;
                        if (envs != null && envs.Length > 0)
                            for (int vi = 0; vi < tris.Count; vi++)
                            {
                                var v = tris[vi];
                                var en = envs[Math.Min(v.PNMTXIDX / 3, envs.Length - 1)];
                                if (en.EnvelopeCount == 0 || en.GetWeightAt(0) < 0.999f || en.JOBJs[0]?.InverseWorldTransform == null) continue;
                                var t = en.JOBJs[0].InverseWorldTransform;
                                var iwt = new Matrix4x4(t.M11, t.M21, t.M31, 0, t.M12, t.M22, t.M32, 0, t.M13, t.M23, t.M33, 0, t.M14, t.M24, t.M34, 1);
                                if (!Matrix4x4.Invert(iwt, out var bind)) continue;
                                var q = Vector3.Transform(new Vector3(v.POS.X, v.POS.Y, v.POS.Z), bind);
                                v.POS.X = q.X; v.POS.Y = q.Y; v.POS.Z = q.Z;
                                tris[vi] = v;
                            }
                        var cf = p.Flags.HasFlag(POBJ_FLAG.CULLFRONT); var cb = p.Flags.HasFlag(POBJ_FLAG.CULLBACK);
                        var gen = new POBJ_Generator { CullMode = cf && cb ? GenCullMode.FrontAndBack : cf ? GenCullMode.Front : cb ? GenCullMode.Back : GenCullMode.None,
                            VertexColorFormat = (GXCompType)GXCompTypeClr.RGBA8 };
                        np = gen.CreatePOBJsFromTriangleList(tris, attrs, null);
                        gen.SaveChanges();
                        any = true;
                    }
                    var last = np; while (last.Next != null) last = last.Next;
                    if (head == null) head = np; else tail.Next = np;
                    tail = last;
                }
                tail.Next = null;
                d.Pobj = head;
                bakedD.Add(d._s);
            }
            if (!any) continue;
            baked++;
            j.Flags &= ~(JOBJ_FLAG.SKELETON_ROOT | JOBJ_FLAG.ENVELOPE_MODEL | JOBJ_FLAG.SKELETON);
            if (j.Child != null && !HasMesh(j.Child))
            {
                j.Child = null;
                if (mp.TryGetValue(j, out var m)) m.Child = null;
                if (ap.TryGetValue(j, out var a)) a.Child = null;
            }
        }
        return baked;
    }
}
