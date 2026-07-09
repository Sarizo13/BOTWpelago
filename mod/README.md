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
| `scan_map.py` | Recherche : liste les actors déclencheurs des map units MainField (résout aussi les `_Static.smubin` packés dans TitleBG.pack) |

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
4. **Gate région par téléport — MÉCANISME VANILLA DÉCODÉ (2026-07-09), recette complète** :
   le champ contient **543 `EventTag`** (dans les `_Static.smubin`, packés dans TitleBG.pack)
   câblés ainsi (chaîne remontée sur `Wind_Relic_Contact_Retry`, B-3) :

   ```
   Area (volume invisible : Shape=Sphere/Capsule/Box, Scale = taille)
     --BasicSig--> LinkTagOr / LinkTagAnd   (logique booléenne ; peut lire/poser des
     |             SaveFlag GameData directement dans la couche map !)
     --BasicSig--> EventTag {EventFlowName, EventFlowEntryName, LaunchEventByOnSignal}
                   → lance l'entry point du flowchart nommé
   ```

   Recette du patch « zone gate » (tout est à NOUS, aucun merge complexe) :
   1. `Event/BOTWpelago_Gate.sbeventpack` (NOUVEAU fichier) : flowchart avec un entry
      point par région — `CheckFlag(IsGet_Armor_XXX_*)` → si absent :
      `Demo_Talk(message)` + `Demo_WarpPlayer(dest sûre)` ; sinon rien.
   2. Enregistrer chaque entry dans `Bootup.pack//Event/EventInfo.product.sbyml` :
      `BOTWpelago_Gate<Gate_Eldin> = {is_timeline: false, mode: "Seamless",
      subfile: [{file: "Common.bfevfl"}]}` (schéma relevé sur les 5 784 entrées vanilla).
   3. Poser `Area` + `EventTag` aux entrées de région dans le `_Dynamic.smubin` du carré
      (fichier LIBRE → remplaçable par graphic pack sans toucher TitleBG.pack).
   4. Message : entrée MSBT `EventFlowMsg/BOTWpelago_Gate.msbt` (texte à nous) dans le
      pack de langue ; PoC possible sans message (fade + warp suffisent à prouver).
   5. Condition côté client : poser les flags `IsGet_Armor_*` (360 existent, un par
      pièce) à la livraison des sets AP.

   Le mod DAR n'est plus nécessaire comme référence (mécanisme vanilla plus complet).

   **PROTOTYPE CONSTRUIT (`patches/zone_gate.py`, v2 — à tester in-game)** :
   gate d'Eldin à l'entrée de la Montagne de la Mort (2404, 230, −1320, rayon 45 m) ;
   sans `IsGet_Armor_011_Upper` (plastron Flamebreaker) → warp au Relais du Pied-de-Mont.
   Produit : `Event/BOTWpelago_Gate.sbeventpack` (flowchart from scratch, 4 events),
   `Pack/Bootup.pack` (EventInfo + `BOTWpelago_Gate<Gate_Eldin>`), `Pack/TitleBG.pack`
   (chaîne Area/LinkTagOr/EventTag dans `H-3_Static.smubin`, HashIds crc32 uniques).

   **Leçons du 1er test in-game (échec, corrigé)** :
   - **Un seul pack Cemu.** Le pack rando ET le pack enforcement shippaient chacun
     `Pack/Bootup.pack` → conflit, notre EventInfo pouvait ne jamais charger. build_mod
     fusionne désormais dans le pack rando `BOTWpelago` (sources layerées : les modifs
     du rando sont préservées) et supprime l'ancien pack séparé. `pack_builder`
     ré-applique automatiquement les patches après chaque régénération de seed.
   - **Les triggers vont dans les `_Static.smubin` (packés dans TitleBG.pack)** : tous
     les chaînages vanilla y vivent ; une Area posée dans le `_Dynamic` libre ne s'est
     pas déclenchée.

   **VALIDÉ IN-GAME (v3)** : le warp se déclenche (couche AOC). Leçon supplémentaire :
   avec le DLC monté le jeu lit les map units depuis l'**aoc** — patcher TitleBG ne
   suffit pas ; et la RSTB doit être mise à jour pour toute ressource modifiée/ajoutée
   (crash au boot sinon — `update_rstb` dans build_mod).

   **v4 (feedback user)** : le TP sec devient une séquence vanilla-like —
   `CheckPlayerRideHorse → Demo_PlayerHorseGetOff` (cheval), `Demo_StopInAir` (coupe
   paravoile/chute), `Fader.Demo_FadeOut(30)` → warp → `Demo_FadeIn(30)` →
   `Demo_OpenMessageTips(EventFlowMsg/BOTWpelago_Gate:Gate_NoGear)`. Le message vit
   dans un **MSBT custom** (`mod/msbt.py`, writer BE minimal LBL1+ATR1+TXT2 calqué sur
   le format vanilla) injecté dans les 7 `Pack/Bootup_EU*.pack` (FR réel, EN ailleurs).

   **Étape suivante — murs de frontière par région** (tracés fournis par le user) :
   générateur de polylignes → chaîne de boîtes `Area` (Shape=Box, hautes de ~400 m
   pour bloquer le paravoile, se recouvrant) → un `LinkTagOr` par mur → un `EventTag`
   par région ; un entry point par région dans `BOTWpelago_Gate.bfevfl` (flag d'armure
   + warp propres à chaque zone). Données : polylignes en JSON committables.
5. Icônes/noms custom (BFRES/MSBT — Switch Toolbox, `--be`), cap cœurs/endurance,
   coffres-locations.
