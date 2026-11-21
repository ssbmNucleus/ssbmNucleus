using HSDRaw;
using mexLib.Types;

class Program
{
    static void Require(bool condition, string message)
    { if (!condition) throw new Exception(message); }

    static byte[] Archive(params string[] roots)
    {
        var f = new HSDRawFile();
        foreach (string r in roots)
            f.Roots.Add(new HSDRootNode { Name = r, Data = new HSDAccessor { _s = new HSDStruct(0x20) } });
        using var ms = new MemoryStream();
        f.Save(ms);
        return ms.ToArray();
    }

    static int Main()
    {
        var checks = new Dictionary<string, Action>
        {
            ["viwait_single_root_is_used"] = () =>
            {
                string s = SinglePlayerGuard.ResolveViWaitSymbol("ftDemoResultMotionFileWolf",
                    SinglePlayerGuard.ReadRootNames(Archive("ftDemoViWaitMotionFileWolf")));
                Require(s == "ftDemoViWaitMotionFileWolf", "got '" + s + "'");
            },
            ["viwait_clone_uses_donor_symbol_in_its_file"] = () =>
            {
                // A clone ships its donor's DViWait file, so the symbol is the donor's.
                string s = SinglePlayerGuard.ResolveViWaitSymbol("ftDemoResultMotionFileLuigi",
                    new[] { "ftDemoViWaitMotionFileLuigi" });
                Require(s == "ftDemoViWaitMotionFileLuigi", "got '" + s + "'");
            },
            ["viwait_prefers_result_suffix_when_several"] = () =>
            {
                string s = SinglePlayerGuard.ResolveViWaitSymbol("ftDemoResultMotionFileWolf",
                    new[] { "ftDemoViWaitMotionFileFox", "ftDemoViWaitMotionFileWolf" });
                Require(s == "ftDemoViWaitMotionFileWolf", "got '" + s + "'");
            },
            ["viwait_never_guesses_a_missing_symbol"] = () =>
            {
                Require(SinglePlayerGuard.ResolveViWaitSymbol("ftDemoResultMotionFileWolf", new[] { "somethingElse" }) == "", "invented a symbol");
                Require(SinglePlayerGuard.ResolveViWaitSymbol("ftDemoResultMotionFileWolf", null) == "", "invented a symbol for an unreadable file");
            },
            ["media_own_file_kept_when_present"] = () =>
            {
                var disc = new HashSet<string> { "MvEndWolf.mth", "MvEndMario.mth" };
                string s = SinglePlayerGuard.ResolveExistingFile("MvEndWolf.mth", new[] { "MvEndMario.mth" }, disc.Contains);
                Require(s == "MvEndWolf.mth", "got '" + s + "'");
            },
            ["media_blank_falls_back_to_first_existing"] = () =>
            {
                var disc = new HashSet<string> { "MvEndMario.mth" };
                string s = SinglePlayerGuard.ResolveExistingFile("", new[] { "", "MvEndLuigi.mth", "MvEndMario.mth" }, disc.Contains);
                Require(s == "MvEndMario.mth", "got '" + s + "'");
            },
            ["media_missing_falls_back_to_donor_before_mario"] = () =>
            {
                var disc = new HashSet<string> { "GmRegendSimpleLuigi.thp", "GmRegendSimpleMario.thp" };
                string s = SinglePlayerGuard.ResolveExistingFile("GmRegendSimpleWeegee.thp",
                    new[] { "GmRegendSimpleLuigi.thp", "GmRegendSimpleMario.thp" }, disc.Contains);
                Require(s == "GmRegendSimpleLuigi.thp", "got '" + s + "'");
            },
            ["media_nothing_exists_keeps_current"] = () =>
            {
                string s = SinglePlayerGuard.ResolveExistingFile("MvEndWolf.mth", new[] { "MvEndMario.mth", null }, _ => false);
                Require(s == "MvEndWolf.mth", "got '" + s + "'");
                Require(SinglePlayerGuard.ResolveExistingFile(null, Array.Empty<string>(), _ => true) == "", "null current not normalised");
            },
            ["unreadable_archive_gives_null"] = () =>
            {
                Require(SinglePlayerGuard.ReadRootNames(new byte[] { 1, 2, 3 }) == null, "short garbage parsed");
                Require(SinglePlayerGuard.ReadRootNames(null) == null, "null parsed");
            },
        };

        int failed = 0;
        foreach (var (name, check) in checks)
        {
            try { check(); Console.WriteLine("PASS " + name); }
            catch (Exception e) { failed++; Console.WriteLine("FAIL " + name + ": " + e.Message); }
        }
        Console.WriteLine($"{checks.Count - failed}/{checks.Count} passed");
        return failed == 0 ? 0 : 1;
    }
}
