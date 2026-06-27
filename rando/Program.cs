// BOTWpelago headless CLI for the (modified) Melonspeedrun BotW Randomizer (GPL v3).
// New file by the BOTWpelago project (2026). See rando/README.md and rando/LICENSE.
using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using BotwRandoLib;

internal class Program
{
    private static void Main(string[] args)
    {
        string settingsPath = args.Length > 0 ? args[0]
            : @"D:\Project arch BOTW\Melonspeedrun rando\2.1.1\settings.json";
        JObject j = JObject.Parse(File.ReadAllText(settingsPath));
        JToken ss = j["StringSettings"];
        string basePath   = (string)ss["BasePath"]["Value"];
        string updatePath = (string)ss["UpdatePath"]["Value"];
        string dlcPath    = (string)ss["DlcPath"]["Value"];
        string gfxPath    = (string)ss["GfxPackPath"]["Value"];
        // Toggles : lus depuis la config AP (section "settings"), sinon tout active par defaut.
        var settings = new Dictionary<string, bool>();
        string apCfg = Environment.GetEnvironmentVariable("BOTW_AP_CONFIG");
        JToken sNode = (!string.IsNullOrEmpty(apCfg) && File.Exists(apCfg))
            ? JObject.Parse(File.ReadAllText(apCfg))["settings"] : null;
        foreach (string k in new[]{"Animals","Armor","ArmorShops","Arrows","Bows","Enemies","Fishes",
            "Fruits","Insects","LongSwords","Mushrooms","Ores","Plants","Rupees","Shields","Spears","Swords","SubBosses"})
        {
            string key = "randomize" + k + "Checkbox";
            settings[key] = (sNode != null && sNode[key] != null) ? (bool)sNode[key] : true;
        }
        string seed = args.Length > 1 ? args[1] : "APTEST";
        Console.WriteLine($"base={basePath}");
        Console.WriteLine($"update={updatePath}");
        Console.WriteLine($"dlc={dlcPath}");
        Console.WriteLine($"gfx={gfxPath}");
        Console.WriteLine($"seed={seed}");
        Console.WriteLine("AP config = " + (Environment.GetEnvironmentVariable("BOTW_AP_CONFIG") ?? "(aucune)"));
        Randomizer.RandomizeGame(basePath, updatePath, dlcPath, gfxPath, settings, out int progress, seed);
        Console.WriteLine("DONE, progress=" + progress);
    }
}
