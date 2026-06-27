using System;
using System.Collections.Generic;
using System.IO;
using EveryFileExplorer;
using SARCExt;
using Toolbox.Library;
using Toolbox.Library.IO;

namespace BotwRandoLib;

internal class LibHelpers
{
	public static RSTB rstb = new RSTB();

	public static bool CopyMapFiles(string sourcePath, string targetPath)
	{
		try
		{
			string[] directories = Directory.GetDirectories(sourcePath, "*", SearchOption.AllDirectories);
			foreach (string text in directories)
			{
				if (Path.GetFileNameWithoutExtension(text).Contains("-"))
				{
					Directory.CreateDirectory(text.Replace(sourcePath, targetPath));
				}
			}
			directories = Directory.GetFiles(sourcePath, "*.smubin", SearchOption.AllDirectories);
			foreach (string text2 in directories)
			{
				if (Path.GetFileNameWithoutExtension(text2).Contains("-"))
				{
					File.Copy(text2, text2.Replace(sourcePath, targetPath), overwrite: true);
				}
			}
		}
		catch
		{
			return false;
		}
		return true;
	}

	internal static void CopyRstbFile(string updateRstbFile, string gfxPackRstbFile)
	{
		if (!File.Exists(gfxPackRstbFile))
		{
			Directory.CreateDirectory(Path.GetDirectoryName(gfxPackRstbFile));
		}
		File.Copy(updateRstbFile, gfxPackRstbFile);
		rstb.LoadFile(gfxPackRstbFile);
	}

	internal static void CopyAndInjectEventFile(byte[] demoFile, string demoName, string updateEventsPath, string gfxPackEventsPath, bool isInBootup = false)
	{
		if (isInBootup)
		{
			if (!Directory.Exists(Path.GetDirectoryName(gfxPackEventsPath)))
			{
				Directory.CreateDirectory(Path.GetDirectoryName(gfxPackEventsPath));
			}
			string text = "EventFlow/" + demoName + ".bfevfl";
			FileStream fileStream = File.OpenRead(gfxPackEventsPath);
			SarcData sarcData = SARC.UnpackRamN(fileStream);
			fileStream.Close();
			sarcData.Files[text] = demoFile;
			byte[] item = SARC.PackN(sarcData).Item2;
			File.WriteAllBytes(gfxPackEventsPath, item);
			MemoryStream memoryStream = new MemoryStream(demoFile);
			RstbFile(text, memoryStream, isCompressed: false);
			memoryStream.Close();
			return;
		}
		if (!Directory.Exists(gfxPackEventsPath))
		{
			Directory.CreateDirectory(gfxPackEventsPath);
		}
		string text2 = Path.Combine(gfxPackEventsPath, demoName + ".sbeventpack");
		File.Copy(Path.Combine(updateEventsPath, demoName + ".sbeventpack"), text2);
		FileStream fileStream2 = File.OpenRead(text2);
		SarcData sarcData2 = SARC.UnpackRamN(YAZ0.Decompress(text2));
		fileStream2.Close();
		sarcData2.Files["EventFlow/" + demoName + ".bfevfl"] = demoFile;
		fileStream2 = File.OpenWrite(text2);
		Tuple<int, byte[]> tuple = SARC.PackN(sarcData2);
		fileStream2.Close();
		File.WriteAllBytes(text2, YAZ0.Compress(tuple.Item2));
		MemoryStream memoryStream2 = new MemoryStream(demoFile);
		RstbFile("EventFlow/" + demoName + ".bfevfl", memoryStream2, isCompressed: false);
		memoryStream2.Close();
		memoryStream2 = new MemoryStream(tuple.Item2);
		RstbFile("Event/" + demoName + ".beventpack", memoryStream2, isCompressed: false);
		memoryStream2.Close();
	}

	internal static List<uint> GetEventsToDisable()
	{
		return new List<uint>
		{
			956566239u, 1667561929u, 2158631089u, 857276579u, 2619496973u, 1470985759u, 2229064910u, 342083935u, 4091274328u, 146112473u,
			1754945523u, 1110838087u, 892419025u, 376831062u, 1634913472u, 3593817625u, 2295470152u, 3612460687u, 3758829974u, 2520755267u,
			4141537481u
		};
	}

	internal static List<uint> GetParagliderChests()
	{
		return new List<uint>
		{
			473644037u, 759164510u, 4093217196u, 1650509316u, 3746546895u, 3791240011u, 2029054705u, 2009260213u, 591392381u, 217594417u,
			3138298400u, 350171171u, 3005657673u, 2080206557u, 407446232u, 614466614u, 1403466912u, 3273140529u, 4046343091u, 2990124756u,
			3381003323u, 3729177928u, 3817004620u, 1757302122u, 950861039u, 2798152012u, 946822747u, 3063385243u, 2728429337u, 1313140003u,
			305852247u, 4125758579u
		};
	}

	internal static void RstbFiles(string rstbFile)
	{
		FileWriter fileWriter = new FileWriter(rstbFile);
		rstb.Write(fileWriter);
		fileWriter.Close();
		Yaz0 yaz = new Yaz0();
		FileStream fileStream = File.OpenRead(rstbFile);
		Stream stream = yaz.Compress(fileStream);
		fileStream.Close();
		File.WriteAllBytes(rstbFile, stream.ToArray());
	}

	internal static void RstbFile(string fileName, Stream fileStream, bool isCompressed)
	{
		rstb.SetEntry(fileName, fileStream, isCompressed);
	}

	internal static bool CopyShrineFiles(string baseShrinesPath, string dlcShrinesPath, string gfxPackBaseShrinesPath, string gfxPackDlcShrinesPath, ref List<string> dungeonFiles)
	{
		try
		{
			Directory.CreateDirectory(gfxPackBaseShrinesPath);
			Directory.CreateDirectory(gfxPackDlcShrinesPath);
			string[] files = Directory.GetFiles(baseShrinesPath, "Dungeon*.pack");
			foreach (string text in files)
			{
				string text2 = Path.Combine(gfxPackBaseShrinesPath, Path.GetFileName(text));
				File.Copy(text, text2);
				dungeonFiles.Add(text2);
			}
			files = Directory.GetFiles(dlcShrinesPath, "Dungeon*.pack");
			foreach (string text3 in files)
			{
				string text4 = Path.Combine(gfxPackDlcShrinesPath, Path.GetFileName(text3));
				File.Copy(text3, text4);
				dungeonFiles.Add(text4);
			}
		}
		catch
		{
			return false;
		}
		return true;
	}

	public static bool IsDirectoryValid(string directory)
	{
		return new DirectoryInfo(directory).Exists;
	}
}
