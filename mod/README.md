# mod/ — BOTWpelago V2 : mod Cemu (graphic pack)

Composant **optionnel** du multiworld : un graphic pack Cemu qui durcit les règles en jeu.
Le client Python (V1) fonctionne entièrement sans lui.

## Règle légale (absolue)

**Rien de dérivé du jeu n'entre dans ce repo.** Ce dossier ne contient que NOS scripts.
Les fichiers du jeu sont lus depuis le **dump local du joueur** (chemins de
`~/.botwpelago/config.json`) au moment du build, et le pack produit va dans
`graphicPacks/` (hors repo). Décompiler des mods tiers = pour apprendre, jamais
redistribuer.

## Contenu

| Fichier | Rôle |
|---------|------|
| `build_mod.py` | Construit + installe le pack `BOTWpelago_Enforcement` (`--check` = dry-run sans écriture) |
| `patches/paraglider.py` | Patch 1 : retire le grant paravoile vanilla (voir ci-dessous) |
| `scan_flows.py` | Recherche : scanne TOUS les `.bfevfl` du dump pour des motifs (actions/flags/acteurs) |
| `dump_flow.py` | Recherche : dissèque un `.bfevfl` (entry points, chaînes d'events, params) |

## Pipeline de build

```
dump local (update/base/dlc)                    ~/.botwpelago/config.json
        │ oead : Yaz0 → SARC big-endian (mode Legacy Wii U au repack)
        ▼
.bfevfl  ──evfl──►  transform() du patch  ──►  ré-écriture  ──►  RE-parse + verify()
        │                                                        (post-condition)
        ▼
graphicPacks/BOTWpelago_Enforcement/{rules.txt, content/Event/…}
```

Round-trip evfl validé **octet-identique** sur `FindDungeon.bfevfl` (v208 EUR) — toute
différence en sortie vient donc du patch, pas de la sérialisation.

## Patch 1 — enforcement paravoile (construit, à valider in-game)

**Trouvé par `scan_flows.py`** : `PlayerStole2` n'apparaît que dans 4 flows du jeu :
- `Event/FindDungeon.sbeventpack/EventFlow/FindDungeon.bfevfl` — **LE grant** :
  `Event65 = SubFlow GetDemo::GetItemByName(CheckTargetActorName=PlayerStole2)`
  dans la scène du Roi sur le toit du Temple du Temps (2 entry points partagent la chaîne).
- `Event/Demo027_0.sbeventpack` — le paravoile comme *accessoire* de cinématique
  (`Demo_EventBind` sur la main du Roi), pas un grant.
- `Pack/TitleBG.pack/EventFlow/Demo042_0.bfevfl` — `CheckFlag(IsGet_PlayerStole2)`
  (branche selon possession), pas un grant.
- `Pack/Bootup.pack/EventFlow/Tips{Player,GameOver}.bfevfl` — tips conditionnels.

**Le patch** excise `Event65` (les prédécesseurs sont rebranchés sur son successeur).
Toute la scène reste intacte : dialogues, `Demo_AdvanceQuest(FindDungeon)`,
`FlagON GanonQuest_Activated / Find_Impa_Activated`, `AutoSave` — mais le paravoile
n'est plus jamais donné par le jeu : il n'arrive **que** par Archipelago.

**À valider in-game** : finir le plateau avec le pack activé → la scène du Roi se joue
sans popup paravoile, la quête avance, et `IsGet_PlayerStole2` reste à 0 jusqu'à
réception AP.

## Primitives confirmées (pour les prochains patches)

Convention d'appel réelle de la primitive « donner N items + popup natif » (relevée sur
des appelants du jeu : `KorokMini_KorokShiren`, `MiniGame_HorsebackArchery`, etc.) :

```
SubFlow GetDemo::GetManyItemsByName
    IncreaseTargetActorName = <actor à ajouter>       (ex Item_Mushroom_N)
    GetNumber               = <quantité>
    ShowDialogTargetActorName = <actor affiché>       (peut différer, ex Obj_ArrowBundle_A_10)
    CheckTargetActorName    = <actor>                 (optionnel)
    IsInvalidOpenPouch      = False
```

Autres actions vues dans `FindDungeon` directement réutilisables :
- `EventSystemActor.Demo_WarpPlayer(WarpDestMapName, WarpDestPosName)` — **la primitive
  de la gate-par-téléport** (idée V2 « façon forêt perdue »).
- `EventSystemActor.Demo_FlagON(FlagName)` / `CheckFlag(FlagName)` (query Switch).
- `EventSystemActor.Demo_CallDemo(DemoName)` / `Demo_AdvanceQuest(QuestName)` /
  `Demo_AutoSave`.

## Roadmap (voir docs/CHECKLIST.md § V2)

1. **[fait, à valider in-game]** Enforcement paravoile.
2. **Gate Ganon** : conditionner l'entrée du combat final (localiser le flow d'entrée,
   `scan_flows.py --patterns Ganon`).
3. **Popup natif « item reçu »** : la route « écriture externe d'un flag → popup
   instantané » est FERMÉE (testé, cf. docs/status.md §Tips). La route ouverte :
   patcher un flow **naturellement récurrent** (dialogue PNJ fréquent, autosave…) pour
   `CheckFlag(mailbox) → SubFlow GetDemo::GetManyItemsByName → Demo_FlagOFF(mailbox)`.
   Le client écrit le flag mailbox (write gd_base prouvé) ; la livraison se fait au
   prochain déclenchement naturel. Questions ouvertes : choix du flow porteur, passage
   du NOM d'item (params EventFlow = statiques → une entrée par item clé, ou mailbox
   à N flags).
4. **Gate région par téléport** : `Demo_WarpPlayer` + message (cf. mod DAR pour le
   blocage conditionnel — à décompiler pour apprendre, ré-implémenter ensuite).
5. Icônes/noms custom (BFRES/MSBT — Switch Toolbox, `--be`), cap cœurs/endurance,
   coffres-locations.
