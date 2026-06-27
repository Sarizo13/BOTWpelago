"""Construit tmp/flag_names.json : {hash_u32: DataName} pour TOUS les flags du gamedata."""
import json, zlib
from pathlib import Path
import oead
BOOTUP=Path(r"D:\Emulateur\Jeux Wiiu\Updates and DLC\The Legend of Zelda Breath of the Wild (UPDATE DATA) (v208) (3,253 GB) (EUR) (unpacked)\content\Pack\Bootup.pack")
sarc=oead.Sarc(BOOTUP.read_bytes())
gd=oead.Sarc(oead.yaz0.decompress(next(bytes(f.data) for f in sarc.get_files() if f.name=="GameData/gamedata.ssarc")))
m={}
for f in gd.get_files():
    root=oead.byml.from_binary(bytes(f.data))
    for key in root:
        if key.endswith("_data"):
            for e in root[key]:
                if "DataName" in e:
                    dn=str(e["DataName"])
                    m[str(zlib.crc32(dn.encode("ascii"))&0xFFFFFFFF)]=dn
Path(r"D:\Project arch BOTW\tmp\flag_names.json").write_text(json.dumps(m), encoding="utf-8")
print(f"{len(m)} flags -> tmp/flag_names.json")
