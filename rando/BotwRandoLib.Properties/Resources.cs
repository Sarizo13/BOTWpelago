using System.CodeDom.Compiler;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Resources;
using System.Runtime.CompilerServices;

namespace BotwRandoLib.Properties;

[GeneratedCode("System.Resources.Tools.StronglyTypedResourceBuilder", "17.0.0.0")]
[DebuggerNonUserCode]
[CompilerGenerated]
internal class Resources
{
	private static ResourceManager resourceMan;

	private static CultureInfo resourceCulture;

	[EditorBrowsable(EditorBrowsableState.Advanced)]
	internal static ResourceManager ResourceManager
	{
		get
		{
			if (resourceMan == null)
			{
				resourceMan = new ResourceManager("BotwRandoLib.Properties.Resources", typeof(Resources).Assembly);
			}
			return resourceMan;
		}
	}

	[EditorBrowsable(EditorBrowsableState.Advanced)]
	internal static CultureInfo Culture
	{
		get
		{
			return resourceCulture;
		}
		set
		{
			resourceCulture = value;
		}
	}

	internal static byte[] Demo003_0 => (byte[])ResourceManager.GetObject("Demo003_0", resourceCulture);

	internal static byte[] Demo033_0 => (byte[])ResourceManager.GetObject("Demo033_0", resourceCulture);

	internal static byte[] Demo333_0 => (byte[])ResourceManager.GetObject("Demo333_0", resourceCulture);

	internal static byte[] Demo700_0 => (byte[])ResourceManager.GetObject("Demo700_0", resourceCulture);

	internal static byte[] Demo701_0 => (byte[])ResourceManager.GetObject("Demo701_0", resourceCulture);

	internal static byte[] HyruleCastle => (byte[])ResourceManager.GetObject("HyruleCastle", resourceCulture);

	internal Resources()
	{
	}
}
