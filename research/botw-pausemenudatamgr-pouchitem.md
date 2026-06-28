# Ajout d’objets d’inventaire en live dans BotW (Wii U 1.5.0, Cemu)

> Objectif : ajouter un objet de type *pouch item* (matériau, nourriture, minerai, etc.) à l’inventaire de Link **en temps réel**, de façon **visible immédiatement** et **persistante après sauvegarde/rechargement**, via un mod externe qui lit/écrit la mémoire du processus Cemu.

---

## 1. Architecture générale de l’inventaire runtime

### 1.1 PauseMenuDataMgr et pouch

Sur BotW, l’inventaire accessible via le menu pause est géré par le singleton `ksys::ui::PauseMenuDataMgr`.[web:1][web:2]

- Namespace : `ksys::ui`.[web:1]
- Classe principale : `PauseMenuDataMgr` (gère les données d’affichage du menu pause, dont le pouch/inventaire).[web:1]
- Cette classe possède des listes d’objets de type `PouchItem` pour chaque catégorie (armes, arcs, boucliers, matériaux, nourriture, etc.).[web:1][web:3]

Les structures pour Switch sont documentées dans le projet de décompilation **zeldaret/botw** et sont largement communes avec la version Wii U 1.5.0 : la logique high‑level (PauseMenuDataMgr, PouchItem, GameData, etc.) est partagée, seuls les offsets binaires et quelques détails d’ABI diffèrent.[web:1][web:4]

### 1.2 PouchItem et listes sead

Les éléments d’inventaire sont représentés par la structure `PouchItem`, stockée dans des listes utilitaires de la lib sead (`sead::OffsetList`, `sead::FreeList`, etc.).[web:1][web:5]

- Chaque `PouchItem` encapsule :
  - L’identifiant d’objet (souvent via un `Item` ou `ItemType` interne, mappé sur le nom de ressource/flag).[web:1][web:3]
  - La quantité / valeur (value1) pour l’objet.[web:3]
  - Des flags d’équipement / data supplémentaire (recipe, equip state, slot index, etc.).[web:3][web:6]

La liste runtime du pouch est synchronisée avec la GameData (`game_data.sav`), mais elle reste une représentation « vivante » utilisée par le moteur (UI, gameplay, sauvegarde).[web:2][web:4]

---

## 2. Structure mémoire de PouchItem (Switch, zeldaret/botw)

> Remarque : les offsets exacts en mémoire diffèrent entre Switch et Wii U, mais la structure logique est identique ; les noms de champs et types sont donc actionnables pour reverse sur Wii U/Cemu.

### 2.1 Définition de base (pseudo‑C)

D’après zeldaret/botw et la documentation communautaire, une structure `PouchItem` ressemble conceptuellement à quelque chose comme :[web:1][web:3][web:5]

```cpp
namespace ksys::ui {

    enum class PouchItemKind : u32 {
        Weapon,
        Bow,
        Shield,
        Armor,
        Material,
        Food,
        KeyItem,
        // ... autres types
    };

    struct PouchItem {
        // Gestion de liste sead
        sead::ListNode mNode;              // 0x00

        // Identifiant d’objet et type
        Item mItem;                        // 0x20 environ
        PouchItemKind mKind;              // type d’objet (material, food...)  

        // Quantité/valeur
        s32 mValue1;                      // valeur principale (quantité, durabilité, etc.)

        // Flags d’équipement / état
        bool mIsEquipped;                 // équipable/équipé
        bool mIsFavorite;                 // marqué comme favori

        // Recipe / data supplémentaire
        s32 mRecipeId;                    // pour les plats cuisinés
        s32 mSlotIndex;                   // position dans le pouch
        // ... autres champs selon le type
    };
}
```

Les prototypes exacts des champs sont dans les headers générés de zeldaret (par ex. `include/ksys/ui/PauseMenuDataMgr.h`, `include/ksys/ui/PouchItem.h`).[web:1][web:3]

### 2.2 Enum de type d’objet

L’enum utilisée pour distinguer les catégories correspond à ceux de la GameData : matériaux, nourriture, armes, etc.[web:3][web:6]

Exemple simplifié :

```cpp
enum class PouchItemKind : u32 {
    Invalid = 0,
    Weapon  = 1,
    Bow     = 2,
    Shield  = 3,
    Armor   = 4,
    Material= 5,
    Food    = 6,
    KeyItem = 7,
    // ...
};
```

Le mapping avec GameData utilise des flags `PorchItem`, `PorchItem_Value1`, `PorchItem_EquipFlag`, `PorchItem_RecipeID`, etc., dont le nom encode la catégorie et l’index.[web:2][web:6]

### 2.3 Listes sead::OffsetList / sead::FreeList

`PauseMenuDataMgr` maintient plusieurs listes de `PouchItem` via les conteneurs sead :[web:1][web:5]

```cpp
class PauseMenuDataMgr {
public:
    sead::OffsetList<PouchItem> mWeaponList;
    sead::OffsetList<PouchItem> mBowList;
    sead::OffsetList<PouchItem> mShieldList;
    sead::OffsetList<PouchItem> mArmorList;
    sead::OffsetList<PouchItem> mMaterialList;
    sead::OffsetList<PouchItem> mFoodList;
    sead::OffsetList<PouchItem> mKeyItemList;
    // ...
};
```

Ces listes sont allouées dans un pool (FreeList) et chaque insertion/suppression passe par des wrappers de PauseMenuDataMgr (`addItem`, `removeItem`, etc.).[web:1][web:5]

---

## 3. Fonctions officielles d’ajout d’objet

### 3.1 API high‑level dans PauseMenuDataMgr

Les fonctions suivantes sont exposées par `PauseMenuDataMgr` dans la décomp Switch :[web:1][web:3]

- `bool addItem(const Item& item, s32 value1, PouchItemKind kind, bool equipFlag, s32 recipeId)`[web:1][web:3]
- `bool addToPouch(const Item& item, s32 value1, PouchItemKind kind)`[web:1]
- `bool createPorchItem(const Item& item, s32 value1, PouchItemKind kind, s32 recipeId)`[web:3]
- Fonctions auxiliaires pour la cuisine, la fusion d’items, etc. (`cookItem`, `onPickupItem`, etc.).[web:3][web:6]

Ces fonctions :[web:1][web:3]

1. Créent ou récupèrent un `PouchItem` dans la liste runtime appropriée.
2. Mettront à jour les flags GameData (`PorchItem*`) via des appels à `GameDataMgr`.
3. Notifieront les systèmes d’UI / autosave qu’un changement d’inventaire s’est produit.

### 3.2 Signature et appel depuis un mod externe

Sur Wii U 1.5.0, les signatures réelles au niveau binaire respectent l’ABI PowerPC C++ (this‑call via r3, arguments suivants dans r4+).[web:4][web:7]

En pratique pour un mod externe qui injecte un appel :

- `this` : pointeur vers le singleton `PauseMenuDataMgr`.
- `item` : structure ou ID, souvent initialisée via une fonction type `Item::setByName(const sead::SafeString&)` ou via un ID numérique.[web:1][web:3]
- `value1` : quantité ou valeur (ex. 1 unité de minerai, durabilité pour une arme).[web:3]
- `kind` : `PouchItemKind` correspondant.[web:3]
- `equipFlag` : booléen (équipé immédiatement ou non).[web:3]
- `recipeId` : 0 pour les matériaux classiques, valeur >0 pour une recette de nourriture.[web:6]

Pseudo‑prototype côté Wii U :

```cpp
bool PauseMenuDataMgr::addItem(const Item& item, s32 value1,
                               PouchItemKind kind, bool equipFlag,
                               s32 recipeId);
```

### 3.3 Comment déclencher l’appel (Cemu, PowerPC)

Depuis ton mod externe (processus séparé) :[web:7][web:8]

1. **Résoudre l’adresse de PauseMenuDataMgr singleton** :
   - Via pointer path / AOB scan sur le binaire `code` de BotW (RPX), en se basant sur les signatures trouvées dans des cheat tables ou trainers existants.[web:7][web:8]
   - Souvent accessible via une global dans `ksys::ui` ou `SystemPause`.

2. **Résoudre l’adresse de la fonction `addItem`** :
   - En partant des symboles de la version Switch (zeldaret) et en utilisant des patterns d’assembly comparés sur Wii U.[web:1][web:4]
   - Des threads GBAtemp/Cemu fournissent des AOB de fonctions d’ajout d’objets, utilisées par des trainers.[web:7][web:8]

3. **Injecter un stub PowerPC** :
   - Allouer un petit bloc de code dans la mémoire du processus Cemu (via WriteProcessMemory).[web:7]
   - Y écrire un stub qui :
     - charge le pointeur `this` (PauseMenuDataMgr) dans r3 ;
     - prépare `Item`, `value1`, `kind`, etc. dans r4+ ;
     - branche vers `addItem` ;
     - retourne au jeu.

4. **Déclencher le stub depuis le thread du jeu** :
   - En patchant une instruction de code (par ex. un NOP dans la boucle de frame) pour brancher sur ton stub, ou en utilisant un hook déjà existant.[web:7][web:8]

En résumé : pour obtenir une persistance correcte, il est recommandé d’appeler les fonctions officielles (`addItem`/`addToPouch`) plutôt que de créer manuellement des nœuds `PouchItem`.[web:1][web:3][web:6]

> Les offsets exacts Wii U 1.5.0 sont spécifiques au build ; ils sont généralement documentés dans des tables de cheats et trainers (voir section 5).[web:7][web:8]

---

## 4. Synchronisation runtime ↔ GameData

### 4.1 GameDataMgr et flags PorchItem

Les données de sauvegarde (game_data.sav) sont gérées par un manager global (`GameDataMgr` / `GameData`) qui expose des accès par nom de flag (`PorchItem`, `PorchItem_Value1`, etc.).[web:2][web:6]

- `PorchItem` : nom / ID d’objet.
- `PorchItem_Value1` : quantité / valeur principale.
- `PorchItem_EquipFlag` : état équipé/non équipé.
- `PorchItem_RecipeID` : recette pour les plats.[web:2]

La liste runtime dans `PauseMenuDataMgr` est reconstruite à partir de ces flags au chargement, et les modifications runtime sont reflétées dans ces tableaux lors des sauvegardes ou lors de certains événements (pickup, cuisine, drop, etc.).[web:2][web:4]

### 4.2 Quand la synchronisation se produit

D’après la documentation ZeldaMods et l’observation de mods existants :[web:2][web:6][web:7]

- **Au chargement de la partie** :
  - `GameDataMgr` lit `game_data.sav`.
  - `PauseMenuDataMgr` reconstruit ses listes de `PouchItem` à partir des flags `PorchItem*`.

- **Lors d’une modification via API interne** (`addItem`, `onPickupItem`, `cookItem`) :
  - La modification est écrite dans la liste runtime.
  - Les flags GameData correspondants sont mis à jour via des appels internes.

- **Lors de l’auto‑save / save manuel** :
  - Le moteur parcourt les listes runtime et sérialise les `PouchItem` vers les tableaux GameData avant d’écrire `game_data.sav`.[web:2]

### 4.3 Conséquences pour ton mod

- **Écrire directement dans le buffer GameData en mémoire pendant le jeu** ne suffit pas :
  - Le moteur considère la liste runtime comme source de vérité et peut écraser le buffer lorsque la synchronisation se produit (autosave, changement d’onglet d’inventaire, etc.).[web:2][web:6]

- **Ajouter un objet uniquement dans la liste runtime** (en manipulant les structures `PouchItem` sans passer par `addItem`) crée un nœud « fantôme » non sérialisé :
  - Il n’est pas pris en compte lors du parcours de sauvegarde.
  - Il disparaît au rechargement.[web:2][web:7]

- Pour avoir **persistance + apparition instantanée**, il faut :
  1. Soit appeler la fonction interne correcte (`addItem`/`addToPouch`) qui gère la double écriture runtime + GameData.[web:1][web:3]
  2. Soit :
     - Écrire les flags GameData (`PorchItem*`) **et**
     - Forcer une re‑synchronisation GameData→runtime en invoquant la fonction interne de reconstruction (non documentée, mais accessible via reverse).[web:2][web:6]

En pratique, la solution (1) est beaucoup plus fiable et alignée avec ce que font les outils existants.[web:6][web:7]

---

## 5. Listes complètes des tableaux GameData d’inventaire

### 5.1 Format général des `PorchItem*`

La documentation **ZeldaMods – Save File Format** décrit le format des tableaux d’inventaire :[web:2][web:6]

- `PorchItem` : tableau de noms de flags (identifiants d’objets) pour chaque slot du pouch.[web:2]
- `PorchItem_Value1` : tableau d’entiers (quantités/durabilité) aligné sur `PorchItem`.[web:2]
- `PorchItem_EquipFlag` : tableau de booléens (équipé/mis en favori).[web:2]
- `PorchItem_RecipeID` : tableau d’entiers (ID de recette pour les plats).[web:2]

Chaque index de slot correspond à une entrée dans chacun de ces tableaux ; pour ajouter un objet proprement uniquement via GameData, il faut écrire **toutes** les colonnes nécessaires :[web:2][web:6]

1. `PorchItem[i]` = nom de l’objet (flag ID, ex. `Item_Ore_L` pour un diamant).[web:6]
2. `PorchItem_Value1[i]` = quantité (pour les matériaux) ou valeur spécifique pour d’autres types.[web:2]
3. `PorchItem_EquipFlag[i]` = 0 ou 1 selon l’état désiré.[web:2]
4. `PorchItem_RecipeID[i]` = 0 pour les matériaux, ID >0 pour une nourriture spécifique.[web:2]

### 5.2 Tables d’autres catégories

ZeldaMods liste également des tableaux spécifiques pour :[web:2][web:6]

- Armes, arcs, boucliers, armures :
  - `WeaponPorchItem`, `WeaponPorchItem_Value1`, etc.
  - `BowPorchItem`, `ShieldPorchItem`, etc.

Les noms précis dépendent de la catégorie ; la logique reste : un tableau de noms + tableaux de valeurs et flags alignés par index.[web:2]

Pour un mod multi‑catégorie, il faut déterminer la catégorie de l’objet cible et écrire dans les tableaux correspondants.[web:2][web:6]

---

## 6. Outils existants et méthodes utilisées

### 6.1 Trainers, cheat tables, randomizer

Plusieurs outils existants ajoutent des objets dans l’inventaire **en live** sur Cemu :[web:7][web:8][web:9]

- Trainers / tables Cheat Engine pour BotW (Wii U/Cemu) disponibles sur les forums GBAtemp et FearLess Cheat Engine.[web:7][web:8]
- Éditeurs de sauvegarde BotW (ex. `botw-tools` par MrCheeze) qui manipulent `game_data.sav` hors jeu.[web:9]
- BotW Randomizer (principalement Switch, mais l’approche est similaire).[web:4][web:9]

Les patterns observés :[web:7][web:8][web:9]

1. **Éditeurs de sauvegarde classiques** (botw‑tools) :
   - Lisent et écrivent uniquement `game_data.sav`.
   - Ne gèrent pas l’ajout en live ; ton expérience du menu titre + reload est conforme à cette approche.[web:2][web:9]

2. **Trainers et cheat tables live** :
   - Utilisent des pointer paths / AOB scans pour trouver les structures runtime de l’inventaire et parfois des fonctions internes.[web:7][web:8]
   - Deux approches principales :
     - Patch direct de GameData en mémoire puis forcer un reload de la partie (moins commun).[web:7]
     - Appel (ou simulation) de la fonction d’ajout d’objet via injections de code / script Lua pour CE.[web:8]

3. **BotW Randomizer / multiworld** :
   - Sur Switch (via Atmosphère, etc.), il est fréquent de hooker les fonctions de pickup / addItem pour injecter des objets supplémentaires.[web:4]
   - L’équivalent sur Wii U/Cemu consiste à :
     - Hooker `ksys::ui::PauseMenuDataMgr::addItem` ou une fonction proche.
     - Appeler cette fonction avec les paramètres désirés quand un événement externe (multiworld) se produit.[web:4][web:7]

### 6.2 Pointer paths et AOB pour PauseMenuDataMgr

Des pointer paths/AOBs documentés pour trouver le singleton `PauseMenuDataMgr` et la liste d’inventaire peuvent être extraits des scripts CE et trainers :[web:7][web:8]

- Les tables BotW pour CE contiennent souvent :
  - Une entrée « Inventory Pointer » ou « Pouch Items ».[web:7]
  - Un AOB pour la fonction qui parcourt la liste d’objets au moment de l’affichage du menu pause.[web:8]

- En pratique, tu peux :
  1. Télécharger une table CE BotW Wii U/Cemu.[web:7]
  2. Inspecter les scripts/AOBs pour trouver :
     - L’adresse base du module RPX.
     - Les signatures d’instructions qui correspondent à des boucles sur les `PouchItem`.
  3. Reproduire ces AOBs dans ton mod en C++ et effectuer un scan mémoire pour obtenir les addresses de :
     - `PauseMenuDataMgr`.
     - Les listes de `PouchItem`.
     - La fonction `addItem` (ou une fonction voisine), via pattern sur son prologue/epilogue.[web:7][web:8]

### 6.3 Cas MrCheeze / botw-tools

`botw-tools` de MrCheeze est principalement orienté manipulation de sauvegarde hors ligne :[web:9]

- Il parse `game_data.sav` conformément à la doc ZeldaMods et modifie `PorchItem*`.
- Il ne couvre pas les aspects runtime/Hook ; tu peux toutefois t’en servir pour valider que les flags que tu écris correspondent bien à des objets valides et persistent.[web:2][web:9]

---

## 7. Stratégie recommandée pour ton mod

### 7.1 Approche « propre » via PauseMenuDataMgr::addItem

Pour ton cas (multiworld, objets envoyés en continu, apparition instantanée, persistance), la voie la plus robuste est :[web:1][web:3][web:6][web:7]

1. **Reverse et résolution d’adresses** :
   - Utiliser zeldaret/botw pour obtenir les signatures de `PauseMenuDataMgr` et `addItem` côté Switch.[web:1][web:4]
   - Utiliser des AOB/CE trainers pour mapper ces signatures sur Wii U 1.5.0 (v208) et déterminer les offsets dans le RPX.[web:7][web:8]

2. **Localiser le singleton PauseMenuDataMgr** :
   - Via pointer path/AOB.
   - Stocker l’adresse dans ton mod pour utilisation ultérieure.

3. **Construire un stub PowerPC dans la mémoire du jeu** :
   - Écrire un petit bout de code qui :
     - prépare `Item` (par nom ou ID), `value1`, `kind`, etc. ;
     - appelle `PauseMenuDataMgr::addItem` ;
     - retourne.

4. **Déclencher le stub lorsque tu reçois un objet depuis le multiworld** :
   - Depuis ton mod, via WriteProcessMemory, tu écris les paramètres dans un buffer de données partagé et tu forces le jeu à exécuter le stub (patch de branche, hook, etc.).

Cette approche garantit :[web:1][web:3][web:6]

- Apparition immédiate dans l’inventaire (liste runtime mise à jour).
- Persistance après save/reload (GameData mise à jour via la fonction interne).
- Compatibilité avec toutes les mécaniques (autosave, UI, tri, drop, etc.).

### 7.2 Approche alternative via GameData + re‑sync

Si tu ne veux/peux pas appeler `addItem`, une autre approche — plus fragile — est :[web:2][web:6][web:7]

1. Écrire les flags GameData (`PorchItem*`) pour l’objet ciblé dans un slot libre.
2. Appeler la fonction interne de reconstruction du pouch (utilisée au chargement de la partie) en la trouvant via reverse/AOB.

Cela force une synchronisation GameData→runtime et fait apparaître l’objet, mais :[web:2][web:6]

- tu dois t’assurer qu’aucune autre logique n’écrase tes modifications ;
- la mise à jour n’est pas forcément instantanée visuellement (selon quand la reconstruction est appelée).

---

## 8. Pistes concrètes de reverse et sources

### 8.1 zeldaret/botw (Switch 1.5.0)

- GitHub `zeldaret/botw` : headers et décomp partielle pour `ksys::ui::PauseMenuDataMgr`, `PouchItem`, `GameDataMgr`.[web:1][web:4]
- Utiliser ces fichiers pour :
  - comprendre les signatures des fonctions ;
  - identifier les noms exacts de champs (kind, value1, flags, recipeId, etc.) ;
  - trouver quels appels écrivent dans GameData.

### 8.2 ZeldaMods – Save File Format

- Documentation du format de `game_data.sav`.[web:2]
- Détail des tableaux `PorchItem*`, mapping des noms d’objets, types et champs.[web:2][web:6]

### 8.3 Cheat tables / trainers Cemu BotW

- Forums GBAtemp, FearLess Cheat Engine : tables CE pour BotW Wii U/Cemu avec pointers et AOBs vers l’inventaire.[web:7][web:8]
- Utiliser ces tables pour récupérer :
  - pointer paths vers le pouch ;
  - signatures d’instructions pour la fonction d’ajout d’item.

### 8.4 MrCheeze / botw-tools

- Outils pour manipuler les sauvegardes, utiles pour valider les modifications sur `game_data.sav`.[web:9]

En combinant ces sources, tu peux dériver :[web:1][web:2][web:4][web:7]

- La structure exacte de `PouchItem` côté Wii U (via analyse d’objets connus et comparaison avec Switch).
- Les offsets d’instances dans `PauseMenuDataMgr`.
- Les signatures AOB de `addItem` et fonctions de synchronisation.

---

## 9. Résumé opérationnel

1. **Ne pas créer manuellement des PouchItem fantômes** : ils ne sont pas sérialisés et disparaissent.[web:2][web:7]
2. **Ne pas se contenter d’écrire GameData en live** : le moteur resynchronise à partir de la liste runtime et peut écraser tes changements.[web:2][web:6]
3. **Utiliser les fonctions internes de PauseMenuDataMgr (`addItem`/`addToPouch`)** pour toute insertion d’objet live que tu veux persistante.[web:1][web:3][web:6]
4. **Pour un multiworld** :
   - hooker ou appeler `addItem` via un stub injecté dans le code PPC du jeu ;
   - résoudre le singleton `PauseMenuDataMgr` et les signatures des fonctions via zeldaret + cheat tables.
5. **En cas de besoin de fallback** : écrire tous les tableaux `PorchItem*` et forcer une re‑construction du pouch à partir de GameData.[web:2][web:6]

Ce fichier fournit la cartographie conceptuelle (classes, fonctions, champs, mécanisme de sync) et les pistes de reverse (zeldaret, ZeldaMods, CE trainers, botw‑tools) nécessaires pour que tu puisses implémenter un ajout d’objets d’inventaire en live sur BotW Wii U 1.5.0 sous Cemu, avec persistance et intégration propre dans le moteur.
