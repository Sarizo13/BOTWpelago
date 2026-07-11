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
- [x] Rubis : vrai portefeuille câblé (strip réactivé, rubis au pool) · loot diversifié
      (+184 armes, +19 plats/élixirs, −Spirit Orbs)
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
- [x] Rubis : **RÉSOLU (2026-07-11)** — localisateur STABLE câblé + validé live sur Cemu
      relancé. Topologie (3 copies de `CurrentRupee`, cf. docs/status.md §gdt-live) :
      save-buffer / objet `gdt::Flag<s32>` (= l'ancien « miroir » AOB, alimente le HUD) /
      **storage gdt live** (la copie AUTORITAIRE, prouvée par achat le 2026-07-10).
      `_find_wallet()` : flagobj (via AOB+vérif vtable/hash, fallback scan du hash) →
      backref guest dans le storage → value ; re-validation structurelle avant CHAQUE
      écriture (`_wallet_valid`, adresse périmée impossible par construction).
      `live_add_rupees` écrit storage + flagobj (HUD). Testé : ±1 cohérent sur les 2 copies.
      Strip placeholder RÉACTIVÉ (`_RUPEE_STRIP_ENABLED=True`) ; rubis restaurés au pool
      (50/100/300, ap_id 6080125-27). NB attach +~40 s (scan backref one-shot, thread lourd).
- [x] CookData (plats/potions type 8) **décodé** (2026-07-10) : +0x68 soin, +0x6C durée, +0x70 prix,
      +0x74 type d'effet (f32), +0x78 niveau/quantité — vérifié sur 4 plats. Débloque plats à effet.
- [x] Plats **CÂBLÉS (2026-07-11)** : `InjectionSpec.AddCookedItem` (live-only, jamais de voie
      fichier — le CookData ne vit que dans le nœud runtime) ; `live_create_item(cook_data=...)`
      écrit le bloc +0x68..+0x78, préfère un template sub=0xA, ne stack jamais (1 nœud = 1
      assiette). Pool : 19 entrées (7 rôtis add_porch + 4 plats soin + 8 élixirs, ap_id
      6080130+). Testé live : Mushroom Skewer + Spicy Elixir créés, CookData relu conforme.
      ⚠️ Énum CookEffectId (decomp : LifeMaxUp=2 ResistHot=4 ResistCold=5 ResistElectric=6
      AttackUp=10 DefenseUp=11 MovingSpeed=13 Fireproof=16) à CONFIRMER à l'écran au premier
      élixir goûté (un Spicy Elixir de test est dans la poche).

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
- [ ] **Flags BOOLS live sans reload (piste ouverte 2026-07-11)** : la chasse au wallet a
      révélé le **gdt live complet** (storage s32 {typeinfo 0x10297C88, ptr flagobj, value}
      + objets `Flag<s32>` vtable 0x102984C8). Les BOOLS ont le même schéma : objets 16 o
      `{hash, ?, vtable 0x10298410, meta}` où meta semble contenir la valeur (Magnetglove
      lu =1, cohérent). Si écrire meta prend effet SANS reload → capacités/gates/Paraglider
      instantanés (fin du « reload-gated »). Session dédiée : write-test prudent sur un flag
      réversible + observation. Détails : docs/status.md §gdt-live.
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
