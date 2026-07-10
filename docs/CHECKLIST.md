# BOTWpelago — Checklist

> État consolidé du projet. Tout est **V1** sauf les gros chantiers **V2** (différés).
> Coche au fil de l'eau. Source de vérité pour « ce qu'il reste à faire ».

---

## ✅ Fait & validé

- [x] Détection des checks : sanctuaires, tours, créatures, lieux, quêtes, souvenirs (save-poll + hash CRC32)
- [x] Gate paravoile + rétention de flags + goal 2 modes (sanctuaires / full)
- [x] DeathLink (validé — **ne pas toucher**)
- [x] Injection live d'items instantanée + persistante : matériaux, flèches, armes, arcs, boucliers, armures
- [x] Master Sword + tenues de Champion (sets complets)
- [x] Placement trié (décroissant par adjacence réelle) · durabilité ×100 · ItemUse · flag équipé
- [x] Catégorie vide : livré + persisté, visible au reload (log clair)
- [x] Crash contention fichier corrigé (lecture/écriture via mémoire quand attaché)
- [x] Rubis strip désactivé (adresse miroir) · loot diversifié (+184 armes, −Spirit Orbs)
- [x] Overlay desktop « item reçu »
- [x] play_local.py (génère + serveur + wipe save) · orchestration BOTWpelago (pack_builder + GUI)

---

## 🔲 V1 — tout le reste

### Finir le jalon / release
- [ ] Rebuild `BOTWpelago.exe` (inclure `mod/` + deps oead/evfl/rstb) + merge `dev` → `main`
- [ ] Validation end-to-end : une vraie run AP multi-slot complète
- [x] TODO-7 : `region` rempli — et ALIGNÉ sur les murs physiques V2 (tools/assign_regions.py,
      polygones = murs par construction ; régions Zora/Gerudo ajoutées au graphe)
- [x] **Garde absolue anti-écriture-save (2026-07-10)** : `cemu_process_running()` verrouille
      TOUTES les voies fichier (`_inject_pending`, `_enforce_retention`, `_bank_spirit_orbs`,
      `can_inject_now`) — un bridge décroché avec Cemu en vie n'ouvre plus jamais la voie
      fichier (cause du crash « item inséré en save » du 2026-07-09)

### Loot & rubis (ex-V1.1)
- [x] Rareté du loot : 4 tiers (common ×8 / uncommon ×4 / rare ×2 / epic ×1) assignés par
      mots-clés dans `build_loot_table.py` ; quantités plafonnées (rare ≤ 2, epic = 1) ;
      specials rescalés (~14 % du tirage). Vérifié sur seed : 50/17/11/1.5 %.
- [~] Rubis : **vrai portefeuille TROUVÉ + prouvé** (2026-07-10, `tools/hunt_wallet.py`
      snap/narrow/probe/context : écrit 55555 → achat −60 → écran 55495 = le jeu débite depuis
      cette adresse ; l'AOB actuel visait un miroir). Reste : localisateur STABLE (hypothèse =
      value+0x14 d'un nœud PouchItem "Money" → scan de nœuds) puis câbler `live_add_rupees`.
- [x] CookData (plats/potions type 8) **décodé** (2026-07-10) : +0x68 soin, +0x6C durée, +0x70 prix,
      +0x74 type d'effet (f32), +0x78 niveau/quantité — vérifié sur 4 plats. Débloque plats à effet.
- [ ] Plats rôtis (`Item_Roast_*`, sans CookData) + plats à effet (`Item_Cook_*` + bloc CookData)
      dans le pool — câbler `InjectionSpec.AddCookedItem` ; le kit de départ garantit un modèle type 8

### Gate difficulté (ex-V1.2)
- [x] ~~Gate armure Créature Divine (kill)~~ — REMPLACÉE par les murs de régions par
      téléport (V2, validés in-game) : moins punitif, même contrat logique

### Popup natif « item reçu » (V2)
- [x] ~~Expérience mailbox (LinkTag SaveFlag → EventTag → GetDemo)~~ — **TESTÉE, FERMÉE**
      (2026-07-10) : flag écrit + joueur au relais + aller-retour zone → aucun popup, flag resté
      à 1 (event non déclenché). La couche map ne poll pas les flags en live (comme le sys. d'events).
- [ ] Cible réelle = le **toast de ramassage** (« item — Sacoche + », cf. capture user), PAS le grand
      dialogue GetDemo. Piste : trouver la FILE UI du toast en mémoire (diff avant/après un ramassage
      naturel, comme la localisation des onglets) → si writable, le client pousse ses propres toasts.
      Session dédiée (lecture d'abord, écriture prudente ensuite).

### PopTracker
- [ ] Tester le pack dans PopTracker (autotracking — construit, jamais testé)
- [x] Checks non accessibles en **ROUGE** : `access_rules` par région (miroir de rules.py,
      héritées par les checks + pins carte) — à vérifier lors du test PopTracker
- [ ] Polish : vraies icônes d'items

### Transverse / dette
- [x] Réconcilier la doc : status.md re-cadré (journal RE, CHECKLIST+CLAUDE.md font foi),
      README (livraison mémoire, layout), CLAUDE.md (tests, TODOs, régions, règle .sav)
- [ ] TODO-9 : valider `memory_injector` sur Cemu 2.x (si upgrade)

---

## 🔲 V2 — gros chantiers (démarrés)

- [x] Scaffold mod V2 (`mod/`) : pipeline evfl+oead validé (round-trip octet-identique),
      outils `scan_flows.py`/`dump_flow.py`, builder → graphic pack séparé
      `BOTWpelago_Enforcement` (installé, désactivé par défaut dans Cemu)
- [ ] Enforcement paravoile : patch CONSTRUIT (grant vanilla excisé de FindDungeon,
      scène/quête intactes) — **à valider in-game** (finir le plateau avec le pack coché)
- [ ] Gate Ganon : localiser le flow d'entrée du combat final (`scan_flows.py --patterns Ganon`)
- [x] ~~Popup natif via mailbox EventFlow/LinkTag~~ — TESTÉ, FERMÉ (2026-07-10, cf. section
      « Popup natif » ci-dessus). La vraie cible = le toast de ramassage (file UI), session diff.
- [ ] Rendu live catégorie vide (couche `ksys::ui`) — investigué, différé (reload suffit)
- [ ] Relics of the Past : décompiler → ré-implémenter des features choisies
- [ ] Chests comme locations (TODO-8)

### Idées gameplay V2
- [x] **Gate région par TÉLÉPORT — VALIDÉE IN-GAME (2026-07-09)** puis généralisée :
      brique unitaire testée à pied/cheval/paravoile (fade forêt-perdue, bannière
      DungeonMessage, monture préservée, descente derrière le noir). **4 murs générés**
      depuis `mod/data/zone_walls.json` (tracés du joueur) : Eldin→Flamebreaker→relais
      Pied-de-Mont, Rito→Snowquill→relais Pont de Tabantha, Zora→armure Zora→Soh Kofi,
      Gerudo→tenue Gerudo→relais Canyon Gerudo. 249 objets / 22 carrés (couche AOC).
      Client : sets livrés + flags IsGet_Armor_* posés. Remplace la gate kill (V1).
      Reste : passe de test des 4 murs in-game + ajustement des polylignes au besoin.
- [ ] **Cap cœurs / endurance + overflow en rubis** : plafonner le max de cœurs et d'endurance ;
      si le joueur en gagnerait au-delà du plafond → convertir en **don de 500 rubis**.

### Décompilations à étudier (apprendre → ré-implémenter, PAS redistribuer)
- [x] ~~**`DAR 3.6 - BCML - FREE.zip`**~~ — plus nécessaire : le mécanisme vanilla de blocage
      conditionnel par zone (Area→LinkTag→EventTag, + SaveFlag lisibles au niveau map) a été
      décodé directement dans le dump (cf. mod/README.md §4) — plus complet que ce que DAR
      aurait appris. (Le zip n'a d'ailleurs pas été retrouvé sur le disque.)
