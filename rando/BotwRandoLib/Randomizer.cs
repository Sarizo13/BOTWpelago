// ---------------------------------------------------------------------------
// Part of a MODIFIED version of the Melonspeedrun BotW Randomizer
// (https://github.com/MelonSpeedruns/BotwRandomizer) — licensed under GPL v3.
//
// Modifications by the BOTWpelago project (2026) for Archipelago integration:
//   - AP config-driven chest placements via the BOTW_AP_CONFIG file (green-rupee
//     placeholder in each AP shrine chest), independent of the category toggles.
//   - In AP mode: the local paraglider chest is disabled (paraglider is an AP item)
//     and ONLY the 4 Great Plateau shrines are pre-cleared (Clear_Dungeon
//     038/041/009/065) to avoid the intro-quest conflict; others stay uncleared.
//   - An AP location dump (ap-locations.json) of every chest processed.
//
// See rando/README.md and rando/LICENSE (GPL v3).
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using BotwRandoLib.Properties;
using ByamlExt.Byaml;
using SARCExt;
using Toolbox.Library;
using Toolbox.Library.Security.Cryptography;

namespace BotwRandoLib;

public class Randomizer
{
	private static List<string> dungeonFiles = new List<string>();

	private static List<uint> eventsToDisable = new List<uint>();

	private static uint paragliderChest;

	private static Random random;

	private static BotwObjects overworldObjectsTable;

	private static BotwRandoTable chestObjectsTable;

	// AP: HashId du coffre/objet -> nom d'acteur a placer (genere par Archipelago)
	private static Dictionary<long, string> apConfig = null;

	// AP: dump des emplacements de coffres pour construire le pool de locations
	private static string currentDungeon = null;
	private static List<Dictionary<string, object>> apDump = new List<Dictionary<string, object>>();

	private static Dictionary<string, string> modifiedActors = new Dictionary<string, string>();

	private static string spoilerLogPath = "";

	private const int SPIRIT_ORB_COUNT = 240;

	private const int CHEST_COUNT = 1398;

	public const string VERSION = "2.1.1";

	private static int currentChestCount = 0;

	public static void RandomizeGame(string basePath, string updatePath, string dlcPath, string gfxPackPath, Dictionary<string, bool> randomizationSettings, out int progress, string seed = null)
	{
		if (string.IsNullOrWhiteSpace(seed))
		{
			seed = GenerateSeed();
		}
		random = new Random((int)Crc32.Compute(seed));
		// AP: charge les placements depuis la config (env BOTW_AP_CONFIG = JSON {settings:{...}, placements:{hashId:actor}})
		string apCfgPath = Environment.GetEnvironmentVariable("BOTW_AP_CONFIG");
		apConfig = null;
		if (!string.IsNullOrEmpty(apCfgPath) && File.Exists(apCfgPath))
		{
			var apRoot = Newtonsoft.Json.Linq.JObject.Parse(File.ReadAllText(apCfgPath));
			if (apRoot["placements"] != null)
				apConfig = apRoot["placements"].ToObject<Dictionary<long, string>>();
		}
		progress = 0;
		List<uint> paragliderChests = LibHelpers.GetParagliderChests();
		paragliderChest = paragliderChests[random.Next(paragliderChests.Count)];
		eventsToDisable = LibHelpers.GetEventsToDisable();
		overworldObjectsTable = new BotwObjects();
		chestObjectsTable = new BotwRandoTable(1398);
		if (!string.IsNullOrWhiteSpace(basePath) && !string.IsNullOrWhiteSpace(updatePath) && !string.IsNullOrWhiteSpace(dlcPath) && !string.IsNullOrWhiteSpace(gfxPackPath))
		{
			if (!LibHelpers.IsDirectoryValid(basePath) && !LibHelpers.IsDirectoryValid(updatePath) && !LibHelpers.IsDirectoryValid(dlcPath) && !LibHelpers.IsDirectoryValid(gfxPackPath))
			{
				throw new ArgumentException("One of the supplied Paths was not valid or doesn't exist!");
			}
			string text = Path.Combine(gfxPackPath, "BOTWpelago");
			try
			{
				if (Directory.Exists(text))
				{
					Directory.Delete(text, recursive: true);
				}
				Directory.CreateDirectory(text);
			}
			catch
			{
				progress = 100;
				return;
			}
			spoilerLogPath = Path.Combine(text, "spoiler-log.txt");
			File.WriteAllText(spoilerLogPath, "Seed: " + seed + "\n");
			File.WriteAllLines(Path.Combine(text, "rules.txt"), RulesTextFile("2.1.1"));
			string sourcePath = Path.Combine(dlcPath, "0010", "Map", "MainField");
			string text2 = Path.Combine(text, "aoc", "0010", "Map", "MainField");
			string updateRstbFile = Path.Combine(updatePath, "System", "Resource", "ResourceSizeTable.product.srsizetable");
			string text3 = Path.Combine(text, "content", "System", "Resource", "ResourceSizeTable.product.srsizetable");
			string path = Path.Combine(text, "aoc", "0010", "Pack", "AocMainField.pack");
			Directory.CreateDirectory(Path.GetDirectoryName(path));
			File.WriteAllText(path, string.Empty);
			LibHelpers.CopyRstbFile(updateRstbFile, text3);
			File.WriteAllText(Path.Combine(text, "content", "System", "Version.txt"), seed);
			progress++;
			if (!LibHelpers.CopyMapFiles(sourcePath, text2))
			{
				progress = 100;
				return;
			}
			progress++;
			string baseShrinesPath = Path.Combine(basePath, "Pack");
			string dlcShrinesPath = Path.Combine(dlcPath, "0010", "Pack");
			string gfxPackBaseShrinesPath = Path.Combine(text, "content", "Pack");
			string gfxPackDlcShrinesPath = Path.Combine(text, "aoc", "0010", "Pack");
			if (!LibHelpers.CopyShrineFiles(baseShrinesPath, dlcShrinesPath, gfxPackBaseShrinesPath, gfxPackDlcShrinesPath, ref dungeonFiles))
			{
				progress = 100;
				return;
			}
			progress++;
			string[] files = Directory.GetFiles(text2, "*.smubin", SearchOption.AllDirectories);
			File.WriteAllText(spoilerLogPath, File.ReadAllText(spoilerLogPath) + "\n\n=== Overworld ===\n");
			string[] array = files;
			for (int i = 0; i < array.Length; i++)
			{
				OpenMainFieldMapFile(array[i], "MainField", randomizationSettings);
			}
			progress++;
			File.WriteAllText(spoilerLogPath, File.ReadAllText(spoilerLogPath) + "\n\n=== Shrines ===\n");
			foreach (string dungeonFile in dungeonFiles)
			{
				OpenDungeonPackFile(dungeonFile, "CDungeon", randomizationSettings);
			}
			progress++;
			// AP: dump complet des coffres (HashId, sanctuaire/Overworld, vanilla) = pool de locations
			File.WriteAllText(Path.Combine(text, "ap-locations.json"),
				Newtonsoft.Json.JsonConvert.SerializeObject(apDump, Newtonsoft.Json.Formatting.Indented));
			string sourceFileName = Path.Combine(updatePath, "Pack", "Bootup.pack");
			string text4 = Path.Combine(text, "content", "Pack", "Bootup.pack");
			File.Copy(sourceFileName, text4, overwrite: true);
			UpdateGameData(text4);
			UpdateSaveData(text4);
			progress++;
			string updateEventsPath = Path.Combine(updatePath, "Event");
			string gfxPackEventsPath = Path.Combine(text, "content", "Event");
			LibHelpers.CopyAndInjectEventFile(Resources.Demo003_0, "Demo003_0", updateEventsPath, gfxPackEventsPath);
			LibHelpers.CopyAndInjectEventFile(Resources.Demo033_0, "Demo033_0", updateEventsPath, gfxPackEventsPath);
			LibHelpers.CopyAndInjectEventFile(Resources.Demo700_0, "Demo700_0", updateEventsPath, gfxPackEventsPath);
			LibHelpers.CopyAndInjectEventFile(Resources.Demo701_0, "Demo701_0", updateEventsPath, gfxPackEventsPath);
			LibHelpers.CopyAndInjectEventFile(Resources.Demo333_0, "Demo333_0", updateEventsPath, gfxPackEventsPath);
			LibHelpers.CopyAndInjectEventFile(Resources.HyruleCastle, "HyruleCastle", updateEventsPath, gfxPackEventsPath);
			progress++;
			Console.WriteLine(currentChestCount);
			LibHelpers.RstbFiles(text3);
			progress++;
		}
		else
		{
			if (string.IsNullOrWhiteSpace(basePath))
			{
				throw new ArgumentException("basePath is null or empty!");
			}
			if (string.IsNullOrWhiteSpace(updatePath))
			{
				throw new ArgumentException("updatePath is null or empty!");
			}
			if (string.IsNullOrWhiteSpace(dlcPath))
			{
				throw new ArgumentException("dlcPath is null or empty!");
			}
			if (string.IsNullOrWhiteSpace(gfxPackPath))
			{
				throw new ArgumentException("gfxPackPath is null or empty!");
			}
		}
	}

	private static void OpenDungeonPackFile(string dungeonFile, string mapType, Dictionary<string, bool> randomizationSettings)
	{
		FileStream fileStream = File.OpenRead(dungeonFile);
		SarcData dungeonSarcData = SARC.UnpackRamN(fileStream);
		fileStream.Close();
		string fileNameWithoutExtension = Path.GetFileNameWithoutExtension(dungeonFile);
		string dungeonPath = $"Map/CDungeon/{fileNameWithoutExtension}/{fileNameWithoutExtension}_Static.smubin";
		string dungeonPath2 = $"Map/CDungeon/{fileNameWithoutExtension}/{fileNameWithoutExtension}_Dynamic.smubin";
		RandomizeDungeon(ref dungeonSarcData, dungeonPath, "Static", fileNameWithoutExtension, "CDungeon", randomizationSettings);
		RandomizeDungeon(ref dungeonSarcData, dungeonPath2, "Dynamic", fileNameWithoutExtension, "CDungeon", randomizationSettings);
		Tuple<int, byte[]> tuple = SARC.PackN(dungeonSarcData);
		File.WriteAllBytes(dungeonFile, tuple.Item2);
	}

	private static bool IsYaz0(byte[] fileData)
	{
		if (fileData[0] == 89 && fileData[1] == 97 && fileData[2] == 122)
		{
			return fileData[3] == 48;
		}
		return false;
	}

	private static void RandomizeDungeon(ref SarcData dungeonSarcData, string dungeonPath, string staticDynamic, string dungeonName, string mapType, Dictionary<string, bool> randomizationSettings)
	{
		currentDungeon = dungeonName;   // AP: contexte sanctuaire pour le dump
		MemoryStream memoryStream = new MemoryStream(dungeonSarcData.Files[dungeonPath]);
		Yaz0 yaz = new Yaz0();
		Stream stream = yaz.Decompress(memoryStream);
		BymlFileData bymlFileData = ByamlFile.LoadN(stream);
		stream.Close();
		memoryStream.Close();
		List<object> list = (List<object>)bymlFileData.RootNode["Objs"];
		for (int i = 0; i < list.Count; i++)
		{
			Dictionary<string, object> actorObj = new Dictionary<string, object>();
			foreach (KeyValuePair<string, object> item in (Dictionary<string, object>)(dynamic)list[i])
			{
				actorObj.Add(item.Key, (dynamic)item.Value);
			}
			Dictionary<string, object> actorParams = new Dictionary<string, object>();
			if (((dynamic)list[i]).ContainsKey("!Parameters"))
			{
				foreach (KeyValuePair<string, object> item2 in (Dictionary<string, object>)((dynamic)list[i])["!Parameters"])
				{
					actorParams.Add(item2.Key, (dynamic)item2.Value);
				}
			}
			RandomizeMapObject(ref actorParams, ref actorObj, mapType, randomizationSettings);
			actorObj["!Parameters"] = actorParams;
			list[i] = actorObj;
		}
		byte[] buffer = ByamlFile.SaveN(bymlFileData);
		memoryStream = new MemoryStream(buffer);
		byte[] value = yaz.Compress(memoryStream).ToArray();
		memoryStream.Close();
		dungeonSarcData.Files[dungeonPath] = value;
		string fileName = $"Map/CDungeon/{dungeonName}/{dungeonName}_{staticDynamic}.mubin";
		memoryStream = new MemoryStream(buffer);
		LibHelpers.RstbFile(fileName, memoryStream, isCompressed: false);
		memoryStream.Close();
	}

	private static string[] RulesTextFile(string version)
	{
		return new List<string>
		{
			"[Definition]",
			"titleIds = 00050000101C9300,00050000101C9400,00050000101C9500",
			"name = BOTWpelago",
			"path = \"The Legend of Zelda: Breath of the Wild/BOTWpelago\"",
			"description = BOTWpelago (Archipelago multiworld) — base rando " + version + "|Active ce pack pour jouer au multiworld !",
			"version = 4"
		}.ToArray();
	}

	public static string GenerateSeed()
	{
		string text = "";
		Random random = new Random();
		for (int i = 0; i < 15; i++)
		{
			int number = random.Next(0, 62);
			text += ConvertToBase62(number).ToUpper();
		}
		char[] array = text.ToCharArray();
		array[4] = '-';
		array[^5] = '-';
		return new string(array);
	}

	private static string ConvertToBase62(int number)
	{
		string text = "";
		do
		{
			text += "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"[number % 62];
			number /= 62;
		}
		while (number != 0);
		return text;
	}

	private static void UpdateSaveData(string bootupFile)
	{
		FileStream fileStream = File.OpenRead(bootupFile);
		SarcData sarcData = SARC.UnpackRamN(fileStream);
		fileStream.Close();
		byte[] buffer = sarcData.Files["GameData/savedataformat.ssarc"];
		Yaz0 yaz = new Yaz0();
		MemoryStream memoryStream = new MemoryStream(buffer);
		SarcData sarcData2 = SARC.UnpackRamN(yaz.Decompress(memoryStream));
		memoryStream.Close();
		List<string> list = new List<string>();
		foreach (KeyValuePair<string, byte[]> file in sarcData2.Files)
		{
			list.Add(file.Key);
		}
		for (int i = 0; i < list.Count; i++)
		{
			if (list[i].StartsWith("/saveformat_"))
			{
				bool flag = false;
				MemoryStream memoryStream2 = new MemoryStream(sarcData2.Files[list[i]]);
				BymlFileData bymlFileData = ByamlFile.LoadN(memoryStream2);
				memoryStream2.Close();
				dynamic val = bymlFileData.RootNode["file_list"];
				for (int j = 0; j < val[1].Count; j++)
				{
					if (modifiedActors.ContainsKey(val[1][j]["DataName"]))
					{
						string text = modifiedActors[val[1][j]["DataName"]];
						bymlFileData.RootNode["file_list"][1][j]["HashValue"] = (int)Crc32.Compute(text);
						bymlFileData.RootNode["file_list"][1][j]["DataName"] = text;
						flag = true;
					}
				}
				if (flag)
				{
					sarcData2.Files[list[i]] = ByamlFile.SaveN(bymlFileData);
				}
			}
			byte[] item = SARC.PackN(sarcData2).Item2;
			memoryStream = new MemoryStream(item);
			Stream stream = yaz.Compress(memoryStream);
			sarcData.Files["GameData/savedataformat.ssarc"] = stream.ToArray();
			memoryStream = new MemoryStream(item);
			LibHelpers.RstbFile("GameData/savedataformat.sarc", memoryStream, isCompressed: false);
			memoryStream.Close();
			byte[] item2 = SARC.PackN(sarcData).Item2;
			File.WriteAllBytes(bootupFile, item2);
		}
	}

	private static void UpdateGameData(string bootupFile)
	{
		FileStream fileStream = File.OpenRead(bootupFile);
		SarcData sarcData = SARC.UnpackRamN(fileStream);
		fileStream.Close();
		byte[] buffer = sarcData.Files["GameData/gamedata.ssarc"];
		Yaz0 yaz = new Yaz0();
		MemoryStream stream = new MemoryStream(buffer);
		SarcData sarcData2 = SARC.UnpackRamN(yaz.Decompress(stream));
		List<string> list = new List<string>();
		foreach (KeyValuePair<string, byte[]> file in sarcData2.Files)
		{
			list.Add(file.Key);
		}
		for (int i = 0; i < list.Count; i++)
		{
			bool flag = false;
			MemoryStream memoryStream = new MemoryStream(sarcData2.Files[list[i]]);
			BymlFileData bymlFileData = ByamlFile.LoadN(memoryStream);
			memoryStream.Close();
			if (bymlFileData.RootNode.ContainsKey("bool_data"))
			{
				dynamic val = bymlFileData.RootNode["bool_data"];
				for (int j = 0; j < val.Count; j++)
				{
					if (modifiedActors.ContainsKey(val[j]["DataName"]))
					{
						string text = modifiedActors[val[j]["DataName"]];
						bymlFileData.RootNode["bool_data"][j]["HashValue"] = (int)Crc32.Compute(text);
						bymlFileData.RootNode["bool_data"][j]["DataName"] = text;
						flag = true;
					}
					if (val[j]["DataName"].Equals("IsGet_AncientArrow") || val[j]["DataName"].StartsWith("IsGet_Animal") || val[j]["DataName"].StartsWith("IsGet_App") || val[j]["DataName"].Equals("IsGet_BeeHome") || val[j]["DataName"].Equals("IsGet_BombArrow_A") || val[j]["DataName"].Equals("IsGet_ElectricArrow") || val[j]["DataName"].Equals("IsGet_FireArrow") || val[j]["DataName"].Equals("IsGet_IceArrow") || (val[j]["DataName"].StartsWith("IsGet_Weapon") && !val[j]["DataName"].Contains("Weapon_Sword_070")) || val[j]["DataName"].StartsWith("IsGet_Item") || val[j]["DataName"].Equals("IsGet_NormalArrow") || val[j]["DataName"].Equals("IsGet_KeySmall") || val[j]["DataName"].Equals("IsGet_Obj_Camera") || val[j]["DataName"].Equals("IsGet_Obj_IceMaker") || val[j]["DataName"].Equals("IsGet_Obj_RemoteBomb") || val[j]["DataName"].Equals("IsGet_Obj_StopTimer") || val[j]["DataName"].Equals("IsGet_Obj_RemoteBombLv2") || val[j]["DataName"].Equals("IsGet_Obj_StopTimerLv2") || val[j]["DataName"].Equals("IsGet_Obj_Magnetglove") || val[j]["DataName"].Equals("IsGet_Obj_Motorcycle") || val[j]["DataName"].Equals("IsGet_Obj_Maracas") || val[j]["DataName"].Equals("IsGet_Obj_AmiiboItem") || val[j]["DataName"].Equals("IsGet_Obj_Album") || val[j]["DataName"].Equals("IsGet_Obj_PictureBook") || val[j]["DataName"].Equals("IsGet_Obj_FireWoodBundle") || val[j]["DataName"].StartsWith("Guide") || val[j]["DataName"].StartsWith("IsHelp") || val[j]["DataName"].Equals("FirstTips") || (apConfig == null && val[j]["DataName"].StartsWith("Clear_Dungeon")) || val[j]["DataName"].Equals("Clear_Dungeon038") || val[j]["DataName"].Equals("Clear_Dungeon041") || val[j]["DataName"].Equals("Clear_Dungeon009") || val[j]["DataName"].Equals("Clear_Dungeon065") ||val[j]["DataName"].Equals("IsPlayed_Demo103_0") || val[j]["DataName"].Equals("IsPlayed_Demo042_0") || val[j]["DataName"].Equals("IsPlayed_Demo042_1") || val[j]["DataName"].Equals("IsPlayed_Demo010_0") || val[j]["DataName"].Equals("IsPlayed_Demo010_1") || val[j]["DataName"].Equals("IsPlayed_Demo104_0") || val[j]["DataName"].Equals("IsPlayed_Demo109_1") || val[j]["DataName"].Equals("IsPlayed_Demo140_0") || val[j]["DataName"].Equals("MapTower_07") || val[j]["DataName"].Equals("MapTower_07_Demo") || val[j]["DataName"].Equals("Open_StartPoint") || val[j]["DataName"].Equals("IsPlayed_Demo164_0") || val[j]["DataName"].Equals("IsPlayed_Demo166_0") || val[j]["DataName"].Equals("IsPlayed_Demo042_0") || val[j]["DataName"].Equals("IsPlayed_Demo042_1") || val[j]["DataName"].Equals("MapTower_DemoFirst"))
					{
						bymlFileData.RootNode["bool_data"][j]["InitValue"] = 1;
						flag = true;
					}
				}
			}
			if (bymlFileData.RootNode.ContainsKey("s32_data"))
			{
				dynamic val2 = bymlFileData.RootNode["s32_data"];
				for (int k = 0; k < val2.Count; k++)
				{
					if (val2[k]["DataName"].Equals("Location_MapTower07"))
					{
						bymlFileData.RootNode["s32_data"][k]["InitValue"] = 1;
						flag = true;
					}
				}
			}
			if (flag)
			{
				sarcData2.Files[list[i]] = ByamlFile.SaveN(bymlFileData);
			}
		}
		byte[] item = SARC.PackN(sarcData2).Item2;
		stream = new MemoryStream(item);
		byte[] value = yaz.Compress(stream).ToArray();
		sarcData.Files["GameData/gamedata.ssarc"] = value;
		stream = new MemoryStream(item);
		LibHelpers.RstbFile("GameData/gamedata.sarc", stream, isCompressed: false);
		stream.Close();
		byte[] item2 = SARC.PackN(sarcData).Item2;
		File.WriteAllBytes(bootupFile, item2);
	}

	private static void OpenMainFieldMapFile(string mapFile, string mapType, Dictionary<string, bool> randomizationSettings)
	{
		currentDungeon = null;   // AP: overworld (pas un sanctuaire)
		byte[] array = File.ReadAllBytes(mapFile);
		MemoryStream memoryStream = new MemoryStream(array);
		Yaz0 yaz = new Yaz0();
		BymlFileData bymlFileData;
		if (IsYaz0(array))
		{
			Stream stream = yaz.Decompress(memoryStream);
			bymlFileData = ByamlFile.LoadN(stream);
			stream.Close();
		}
		else
		{
			bymlFileData = ByamlFile.LoadN(memoryStream);
		}
		memoryStream.Close();
		List<object> list = (List<object>)bymlFileData.RootNode["Objs"];
		for (int i = 0; i < list.Count; i++)
		{
			Dictionary<string, object> actorObj = new Dictionary<string, object>();
			foreach (KeyValuePair<string, object> item in (Dictionary<string, object>)(dynamic)list[i])
			{
				actorObj.Add(item.Key, (dynamic)item.Value);
			}
			Dictionary<string, object> actorParams = new Dictionary<string, object>();
			if (((dynamic)list[i]).ContainsKey("!Parameters"))
			{
				foreach (KeyValuePair<string, object> item2 in (Dictionary<string, object>)((dynamic)list[i])["!Parameters"])
				{
					actorParams.Add(item2.Key, (dynamic)item2.Value);
				}
			}
			RandomizeMapObject(ref actorParams, ref actorObj, mapType, randomizationSettings);
			actorObj["!Parameters"] = actorParams;
			list[i] = actorObj;
		}
		byte[] buffer = ByamlFile.SaveN(bymlFileData);
		memoryStream = new MemoryStream(buffer);
		byte[] bytes = yaz.Compress(memoryStream).ToArray();
		memoryStream.Close();
		File.WriteAllBytes(mapFile, bytes);
		string fileNameWithoutExtension = Path.GetFileNameWithoutExtension(mapFile);
		string value = fileNameWithoutExtension.Split('_')[0];
		string fileName = $"Aoc/0010/Map/MainField/{value}/{fileNameWithoutExtension}.mubin";
		memoryStream = new MemoryStream(buffer);
		LibHelpers.RstbFile(fileName, memoryStream, isCompressed: false);
		memoryStream.Close();
	}

	private static bool ShouldBeRandomized(string unitconfigname, Dictionary<string, bool> randomizationSettings)
	{
		if (randomizationSettings.ContainsKey("randomizeArmorCheckbox") && randomizationSettings["randomizeArmorCheckbox"] && unitconfigname.StartsWith("Armor"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeSwordsCheckbox") && randomizationSettings["randomizeSwordsCheckbox"] && unitconfigname.StartsWith("Weapon_Sword"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeLongSwordsCheckbox") && randomizationSettings["randomizeLongSwordsCheckbox"] && unitconfigname.StartsWith("Weapon_Lsword"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeSpearsCheckbox") && randomizationSettings["randomizeSpearsCheckbox"] && unitconfigname.StartsWith("Weapon_Spear"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeBowsCheckbox") && randomizationSettings["randomizeBowsCheckbox"] && unitconfigname.StartsWith("Weapon_Bow"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeShieldsCheckbox") && randomizationSettings["randomizeShieldsCheckbox"] && unitconfigname.StartsWith("Weapon_Shield"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeEnemiesCheckbox") && randomizationSettings["randomizeEnemiesCheckbox"] && unitconfigname.StartsWith("Enemy"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeInsectsCheckbox") && randomizationSettings["randomizeInsectsCheckbox"] && unitconfigname.StartsWith("Animal_Insect"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeFishesCheckbox") && randomizationSettings["randomizeFishesCheckbox"] && unitconfigname.StartsWith("Animal_Fish"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizePlantsCheckbox") && randomizationSettings["randomizePlantsCheckbox"] && unitconfigname.StartsWith("Item_Plant"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeMushroomsCheckbox") && randomizationSettings["randomizeMushroomsCheckbox"] && unitconfigname.StartsWith("Item_Mushroom"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeFruitsCheckbox") && randomizationSettings["randomizeFruitsCheckbox"] && unitconfigname.StartsWith("Item_Fruit"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeAnimalsCheckbox") && randomizationSettings["randomizeAnimalsCheckbox"] && unitconfigname.StartsWith("Animal"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeOresCheckbox") && randomizationSettings["randomizeOresCheckbox"] && unitconfigname.StartsWith("Item_Ore"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeRupeesCheckbox") && randomizationSettings["randomizeRupeesCheckbox"] && unitconfigname.StartsWith("PutRupee"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeArrowsCheckbox") && randomizationSettings["randomizeArrowsCheckbox"] && unitconfigname.Contains("Arrow"))
		{
			return true;
		}
		if (randomizationSettings.ContainsKey("randomizeArmorShopsCheckbox") && randomizationSettings["randomizeArmorShopsCheckbox"] && unitconfigname.StartsWith("Mannequin"))
		{
			return true;
		}
		return false;
	}

	private static void RandomizeMapObject(ref Dictionary<string, dynamic> actorParams, ref Dictionary<string, dynamic> actorObj, string mapType, Dictionary<string, bool> randomizationSettings)
	{
		string text = actorObj["UnitConfigName"];
		if ((actorParams.ContainsKey("IsNearCreate") && actorParams["IsNearCreate"] == true) || ((actorParams.ContainsKey("IsHardModeActor") && actorParams["IsHardModeActor"] == true) ? true : false))
		{
			return;
		}
		if (eventsToDisable.Contains(actorObj["HashId"]))
		{
			actorObj["UnitConfigName"] = "Dummy";
			return;
		}
		if (actorObj["UnitConfigName"].StartsWith("Npc_King"))
		{
			actorObj["UnitConfigName"] = "Dummy";
			return;
		}
		if (text.StartsWith("TBox_") && !text.Contains("Gamble"))
		{
			currentChestCount++;
			// AP: enregistre ce coffre (HashId, sanctuaire ou Overworld, item vanilla)
			apDump.Add(new Dictionary<string, object>
			{
				{ "hashId", (long)actorObj["HashId"] },
				{ "dungeon", currentDungeon ?? "Overworld" },
				{ "vanilla", actorParams.ContainsKey("DropActor") ? (string)actorParams["DropActor"] : "" }
			});
			if (apConfig == null && paragliderChest == actorObj["HashId"])
			{
				// Hors-AP : le rando cache le paravoile dans un coffre du plateau.
				// En mode AP, le paravoile est un item AP livré par le client -> on saute ce placement.
				actorParams["DropActor"] = "PlayerStole2";
				File.WriteAllText(spoilerLogPath, File.ReadAllText(spoilerLogPath) + "\nParaglider: " + actorObj["HashId"]);
			}
			else if (apConfig != null && apConfig.ContainsKey((long)actorObj["HashId"]))
			{
				// AP impose l'item de ce coffre, INDEPENDAMMENT des toggles
				actorParams["DropActor"] = apConfig[(long)actorObj["HashId"]];
				File.AppendAllText(spoilerLogPath, "\n[AP] " + (string)actorParams["DropActor"] + ": " + actorObj["HashId"]);
			}
			else if (Randomizer.ShouldBeRandomized(actorParams["DropActor"], randomizationSettings))
			{
				RandomizeParameter("DropActor", ref actorParams, actorObj);
			}
			return;
		}
		if (text.Equals("TwnObj_GanonGrudgeSolid_Generator_A_01"))
		{
			actorParams["ActorName"] = "Enemy_Bokoblin_Gold";
			RandomizeParameter("ActorName", ref actorParams);
			return;
		}
		if (ShouldBeRandomized(text, randomizationSettings))
		{
			string randomMapObject = GetRandomMapObject(text);
			if (randomMapObject != null)
			{
				ModifyActorName(ref actorObj, randomMapObject, mapType);
			}
		}
		RandomizeParameter("EquipItem1", ref actorParams);
		RandomizeParameter("EquipItem2", ref actorParams);
		RandomizeParameter("EquipItem3", ref actorParams);
		RandomizeParameter("EquipItem4", ref actorParams);
		RandomizeParameter("ArrowName", ref actorParams);
	}

	private static void ModifyActorName(ref Dictionary<string, dynamic> actorObj, dynamic value, string mapType)
	{
		long num = actorObj["HashId"];
		string key = mapType + "_" + actorObj["UnitConfigName"] + "_" + num;
		string value2 = mapType + "_" + value + "_" + num;
		if (!modifiedActors.ContainsKey(key))
		{
			modifiedActors.Add(key, value2);
		}
		actorObj["UnitConfigName"] = (object)value;
	}

	private static void RandomizeParameter(string paramName, ref Dictionary<string, dynamic> actorParams, Dictionary<string, dynamic> actorObj = null)
	{
		if (!actorParams.ContainsKey(paramName))
		{
			return;
		}
		string text = actorParams[paramName];
		if (!(text != "Default"))
		{
			return;
		}
		string text2;
		if (paramName == "DropActor")
		{
			KeyValuePair<string, string> chestLootObject = GetChestLootObject();
			text2 = chestLootObject.Key;
			if (actorObj != null && !string.IsNullOrEmpty(chestLootObject.Value))
			{
				File.WriteAllText(spoilerLogPath, File.ReadAllText(spoilerLogPath) + "\n" + chestLootObject.Value + ": " + actorObj["HashId"]);
			}
		}
		else
		{
			text2 = GetRandomMapObject(text);
		}
		if (text2 != null)
		{
			actorParams[paramName] = text2;
		}
	}

	private static KeyValuePair<string, string> GetChestLootObject()
	{
		chestObjectsTable.ChestItems = chestObjectsTable.ChestItems.OrderBy((KeyValuePair<string, string> x) => random.Next()).ToList();
		KeyValuePair<string, string> keyValuePair = chestObjectsTable.ChestItems[0];
		chestObjectsTable.ChestItems.Remove(keyValuePair);
		return keyValuePair;
	}

	private static string GetRandomMapObject(string objectName)
	{
		for (int i = 0; i < overworldObjectsTable.OverworldObjects.Count; i++)
		{
			for (int j = 0; j < overworldObjectsTable.OverworldObjects.ElementAt(i).Key.Count; j++)
			{
				if (overworldObjectsTable.OverworldObjects.ElementAt(i).Key[j] == objectName)
				{
					int index = random.Next(overworldObjectsTable.OverworldObjects.ElementAt(i).Key.Count);
					string result = overworldObjectsTable.OverworldObjects.ElementAt(i).Key[index];
					if (overworldObjectsTable.OverworldObjects.ElementAt(i).Value)
					{
						overworldObjectsTable.OverworldObjects.Remove(overworldObjectsTable.OverworldObjects.ElementAt(i).Key);
					}
					return result;
				}
			}
		}
		return null;
	}
}
