# BOTWpelago — Protocole de RUN DE VALIDATION V1 (2026-07-13)

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

2. **Cemu** : Options ▸ Graphic Packs ▸ coche **BOTWpelago** (et **BOTWpelago_Enforcement**
   si tu testes les murs de région). Lance BotW, **charge ta save** (profil `80000002`).
   > Ordre important pour tester le bug du 1er attach : **charge la save AVANT de lancer le
   > client** (l'attache tombe juste après le load, inventaire pas encore stabilisé).

3. **Terminal B — client** (seed neuve → `--reset` pour repartir l'état AP proprement) :
   ```
   python -m BotWClient.BotWClient --name Shorizo --reset
   ```

4. (option) PopTracker : ouvre le pack `poptracker/botw-ap-tracker`, connecte l'autotracking
   à `localhost:38281`.

---

## 1. 🔴 CORRECTIF CLÉ — Livraison dès le 1er attach, SANS déco/reco

> Bug corrigé : au 1er attach juste après un load, la poche fraîchement réallouée laissait une
> copie périmée → `heap_base` décalé → spam `wallet: flagobj hors mapping guest` + items non
> livrés jusqu'à un redémarrage client.

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

## 2. Checks sortants (détection)

- [ ] ⚠️ Ouvre un **coffre de sanctuaire** → check AP envoyé **ET** rubis-placeholder retiré.
- [ ] ⚠️ Termine un **sanctuaire / une tour** → check envoyé (selon le mode de goal).
- [ ] ⚠️ **Grand Plateau accessible SANS paravoile** (correctif PopTracker) : sur le tracker,
      la région **Great Plateau** est **verte d'emblée** — ses 16 checks (4 sanctuaires, la
      tour, 6 coffres, + 6 lieux dont *Times Shrine* / Temple du Temps) ne sont PAS rouges.
      Le reste d'Hyrule reste rouge tant que la paravoile n'est pas reçue.

## 3. Toast natif « item reçu »

- [ ] ⚠️ À chaque réception (pouch/plat), bandeau **« Vous avez reçu {item} xN. »** en jeu
      (nom localisé, `xN` masqué si 1). Pas de crash, throttle ~4 s.

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

## 5. 🔴 NOUVEAU — Cap cœurs / endurance + overflow rubis (⚠️ constantes à confirmer)

> Réceptacle de Cœur (6080128) / Fiole d'Endurance (6080129) ajoutés au pool. Montent le max
> jusqu'au plafond du jeu ; au-delà → 500 rubis. **Le flag de max-PV n'est pas confirmé** pour
> cette version (`Item_LifeMaxUp` absent du dump) → tant qu'il ne l'est pas, un Réceptacle
> donne 500 rubis + un log « à confirmer » (jamais de perte, jamais d'écriture hasardeuse).

**Confirmer les flags (sur `80000010`, à part du run)** :
1. En jeu, note l'état, **sauvegarde** → copie `game_data.sav` en `av.sav`.
2. Ramasse/obtiens **1 réceptacle de cœur** (statue de la déesse, 4 orbes) et **1 fiole
   d'endurance**, **sauvegarde** → copie en `ap.sav`.
3. Diff :
   ```
   python -m BotWClient.BotWClient --diff-saves av.sav ap.sav
   ```
4. Repère le flag s32 qui monte de **+4** (cœur : le vrai nom du max-PV) et le f32 de
   `StaminaMax` (échelle/plafond) → mets à jour `_MAX_STAT` dans
   `BotWClient/providers/save_file.py` (clé `heart.flag`, `stamina.per_unit`, `.cap`).

**Puis, dans le run** :
- [ ] ⚠️ Reçois un **Réceptacle de Cœur** en dessous du max → au **reload**, +1 cœur.
- [ ] ⚠️ Reçois-en un **au max (30 cœurs)** → log `au-delà du plafond → +500 rubis`, le
      portefeuille monte de 500, aucun cœur en trop.
- [ ] ⚠️ Idem **Fiole d'Endurance** (roue au reload ; overflow → 500 rubis au max).
- [ ] ⚠️ **Avant confirmation du flag cœurs** : un Réceptacle donne 500 rubis + log
      `max 'Item_LifeMaxUp' introuvable/hors plage … À CONFIRMER IN-GAME` (comportement SÛR).

## 6. Gates & progression (rappel — voir aussi ingame_test_checklist.md §B)

- [ ] ⚠️ **Paravoile** reçue → on peut quitter le Plateau ; quête « En quête d'Impa » active.
- [ ] ⚠️ **4 Champions** → capacité utilisable après reload. **Master Sword** → équipable.
- [ ] ⚠️ **Runes de départ** fonctionnelles (Magnésis / Stase / Cryonis / Bombe / Caméra).

## 7. Goal / victoire

- [ ] ⚠️ Mode **shrines** : atteindre N sanctuaires → « Goal complete! » envoyé au serveur.
- [ ] ⚠️ Mode **full** : N sanctuaires + 4 Créatures + Master Sword + Arc de Lumière → goal.

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
