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

### Release — EN DERNIER (consigne user 2026-07-11 : pas de rebuild exe / merge
### tant que TOUTE la checklist ci-dessous n'est pas ✅)
- [ ] Rebuild `BOTWpelago.exe` + merge `dev` → `main`. Préparation DÉJÀ faite (2026-07-11) :
      spec embarque `mod/` + oead/evfl/rstb ; `pack_builder` exécute `build_mod` in-process
      (runpy — dans l'exe figé `sys.executable` n'est plus un python) ; dry-run `--check` OK.
- [ ] Validation end-to-end : une vraie run AP multi-slot complète.
      Génération 2 slots ✅ (2026-07-11 : apworld rebuild + p1/p2 → 1422 items placés,
      seed + 2 `.apbotw` × 186 coffres) — reste la RUN jouée.
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
- [x] Plats **CÂBLÉS (2026-07-11) + CONFIRMÉS IN-GAME** : `InjectionSpec.AddCookedItem`
      (live-only, jamais de voie fichier — le CookData ne vit que dans le nœud runtime) ;
      `live_create_item(cook_data=...)` écrit le bloc +0x68..+0x78, ne stack jamais (1 nœud
      = 1 assiette). sub vérifié sur nœuds naturels : plats cuisinés Cook_* = **0x8**,
      grillés Roast*/Boiled/Chilled = **0xA** (pouch_db régénéré, nourriture type 8).
      Pool : 19 entrées (7 rôtis add_porch + 4 plats soin + 8 élixirs, ap_id 6080130+).
      ✅ Vérif joueur (2026-07-11) : plats/icônes corrects, Spicy Elixir donne bien rés.
      froid 10:00 → **énum CookEffectId VALIDÉE** (LifeMaxUp=2 ResistHot=4 ResistCold=5
      ResistElectric=6 AttackUp=10 DefenseUp=11 MovingSpeed=13 Fireproof=16) ; rubis
      inchangés après l'aller-retour ±1.

### Gate difficulté (ex-V1.2)
- [x] ~~Gate armure Créature Divine (kill)~~ — REMPLACÉE par les murs de régions par
      téléport (V2, validés in-game) : moins punitif, même contrat logique

### Popup natif « item reçu »
- [x] ~~Expérience mailbox (LinkTag SaveFlag → EventTag → GetDemo)~~ — **TESTÉE, FERMÉE**
      (2026-07-10) : flag écrit + joueur au relais + aller-retour zone → aucun popup, flag resté
      à 1 (event non déclenché). La couche map ne poll pas les flags en live (comme le sys. d'events).
- La cible réelle (toast de ramassage) est suivie dans « V1 — gameplay & enforcement » ci-dessous.

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

## 🔲 V1 — gameplay & enforcement (ex-V2, TOUT passé en V1 le 2026-07-11, consigne user)

- [x] Scaffold mod V2 (`mod/`) : pipeline evfl+oead validé (round-trip octet-identique),
      outils `scan_flows.py`/`dump_flow.py`, builder → graphic pack séparé
      `BOTWpelago_Enforcement` (installé, désactivé par défaut dans Cemu)
- [ ] Enforcement paravoile : patch CONSTRUIT (grant vanilla excisé de FindDungeon,
      scène/quête intactes) — **à valider in-game** (finir le plateau avec le pack coché)
- [~] Gate Ganon / **Arc de Lumière** — **CONSTRUIT (2026-07-11), reste le test in-game** :
      - Flow d'entrée localisé : `HyruleCastle.bfevfl` entry `BossRoom0` (boss room au
        warp vanilla (-254, 295, -1049)) — mais implémentation = **5e mur zone_walls**
        (brique validée) : région "Ganon", octogone fermé r~130 autour du Sanctum
        (carrés E-3/E-4, 261 objets/24 carrés au total), warp PROVISOIRE porte sud du
        château (-254, 130, -580) à ajuster à la passe de test.
      - Flag du mur = **mailbox inerte `TestQuest_Takano_01_Finish`** posé par le client
        à la réception — PAS `IsGet_Weapon_Bow_071` (preuve du goal 'full', posé par
        Zelda pendant Dark Beast ; conflit détecté et évité, test data-integrity ajouté).
      - Item AP **« Bow of Light » (6080018, progression)** : add_porch Weapon_Bow_071
        (dura 100) + set_flag mailbox ; retiré du filler gear (était epic) ; goal AP
        l'exige toujours (rules.py). Génération 2 slots revalidée.
      - NB : comme les tenues, l'ouverture du mur après réception ≠ instantanée
        (flags reload-gated) → cf. piste bools live.
- [ ] Popup natif = **toast de ramassage** (« item — Sacoche + ») : session diff live
      (snapshot avant/après un ramassage naturel → trouver la file UI ; si writable,
      le client pousse ses propres toasts). Lecture d'abord, écriture prudente ensuite.
- [ ] Passe de test des 4 murs de régions in-game + ajustement des polylignes au besoin
- [ ] **Cap cœurs / endurance + overflow en rubis** : plafonner le max de cœurs et
      d'endurance ; au-delà du plafond → convertir en **don de 500 rubis** (le vrai
      portefeuille est câblé → faisable proprement maintenant)
- [~] **Flags BOOLS live — storage TROUVÉ + write PERSISTANT (2026-07-11)** : structure
      complète confirmée (table objets `{hash, 0, vt 0x10298410, meta}` stride 16 ;
      **storage** `{typeinfo 0x10297BD0, ptr → sous-objet hash+8, value u8<<24}` —
      l'analogue exact du wallet s32). Write-test validé sur `TestQuest_Takano_01_Finish`
      (inerte) : 0→1 persiste 22 s, miroir meta+2 aligné, restauré. RESTE le test in-game :
      (a) sérialisation à l'autosave ; (b) la couche map lit-elle le storage EN LIVE →
      banc de test = **le mur Ganon** (même flag mailbox). Si oui → livraisons de flags
      instantanées (runes/capacités/gates sans reload) → câbler `write_flag_live` dans
      memory_injector. Détails : docs/status.md §gdt-live.

## 🔲 Différé APRÈS la V1

- [ ] Rendu live catégorie vide (couche `ksys::ui`) — investigué, différé (reload suffit)
- [ ] Relics of the Past : décompiler → ré-implémenter des features choisies
- [ ] Chests comme locations (TODO-8)

### Détail gameplay (référence)
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
