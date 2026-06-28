# Chaîne de pointeurs HP joueur BotW Wii U 1.5.0 (Cemu)

> Mod externe pour lire/écrire les HP de Link via `ReadProcessMemory/WriteProcessMemory` sur `cemu.exe`, version Wii U 1.5.0 (update v208), PowerPC big-endian.

## 1. Subsystem `PlayerInfo` et initialisation sur Wii U 1.5.0

La documentation ZeldaMods sur le subsystem `PlayerInfo` confirme que c’est l’objet qui contient les informations de joueur (position, hearts, stamina, etc.).[web:45]

Table récapitulative :

| Champ | Valeur |
| --- | --- |
| Description | Holds information about the player (position, heart, stamina, etc.).[web:45] |
| Init function (Switch 1.5.0) | `0x0000007100854298`.[web:45] |
| Init function (Wii U 1.5.0) | `0x02D495D8`.[web:45] |

Sur Wii U 1.5.0, ton analyse du RPX v208 a déjà identifié une fonction `getLife` à `0x02D49974` qui fait `lfs f0, 0x64(r3)` puis `fctiwz`, ce qui colle exactement avec l’idée que le HP courant est un `float` à l’offset `+0x64` de l’objet `life` passé dans `r3`.[web:1]

L’init function `PlayerInfo` à `0x02D495D8` est donc un bon point d’entrée pour remonter vers des pointeurs globaux/Singletons qui référencent l’acteur joueur et son objet de vie.[web:45]

## 2. GameData et sauvegardes : où sont stockés les hearts ?

La page ZeldaMods "Save Files" décrit la structure des fichiers de sauvegarde, en particulier `game_data.sav`, qui contient les données de chaque save state sous forme de chunks 8 octets : `id` (crc32 du nom de flag interne) + `value`. Les données sont little-endian sur Switch et **big-endian sur Wii U**.[web:59]

Table récapitulative :

| Fichier | Rôle |
| --- | --- |
| `option.sav` | Paramètres d’options (inverted camera, etc.).[web:59] |
| `caption.sav` | Métadonnées affichées dans l’écran de sélection de sauvegarde (time, location). Les flags sont définis dans `saveformat_*.bgsvdata`.[web:59] |
| `game_data.sav` | Données de jeu (GameData flags) pour chaque save. Les flags sont définis dans `saveformat_*.bgsvdata` et `gamedata.ssarc/*`.[web:59] |

Le save editor de Marc Robledo expose un champ "Max. hearts" et "Max. stamina" qui montrent que le nombre de conteneurs de cœur/stamina est bien géré via GameData/flags dans `game_data.sav`, modifiables hors ligne.[web:59][web:49]

Ce système de flags est géré par le subsystem `GameDataMgr`, décrit par ZeldaMods comme responsable du stockage et de la lecture des flags dans les bgdata et de leur transfert vers et depuis les saves via `SaveSystem` et `SaveMgr`.[web:18][web:76]

Implications pour le mod :

- Le **nombre de conteneurs de cœur/stamina** (la jauge max) est stocké dans GameData (`game_data.sav`) via des flags int32/float, modifiables hors ligne ou via le moteur s’il expose des setters sur `GameDataMgr`.
- Le **HP actuel** (la valeur courante, incluant les cœurs temporaires, la valeur exacte en float) est un champ runtime dans `PlayerInfo` / l’objet `life`, pas un simple flag GameData.

## 3. Chaînes de pointeurs utilisées par Cheat Engine / FearLess / Cemu

Les communautés FearLess Cheat Engine et Cemu rappellent que pour Cemu (émulation Wii U), il faut utiliser des types big-endian dans Cheat Engine pour pointer les valeurs de santé, en particulier 2-byte big-endian pour la santé représentée en unités de quart de cœur.[web:32][web:66]

Un guide pour Wind Waker HD sur Cemu montre :

- Chaque cœur vaut 4 unités.
- Pour 3 cœurs pleins, il faut chercher la valeur 12 (3 × 4) en 2-byte big-endian.
- Les conteneurs (nombre de cœurs max) sont stockés dans une valeur 2-byte big-endian à l’adresse juste avant l’adresse de la vie courante, ce qui donne une **séquence de deux valeurs consécutives** : (conteneurs, vie). Changer la valeur précédente permet de modifier de façon persistante le nombre de cœurs max, tandis que la valeur suivante contrôle le HP courant.[web:66]

Même si cet exemple est pour Wind Waker HD, la même logique est reprise par les topics pour BotW sur Cemu :

- Utiliser des scripts Cheat Engine pour ajouter des types 2-byte/4-byte/float big-endian.[web:10][web:47]
- Scanner les HP comme entier (quart de cœur) ou float big-endian à une adresse relative à des structures `PlayerInfo` / `Actor`.

Les cheat tables BOTW sur FearLess (et CemuPiracy) sont distribuées via un topic unique, mais les détails internes (pointer paths exacts) ne sont pas publiés textuellement dans les extraits accessibles ; les tables `.CT` contiennent des pointer scans avec offsets et AOB scans pour s’accrocher sur les instructions qui écrivent la vie (similarité avec ton patch `Infinite Hearts` qui NOP une méthode `setLife`/applyDamage).[web:68][web:69]

En résumé :

- Les cheat tables BOTW Cemu utilisent **des pointer paths dynamiques** obtenus par pointer scan (Cheat Engine) depuis l’adresse de la santé jusqu’à un pointeur stable, plutôt que des adresses absolues.
- Elles s’appuient souvent sur un **AOB scan** autour de l’instruction de dégâts / mise à jour de la vie pour accrocher un code injection qui maintient la santé ou modifie la valeur avant l’écriture.

## 4. Classe `PlayerInfo` et stockage des HP dans la décompilation zeldaret/botw

La décompilation `zeldaret/botw` est pour BotW Switch 1.5.0, mais les structures logiques sont partagées avec la version Wii U, même si les offsets peuvent différer. Le `PlayerInfo` y est documenté comme subsystem, mais la page ZeldaMods ne donne pas directement les offsets des champs (hearts, stamina).[web:28][web:45]

La doc ZeldaMods indique simplement : "Holds information about the player (position, heart, stamina, etc.)", sans détailler la structure C++.[web:45]

Quant à `GameDataMgr`, la page précise que :

- Il gère les GameData flags, y compris des compteurs de difficulté (defeated counters) et des paramètres de boutique, etc.[web:18][web:76][web:37]

La décompilation zeldaret/botw sur GitHub n’expose pas encore une classe `PlayerInfo` complète dans le dépôt public ; la documentation de l’API NiceneNerd (`botw-utils`) se concentre sur les outils de fichiers (SARC/BYML/RSTB), pas sur les structures runtime en mémoire.[web:28][web:29]

Conséquence : pour l’instant, il n’y a pas de **mapping officiel public (nom de champ, offset)** pour le HP courant dans `PlayerInfo` sur Switch 1.5.0, et encore moins sur Wii U 1.5.0. Les moddeurs et reverse engineers s’appuient sur leurs propres décomps locales du RPX pour établir ces offsets, comme tu l’as déjà fait avec `getLife` et son offset `+0x64` dans l’objet `life`.[web:1]

## 5. GameData : hearts et HP

Les GameData flags sont définis dans des fichiers BYML (`bgdata`) dans `Pack/Bootup.pack//GameData/gamedata.ssarc/*`. ZeldaMods explique que chaque flag a un type (bool, int32, float32, etc.) et que les valeurs sont stockées dans les saves via un mapping `id` (crc32 du nom) vers `value`.[web:59][web:26]

Les flags liés aux items (armes, boucliers, etc.) sont stockés dans des arrays `PorchItem`, `PorchEquip`, `PorchItem_Value1`, etc., tandis que des données de cuisine utilisent des arrays `CookEffect0`, `CookEffect1`, `StaminaRecover`. Le champ `StaminaRecover[0]` est décrit comme `HitPointRecover`, montrant que les effets de nourriture sur la vie utilisent des floats vector2f en GameData.[web:59]

Cela montre que :

- Les **effets de récupération de vie** (soin) sont stockés dans GameData pour les items cuisinés.
- Le **HP courant** lui-même n’est pas stocké tel quel dans `game_data.sav` ; ce fichier garde plutôt les états persistants, pas la valeur instantanée de la vie.

Les moddeurs se reposent donc sur :

- GameData pour le **nombre de cœurs max / stamina max**, via des flags spécifiques (consommation de Spirit Orbs).
- PlayerInfo / objets runtime pour le **HP actuel**.

## 6. Effets de mort, Mipha’s Grace et autres revives

Les topics de cheat sur Cemu pour BotW mentionnent des patches d’instructions pour rendre Mipha’s Grace/Revali’s Gale infinis, par exemple :

- `0x1842CBAB8 = nop ;inf mimpa's grace`
- `0x1842CB974 = nop ;inf revali's gale`.[web:13]

Cela montre que :

- La logique de Mipha’s Grace est gérée par un code spécifique qui check l’état de la capacité et applique un revive lorsque la vie tombe à zéro.
- Les cheaters rendent cette capacité infinie en NOPant l’instruction qui décrémente le compteur ou désactive la capacité.[web:13]

Pour la mort de Link :

- Les jeux Zelda traditionnels déclenchent un `Game Over` quand le HP tombe à zéro.[web:33][web:46]
- Dans BotW, lorsque la vie atteint 0, le moteur vérifie les capacités de revive (Mipha’s Grace, Fairy) avant de déclencher la mort.

Implication pratique pour ton mod :

- **Écrire HP = 0** dans l’objet de vie ne garantit pas un "vrai" game over, car si Mipha’s Grace ou une Fairy sont actifs, le jeu va te remonter la vie via ces systèmes.
- Pour "tuer Link à la demande" de manière fiable, il faudrait idéalement :
  - Soit désactiver les revives (patcher les flags/capacités, ou NOP les fonctions associées comme le cheat pour Mipha).[web:13]
  - Soit écrire HP = 0 dans un contexte où ces revives ne se déclenchent pas (par exemple après avoir vidé les Fairy/Mipha).

Les sources publiques ne documentent pas une API simple pour "force death" via un flag GameData ou une fonction exposée ; tout se fait via patch de code ou modification directe de la valeur de vie suivie de la logique normale du jeu.[web:13]

## 7. Approche concrète pour pointer de façon stable vers l’objet `life` sur Cemu

### 7.1. Constats (RPX v208 + doc ZeldaMods)

- Tu as identifié `getLife` à `0x02D49974`, utilisant `lfs f0, 0x64(r3)` pour lire le float HP courant à offset `+0x64` dans l’objet `life` (`lifeObj`).[web:1]
- La fonction d’init `PlayerInfo` sur Wii U 1.5.0 est `0x02D495D8`, ce qui suggère que les objets de type `PlayerInfo`/`Link` sont initialisés autour de cette adresse.[web:45]
- Le cheat "Infinite Hearts" NOP une instruction à `0x02D452A4` (module 0x6267BFD0) associée à une méthode `setLife`/applyDamage appelée via `r29->[0xE8]->[0xA24](this, delta)`, ce qui montre un chemin de vtable/pointeur vers une fonction membre qui modifie la vie.[web:7]

### 7.2. Chaîne de pointeurs à reconstruire

Les moddeurs Cemu n’ont pas publié de pointer path "clé en main" pour la vie, mais on peut dériver une stratégie générique :

1. Attacher un debugger (IDA, Ghidra, ou ton mod Python) à `cemu.exe` et charger le RPX pour connaître les offsets dans le module `BotW`.
2. Rechercher l’appel de `getLife` (`0x02D49974`) et inspecter les callsites pour voir :
   - Quelle est l’origine du registre `r3` (lifeObj) ? Typiquement `r3` provient d’un champ dans une structure globale (PlayerInfo, Link actor).
   - Les champs autour de ce pointeur dans la structure `PlayerInfo`. ZeldaMods indique que `PlayerInfo` contient position, hearts, stamina ; l’objet `life` peut être un champ de `PlayerInfo` ou d’un sous-objet.[web:45]
3. Remonter la chaîne de pointeurs à partir de cette structure vers un singleton stable, par exemple :
   - `ksys::gdt::Manager` (GameDataMgr/Manager).[web:18]
   - `PlayerInfo` manager ou `ActorSystem`.

En pratique, sur Wii U :

- Le pointeur global vers `GameDataMgr`/`PlayerInfo` est souvent stocké dans `.bss` ou `.data` à une adresse fixe relative au RPX (ex. `0x106xxxxx` dans l’espace de BotW). La page GameDataMgr ZeldaMods donne son init function sur Switch mais pas l’adresse du singleton, ce qui nécessite du reverse local.[web:18]
- Une fois ce pointeur trouvé, la structure `PlayerInfo` permet d’accéder au champ `life`. Ton reverse a déjà prouvé que `life+0x64` est le HP courant.

### 7.3. Méthode pratique : pointer scan + AOB

Puisque l’objet `life` est réalloué/déplacé pendant le jeu, la pratique des cheat tables est :

1. **Pointer scan** :
   - En utilisant Cheat Engine avec types big-endian (float big-endian) sur Cemu, scanner la valeur de vie courante (en float ou en quart de cœur) autour de l’appel à `getLife`.
   - Une fois trouvé, effectuer un pointer scan pour remonter aux pointeurs stables (base address + offsets) qui mènent à cette valeur.
2. **AOB scan** :
   - Construire une signature AOB autour du code de `getLife` ou autour du patch "Infinite Hearts".
   - Utiliser cette signature dans ton mod Python pour retrouver à runtime l’adresse de la fonction et, par extension, les structures autour (via pattern scanning dans le module RPX chargé par Cemu).

Exemple de signature AOB (à adapter en pratique, pseudo-code) :

```text
# Autour de getLife (lfs + fctiwz) sur Wii U 1.5.0
xx xx xx xx xx xx xx xx  C0 03 00 64  FC 00 00 1E

C0 03 00 64    ; lfs f0, 0x64(r3)
FC 00 00 1E    ; fctiwz
```

En Python :

- Scanner le module `BotW` (segment .text du RPX dans l’espace mémoire de Cemu) pour ce motif.
- Quand trouvé, calculer l’adresse de la fonction `getLife`.
- Utiliser les offsets connus dans la fonction pour remonter à la structure contenant `life` (via disassembly) ou s’accrocher sur les callsites qui fournissent `r3`.

### 7.4. Intégration dans ton mod externe

Dans ton mod Python :

1. À chaque lancement de BotW dans Cemu :
   - Attacher au process `cemu.exe`.
   - Scanner l’espace mémoire pour le module RPX de BotW (via lecture du mapping mémoire ou heuristique sur le nom du module).
   - Effectuer l’AOB scan pour `getLife` ou la fonction `setLife`/applyDamage.
2. À partir de là :
   - Soit reconstituer la chaîne de pointeurs (plus complexe mais plus propre).
   - Soit effectuer un pointer scan programmatique (plus lourd) pour trouver la valeur HP et ses pointeurs stables.
3. Une fois le pointeur HP stable identifié :
   - Lire périodiquement la valeur (float big-endian à `life+0x64`).
   - Détecter la mort quand elle atteint 0.
   - Écrire HP = 0 pour forcer la mort, en tenant compte des capacités de revive.

## 8. Limites des informations publiques

Les sources publiques (ZeldaMods, zeldaret, cheat tables, randomizer/BCML) donnent :

- Le rôle de `PlayerInfo` (position, hearts, stamina) et son init function Wii U.[web:45]
- Le fonctionnement de GameData, des flags et des save files (`game_data.sav`, max hearts/stamina via flags).[web:59][web:49][web:26]
- Des guides Cheat Engine pour Cemu (big-endian, pointer scans) et des patches infinis (Mipha’s Grace/health).[web:10][web:32][web:66][web:13]

Mais elles **ne publient pas** :

- Une chaîne de pointeurs statique documentée pour l’objet de vie du joueur dans BotW Wii U 1.5.0.
- Les offsets exacts des champs de `PlayerInfo` / `ksys::gdt::Manager` pour le HP courant.

La reconstruction de ces infos reste un travail de reverse local (ton RPX v208 + IDA/Ghidra) et de pointer scan, ce que tu as déjà commencé avec la découverte de `getLife` et de l’offset `+0x64`.

Cela signifie que pour un mod fiable et persistant entre sessions, la meilleure approche concrète est :

- S’appuyer sur **AOB scan** + **pointer scan** dans ton mod externe.
- Utiliser la connaissance qu’`PlayerInfo` et GameDataMgr existent à des adresses d’init connues pour affiner les patterns.

---

Ce fichier ne contient volontairement pas de code complet Python, mais fournit le contexte, les offsets documentés (init function PlayerInfo, structure des saves) et les stratégies (pointer scan, AOB) utilisées par les outils existants, afin que tu puisses les intégrer dans ton propre mod.
