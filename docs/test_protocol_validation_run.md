# BOTWpelago — Protocole de RUN DE VALIDATION V1 (2026-07-13, màj 2026-07-14 soir)

> **Màj 2026-07-14 (post-crash 3e run, révisé après le 4e run)** — comportements NOUVEAUX :
> - **7 locations pré-vraies HORS POOL** (4 sanctuaires du plateau, Grand Plateau Tower, lieu
>   Map Tower07, Souvenir 008 — InitValue=1 posé par le rando à toute nouvelle partie) :
>   AUCUN item n'y est placé (fini le « Paraglider gratuit » du 4e run), le client ne les émet
>   plus, elles n'apparaissent plus dans PopTracker. `ShrinesCleared` démarre à **0** ; un
>   sanctuaire du plateau se suit dans PopTracker via son **LIEU + son COFFRE**.
> - **Gel pré-tablette** : AUCUNE livraison/écriture avant que la **tablette Sheikah** soit en
>   poche. Log : `jeu pas prêt (pré-tablette Sheikah / load en cours)` pendant la cinématique,
>   puis `tablette Sheikah détectée en poche — livraisons AUTORISÉES`. Tant que la tablette
>   n'est pas vue, le client RE-LOCALISE la poche (~20 s) — le 4e run restait collé sur un
>   buffer périmé « confirmé » par une fausse ancre (offset non aligné) → gate jamais levée.
> - **Ancre statique poche** : log attendu à la 1re localisation validée : `ancre statique
>   poche @ host … (offset objet +0x…)` — l'offset doit être ALIGNÉ (multiple de 4) ; aux
>   réallocations : `poche re-suivie via l'ancre statique → …` ; si l'ancre ne suit pas un
>   buffer re-validé : `ancre statique poche incohérente … — re-résolution` (auto-guérison).

Run de bout en bout pour valider les correctifs de cette session **et** le flux complet.
⚠️ = point qui doit être confirmé IN-GAME (impossible hors jeu). Coche au fur et à mesure.

Cible : **profil Cemu du run AP = `80000002`** (celui vers lequel pointe `save_path` de
`~/.botwpelago/config.json`). Les write-tests bruts (ex. confirmer un flag) se font sur
`80000010` uniquement. Réfs : [[project_cemu_save_profiles]], `docs/ingame_test_checklist.md`
(couverture exhaustive), `docs/CHECKLIST.md` (backlog).

---

## 0. Préparation

1. **Terminal A — orchestration** (garde ta save actuelle) :
   ```
   python tools/play_local.py --keep-save
   ```
   → reconstruit l'apworld, génère une seed, extrait le config, reconstruit le pack, puis
   héberge le serveur AP sur `localhost:38281` (bloquant, laisse-le tourner).
   - Si tu veux **repartir de zéro** (save neuve), lance SANS `--keep-save` (⚠️ WIPE la save).
   - Note dans la bannière : le **slot** (défaut `Shorizo`) et la **seed**.

2. **Cemu** : Options ▸ Graphic Packs ▸ coche **BOTWpelago** (UN SEUL pack : build_mod y
   FUSIONNE enforcement paravoile + murs + kit — l'ancien pack séparé « Enforcement »
   n'existe plus). Lance BotW, **charge ta save** (profil `80000002`).
   > Ordre important pour tester le bug du 1er attach : **charge la save AVANT de lancer le
   > client** (l'attache tombe juste après le load, inventaire pas encore stabilisé).

3. **Terminal B — client** (seed neuve → `--reset` pour repartir l'état AP proprement) :
   ```
   python -m BotWClient.BotWClient --name Shorizo --reset
   ```
   > Depuis le 2026-07-13, `--reset` est SANS DANGER en cours de run : la baseline des checks
   > est indexée par seed et n'est plus re-snapshotée à chaque relance (les checks faits
   > pendant un crash/trou de couverture sont ÉMIS à la reconnexion, plus jamais mangés).
   > Relance après crash : la MÊME commande (avec ou sans `--reset`) suffit.

4. (option) PopTracker : ouvre le pack `poptracker/botw-ap-tracker`, connecte l'autotracking
   à `localhost:38281`.

---

## 1. 🔴 CORRECTIF CLÉ — Livraison dès le 1er attach, SANS déco/reco

> Bugs corrigés : (a) au 1er attach juste après un load, la poche fraîchement réallouée
> laissait une copie périmée → `heap_base` décalé → spam `wallet: flagobj hors mapping guest`
> + items non livrés jusqu'à un redémarrage client ; (b) attach pendant la cinématique/save
> neuve → inventaire jamais re-cherché → **rien livré avant relance du client** (run du 13/07) ;
> (c) Cemu relancé après crash → le client ne se ré-attachait pas.

- [ ] ⚠️ Au **premier** connect (client fraîchement lancé, save déjà chargée) : les items de
      départ (**précollectés** : runes, + tout ce que la seed donne au départ) sont livrés
      **LIVE immédiatement**, sans qu'on ait à fermer/relancer le client.
- [ ] ⚠️ Dans les logs du client : **PAS** de `wallet: flagobj hors mapping guest` en boucle.
      Attendu à la place : `Inventaire live localise … (base validée)` puis, au 1er crédit
      rubis, `Portefeuille (storage gdt) @ … = N rubis`.
- [ ] ⚠️ Si l'inventaire vient d'être réalloué : un seul `Inventaire re-localisé (réallocation
      détectée)` puis livraison — jamais de boucle de warnings.
- [ ] ⚠️ Reçois un lot de rubis (le pool en contient) → le **portefeuille monte** dès le 1er
      attach (avant tout sanctuaire).
- [ ] ⚠️ **Ré-attache auto** : lance le client AVANT Cemu (ou tue/relance Cemu en cours de
      run) → dans les 15-20 s après le chargement de la save, log `game_data localise` (ou
      `re-localisé`) et les livraisons repartent SEULES (aucune relance du client).
- [ ] ⚠️ **Partie neuve / cinématique d'intro** : client connecté pendant la cinématique →
      log `[Pending] … inventaire live pas encore localisé (retry auto …)` puis, une fois
      in-game, localisation + livraison AUTOMATIQUES (≤ ~20 s).
- [ ] ⚠️ Les logs de la session sont dans `~/.botwpelago/logs/client-<date>.log` (niveau
      DEBUG) — en cas de pépin, ce fichier est la source du diagnostic.

## 2. Checks sortants (détection)

- [ ] ⚠️ Ouvre un **coffre de sanctuaire** → check AP envoyé **ET** rubis-placeholder retiré.
- [ ] ⚠️ Termine un **sanctuaire / une tour** → check envoyé (selon le mode de goal).
- [ ] ⚠️ **Grand Plateau accessible SANS paravoile** (correctif PopTracker) : sur le tracker,
      la région **Great Plateau** est **verte d'emblée** — ses 16 checks (4 sanctuaires, la
      tour, 6 coffres, + 6 lieux dont *Times Shrine* / Temple du Temps) ne sont PAS rouges.
      Le reste d'Hyrule reste rouge tant que la paravoile n'est pas reçue.
      **NB (2026-07-13)** : le pack de PopTracker vit dans `D:/poptracker/packs/` — il a été
      réinstallé (l'ancien datait d'avant le fix régions, d'où le plateau rouge). **Relance
      PopTracker** et recharge le pack ; après tout rebuild → `build_poptracker.py --install`
      + redémarrage de PopTracker (il verrouille le dossier du pack).

## 3. Toast natif « item reçu » + « item envoyé »

- [ ] ⚠️ À chaque réception (pouch/plat), bandeau **« Vous avez reçu {item} xN. »** en jeu
      (nom localisé, `xN` masqué si 1). Pas de crash, throttle ~4 s.
- [ ] ⚠️ **NOUVEAU** : ouvre un coffre/check qui contient l'item d'un AUTRE monde → bandeau
      **« {item} envoyé à {joueur}. »** (texte libre, même canal). Alternance reçu/envoyé OK
      (la zone MSBT est réécrite à chaque bandeau).
- [ ] ⚠️ **NOUVEAU** : Réceptacle de Cœur / Fiole d'Endurance reçu → bandeau natif (nom
      localisé du jeu) ; en overflow → bandeau « … converti en 500 rubis. »

## 4. 🔴 CORRECTIF — Tenues de région (3 pièces) + mur au reload

> Bug corrigé : les tenues (spec mixte porch+flag) étaient mal routées → ni pièces ni flags
> livrés. Désormais livrées via le mécanisme companion.

- [ ] ⚠️ Reçois une tenue (**Flamebreaker / Snowquill / Vai / Zora**) → les **3 pièces**
      (casque + torse + jambes) apparaissent en poche **live** (log `[Live] Armor_xxx livré`).
      Log client attendu : `[Received] <tenue> (logical — no save injection)` **PAS**
      `[ACTION] Flags écrits — RECHARGE` (l'ancien symptôme).
- [ ] ⚠️ Les 3 pièces sont **équipables** et donnent le bonus de zone.
- [ ] ⚠️ **RECHARGE** la save → le **mur de région** correspondant s'ouvre (téléport ne
      renvoie plus). (Flags `IsGet_Armor_*` reload-gated — normal.)
- [ ] ⚠️ **Arc de Lumière** reçu → l'arc apparaît en poche + (au reload) le mur du Sanctum
      s'ouvre (flag mailbox `TestQuest_Takano_01_Finish`).

## 5. Cap cœurs / endurance + overflow rubis (✅ flags confirmés 2026-07-13)

> Réceptacle de Cœur (6080128) / Fiole d'Endurance (6080129) ajoutés au pool. Montent le max
> jusqu'au plafond du jeu ; au-delà → 500 rubis. **Flags CONFIRMÉS par lecture des saves
> réelles** : cœurs = `MaxHartValue` (s32 ¼-cœurs, 12=3♥ / 36=9♥) ; endurance = `StaminaMax`
> **et** `StaminaCurrentMax` (f32 égaux, 1000 base / 1200 base+1 fiole) — les deux écrits.
> Plus AUCUN diff-saves requis — validation directe dans le run :

- [ ] ⚠️ Reçois un **Réceptacle de Cœur** en dessous du max → bandeau natif + au **reload**,
      +1 cœur (le user du 13/07 : 3 cœurs → 4 cœurs attendus au reload).
- [ ] ⚠️ Reçois-en un **au max (30 cœurs)** → log `au-delà du plafond → +500 rubis`, bandeau
      « converti en 500 rubis », le portefeuille monte de 500, aucun cœur en trop.
- [ ] ⚠️ Idem **Fiole d'Endurance** (+1/5 de roue au reload ; overflow → 500 rubis au max).

## 6. Gates & progression (rappel — voir aussi ingame_test_checklist.md §B)

- [ ] ⚠️ **Paravoile** reçue → on peut quitter le Plateau ; quête « En quête d'Impa » active.
- [ ] ⚠️ **4 Champions** → capacité utilisable après reload. **Master Sword** → équipable.
- [ ] ⚠️ **Runes de départ** fonctionnelles (Magnésis / Stase / Cryonis / Bombe / Caméra).

## 7. Goal / victoire

- [ ] ⚠️ Mode **shrines** : atteindre N sanctuaires → « Goal complete! » envoyé au serveur.
- [ ] ⚠️ Mode **full** : N sanctuaires + 4 Créatures + Master Sword + Arc de Lumière → goal.
- [ ] ⚠️ **À SURVEILLER (constat 2026-07-13)** : sur la save du run (4 sanctuaires du Plateau
      `Clear_Dungeon*` = 1), **`DungeonClearCounter` était encore à 0** dans la save disque.
      Après le prochain sanctuaire terminé, vérifie `--check-flags` : si le compteur ne monte
      toujours pas, le goal « shrines » ne se déclenchera jamais → on basculera le calcul du
      goal sur le comptage des flags `Clear_Dungeon*` (fix trivial côté client).

## 8. Robustesse (surveiller pendant tout le run)

- [ ] ⚠️ **Aucune écriture de `game_data.sav` par le client pendant que Cemu tourne** (dans le
      log Cemu : plus de `FSC: File create failed …`). Mourir → reload **sans crash**.
- [ ] ⚠️ **DeathLink** intact (ne pas y toucher) : mourir → mort envoyée ; recevoir → Link meurt.
- [ ] ⚠️ Grosse rafale (`release all`) → pas de crash, pas de déco AP (1011), pool régénéré au reload.

---

## Après validation (jalon V1)

- [ ] Mettre à jour `_MAX_STAT` avec les flags cœurs/endurance confirmés (si pas déjà fait).
- [ ] Cocher les points validés dans `docs/CHECKLIST.md` + `docs/ingame_test_checklist.md`.
- [ ] Rebuild `BOTWpelago.exe` (`pyinstaller BOTWpelago.spec --noconfirm --clean`).
- [ ] Merge `dev` → `main` (seulement quand TOUTE la checklist V1 est ✅).
