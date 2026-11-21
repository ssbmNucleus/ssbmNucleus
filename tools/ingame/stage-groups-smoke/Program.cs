using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Melee.Gr;

// Synthetic DAT: ten embedded map groups, with exported references splitting
// the table at group 3 and again inside group 5. No game assets are needed.
const int table = 0x30, joint = 0x238, materials = 0x278, matJoint = 0x280;
const int dataSize = 0x290, floor = table + 5 * 0x34;
int[] relocations = { 8, floor, floor + 8, materials };
string[] symbols = { "map_head", "split_group_three", "split_group_five_animation_slot" };
var names = Encoding.ASCII.GetBytes(string.Join('\0', symbols) + '\0');
int roots = 0x20 + dataSize + relocations.Length * 4;
var bytes = new byte[roots + symbols.Length * 8 + names.Length];
void Put(int offset, int value) => BinaryPrimitives.WriteInt32BigEndian(bytes.AsSpan(offset, 4), value);
void Data(int offset, int value) => Put(0x20 + offset, value);
void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

Put(0, bytes.Length); Put(4, dataSize); Put(8, relocations.Length); Put(12, 1); Put(16, 2);
Data(8, table); Data(12, 10);
Data(floor, joint); Data(floor + 8, materials); Data(floor + 0x24, 17);
Data(joint + 0x20, 0x3f800000); Data(joint + 0x24, 0x3f800000); Data(joint + 0x28, 0x3f800000);
Data(materials, matJoint);
for (int i = 0; i < relocations.Length; i++) Put(0x20 + dataSize + 4 * i, relocations[i]);
int[] offsets = { 0, table + 3 * 0x34, floor + 4 };
int nameOffset = 0;
for (int i = 0; i < symbols.Length; i++)
{
    Put(roots + i * 8, offsets[i]); Put(roots + i * 8 + 4, nameOffset);
    nameOffset += symbols[i].Length + 1;
}
names.CopyTo(bytes, roots + symbols.Length * 8);

var file = new HSDRawFile(bytes);
var head = (SBM_Map_Head)file["map_head"].Data;
Check(head.ModelGroups.Length == 3, "Fixture must reproduce the original three-group truncation");
var groups = head.ReadModelGroups(file);
Check(groups.Length == 10, "Must read all ten declared groups");
Check(groups[5].RootNode?.SX == 1, "Normal floor/platform group must resolve its model");
Check(groups[5].MaterialAnimations?[0] != null, "Material pointer must survive a split inside the group");
Check(groups[5].CollisionLinkCount == 17, "Scalar fields past the split must be preserved");
Check(ReferenceEquals(groups[5].RootNode._s, file.GetReferenceAtDataOffset<HSDRaw.Common.HSD_JOBJ>(floor)._s),
      "Read descriptors must retain original pointed-to objects for texture edits");
head._s.SetInt32(0x0C, -1);
try { head.ReadModelGroups(file); throw new Exception("Invalid group count was accepted"); }
catch (InvalidDataException) { }
Console.WriteLine("PASS: split stage group table, model/material pointers, scalar fields, invalid count");
