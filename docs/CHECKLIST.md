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
- [x] **Bug 1er attach — livraison ratée + spam wallet (2026-07-12)** : au 1er attach juste
      après un load, la poche fraîchement réallouée laisse une COPIE freed mappée ; le
      localisateur s'y accrochait → `heap_base` décalé → `wallet: flagobj hors mapping guest`
      en boucle + items pas livrés jusqu'à un redémarrage client. Fix (sans reco) : sélection
      du buffer VIVANT par ancre rubis (`_flagobj_guest_ok`), validation de couple, reset de
      `heap_base`/wallet à la relocation, détection de dérive de base, warning rate-limité.
      Tests : `tests/test_memory_injector_locate.py` (7). Détails : status.md §gdt-live.
      **RESTE : confirmer in-game** (items de départ livrés au 1er attach, sans déco/reco).
- [ ] TODO-9 : valider `memory_injector` sur Cemu 2.x (si upgrade)

---

## 🔲 V1 — gameplay & enforcement (ex-V2, TOUT passé en V1 le 2026-07-11, consigne user)

- [x] Scaffold mod V2 (`mod/`) : pipeline evfl+oead validé (round-trip octet-identique),
      outils `scan_flows.py`/`dump_flow.py`, builder → graphic pack séparé
      `BOTWpelago_Enforcement` (installé, désactivé par défaut dans Cemu)
- [x] Enforcement paravoile : patch construit (grant vanilla excisé de FindDungeon,
      scène/quête intactes) — **VALIDÉ IN-GAME (2026-07-12)** par le joueur
- [x] Gate Ganon / **Arc de Lumière** — **VALIDÉE IN-GAME DE BOUT EN BOUT (2026-07-12)** :
      mur actif (TP), ouverture par flag+reload (simulation réception AP), renvoi grande
      porte confirmé par le joueur. Détail de construction :
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
- [x] Popup natif « item reçu » — **VALIDÉ IN-GAME + IMPLÉMENTÉ (2026-07-12)** : bandeau
      natif MessageGet « **Vous avez reçu {item} xN.** » (nom LOCALISÉ sans article,
      quantité au suffixe : « Vous avez reçu flèche en bois x5 »). Détail → status §6c.
      **Recette complète** : (1) enqueue pur-mémoire dans la file du HUD (reqMgr =
      *(HUD+0x1B84), HUD = écran registre 0x25) — sentinel {head +0x14C, tail +0x150},
      count +0x154, freelist +0x158 (pop = 1er mot), cap 3 ; nœud 0x54+8 {type @0,
      top→+0x10, vt 0x1021D0FC, 0x40, char[64] nom d'ACTOR @+0x10, u8 @+0x50, links
      @+0x54/58} ; type **0xA** (message à placeholder {item} = string du nœud) ; + nom
      d'actor au ctx *(0x1047B054)+0x2C + bit dirty *(*(0x1046BDD8))+0x4075C |= 1.
      (2) **REDIRECTION MSBT en RAM** : phrase custom « Vous avez reçu {tag} xN. » écrite
      dans une string placeholder de dev (~0xC6 o, jamais affichée) + offset TXT2 de
      l'entrée toast redirigé dessus ; tag article omis → nom nu ; « xN » réécrit avant
      chaque bandeau (masqué si N≤1). Cartographie COMPLÈTE des 0x30 types de toasts
      faite in-game (0-7 compartiments pleins, 8/9/0xA placeholder-item, 0xB-0xD Master
      Sword, 0xE-0x11 compagnons, 0x12-0x18 exposition/équipement, 0x19-0x2F annonces
      diverses) : AUCUN « vous obtenez » natif → la redirection est LA solution.
      **Implémenté** : `push_toast(actor,qty)`/`toast_enqueue`/`toast_pump` dans
      memory_injector (deque throttlée 4 s, préparation heap_base+MSBT sur thread daemon,
      revalidation offset+préfixe avant chaque bandeau → re-préparation auto si le jeu
      recharge le MSBT, best-effort intégral), câblé dans `_apply_actions_memory`
      (pouch/plats → item_name+amount ; SetFlag `IsGet_<actor>` → actor) + `flush()`
      (pump). RESTE : valider le câblage en session AP réelle ; langues ≠ FR = texte
      vanilla en attendant des motifs par langue.
      Outils : tools/{toast_recon,toast_screens,toast_queue_watch,toast_push_test,
      toast_msbt_redirect,toast_msbt_patch}.py.
- [x] Passe de test des murs in-game — **VALIDÉE (2026-07-12)** par le joueur ; warps
      Zora/Gerudo réajustés à la main dans zone_walls.json (coords in-game du joueur)
- [ ] **Cap cœurs / endurance + overflow en rubis** : plafonner le max de cœurs et
      d'endurance ; au-delà du plafond → convertir en **don de 500 rubis** (le vrai
      portefeuille est câblé → faisable proprement maintenant)
- [x] **Flags BOOLS live — TRANCHÉ (2026-07-12, tests in-game mur Ganon)** : storage bool
      trouvé + write persistant en RAM, MAIS (a) **pas sérialisé** (le jeu ne resérialise
      que ses flags « dirty » — 3 saves manuelles, .sav resté à 0) et (b) **pas relu en
      live par la couche map** (mur TP malgré storage+meta à 1). La voie de livraison des
      flags RESTE gd_base/fichier + reload. Le storage bool garde une valeur en LECTURE
      (état runtime réel). Corollaire rubis : `live_add_rupees` écrit désormais AUSSI
      gd_base (sans transaction joueur, le storage seul n'aurait pas été sérialisé).
      Fermé — pas de « flags sans reload » par ce chemin ; il faudrait l'API native
      setBool (mur du recompilateur). Détails : docs/status.md §gdt-live.

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
