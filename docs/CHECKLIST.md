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
- [x] **« Plateau rouge » élucidé (2026-07-13)** : le pack que PopTracker charge vit dans
      `D:/poptracker/packs/botw-ap-tracker` — c'était une copie du 10/07, ANTÉRIEURE au fix
      régions du 12/07 (les 6 lieux du plateau y étaient encore sous « Hyrule World » → rouges).
      Pack reconstruit + réinstallé (`python tools/build_poptracker.py --install`, 16 checks
      plateau vérifiés des deux côtés). ⚠️ Après chaque rebuild du pack : relancer `--install`
      ET redémarrer PopTracker (il tient un handle sur le dossier du pack). **À re-vérifier au
      prochain lancement PopTracker** (plateau vert d'emblée).
- [x] Checks non accessibles en **ROUGE** : `access_rules` par région (miroir de rules.py,
      héritées par les checks + pins carte) — à vérifier lors du test PopTracker
- [x] **Grand Plateau accessible AVANT la paravoile — VÉRIFIÉ + CORRIGÉ (2026-07-12)** : la
      région "Great Plateau" n'a AUCUNE `access_rules` (toujours verte) — cohérent avec
      rules.py (seule la SORTIE « Leave Great Plateau » exige la paravoile). Bug trouvé : 6
      LIEUX physiquement sur le plateau (Location_* co-localisés aux sanctuaires : Dungeon009/
      038/041/065, Map Tower07, + Temple du Temps « Times Shrine ») étaient tagués "Hyrule
      World" → rouges/gatés à tort. Fix à la SOURCE dans `tools/assign_regions.py` : polygone
      Grand Plateau (enveloppe convexe des sanctuaires/tour, marge 120 u conservatrice — Hyrule
      central le plus proche à ~390 u) → assigne les lieux DESSUS à "Great Plateau" (survit au
      rebuild build_locations→assign_regions). Données régénérées (4 fichiers) + pack PopTracker
      reconstruit : région Great Plateau = 16 checks, aucune access_rules. Tests 36 OK.
- [ ] Polish : vraies icônes d'items

### Transverse / dette
- [x] Réconcilier la doc : status.md re-cadré (journal RE, CHECKLIST+CLAUDE.md font foi),
      README (livraison mémoire, layout), CLAUDE.md (tests, TODOs, régions, règle .sav)
- [x] **Robustesse post-crashs (2026-07-13)** — réponse aux 3 crashs Cemu + livraisons ratées
      de la run du 13/07 (Event Log : 0xc0000409 avant menu 00:33, 0xc0000005 code recompilé
      au tri d'inventaire 00:49) :
      1. **Validation gd_base à CHAQUE accès** (header + canari des 16 premiers flag_ids) :
         un buffer game_data RÉALLOUÉ par le jeu (load/nouvelle partie) est détecté →
         invalidation + AUCUNE écriture dans la mémoire recyclée (cause plausible des crashs
         boot/cinématique : retention écrite sur le buffer du menu titre, freed au vrai load).
      2. **Ré-attache AUTO** (`ensure_attached`, cooldown 15 s, appelé chaque flush) : client
         lancé avant Cemu, Cemu relancé après crash, gd invalidé → plus jamais besoin de
         relancer le client.
      3. **Retry localisation inventaire** (`ensure_live_inventory`, cooldown 20 s) : attach
         pendant la cinématique d'intro / save neuve → l'inventaire absent n'était JAMAIS
         re-cherché → **AUCUNE livraison jusqu'au redémarrage client** (bug « rien reçu avant
         le 1er sanctuaire »). Corrigé.
      4. **Baseline PAR SEED + intersection serveur** : un `--reset` en cours de run
         re-snapshotait la baseline → checks faits pendant les crashs MANGÉS (constaté : 4
         sanctuaires Plateau + tour). Désormais : baseline réutilisée tant que la seed ne
         change pas (`--reset` ne la supprime plus) ; au snapshot d'une room EN COURS, seuls
         les checks connus du serveur sont baselinés, le reste est ÉMIS. tests/test_baseline.py.
      5. **Log fichier persistant** (`~/.botwpelago/logs/client-*.log`, DEBUG, 10 fichiers) —
         le diagnostic post-mortem était impossible (stdout seul).
      **RESTE : confirmer in-game** (les protections sont passives tant que le jeu ne
      réalloue pas). Le crash « tri d'inventaire » (0xc0000005 dans le code recompilé) reste
      SUSPECT d'un nœud pouch mal formé — à surveiller avec les nouveaux logs.
- [x] **Livraison sur POCHE QUASI-VIDE — CORRIGÉE (2026-07-14, run de validation raté)** :
      sur save neuve (1-2 nœuds pouch), (a) la dérivation de base par ADJACENCE n'avait qu'un
      couple → base GARBAGE (guests négatifs) → `wallet: flagobj hors mapping guest` en boucle,
      et (b) AUCUNE ancre triée possible (ni paire encadrante ni borne) → « pas d'ancre triée …
      reporté » à l'infini pour TOUT (paravoile `PlayerStole2` incluse) → « je n'ai reçu aucun
      objet ». Fixes (memory_injector) : **base par SELF-POINTER** du nom (+0x1C → node+0x28,
      exacte dès UN nœud, même libre) + filtre de plausibilité guest [0x02000000, 4 Gio) ;
      **ancre par la LISTE RÉELLE** (`_find_list_sentinel` + `_find_insert_link` : marche depuis
      la sentinelle sead::OffsetList, insertion en TÊTE/queue possible dès un nœud ; splice
      généralisé aux links — sentinelle = S+0x00, nœud = N+0x04, prev du suivant = link+4) ;
      **fallback non-validé** garde désormais la base dérivée et `_find_wallet` cherche le
      flagobj VIVANT par scan de hash (cooldown 30 s) quand la copie AOB est morte. Les 4
      « Flag introuvable » ponctuels du log = état transitoire pendant le reload (bénin, retry
      au cycle suivant). Tests : test_memory_injector_locate.py (12). **À re-valider in-game.**
- [x] **Retour de run 2026-07-14 (2e passe) — livraison VALIDÉE in-game** (plats, matériaux,
      armes, paravoile objet+flag, rubis, re-localisation auto après réallocation, récupération
      d'un create perdu par l'idempotence companion). Polish corrigé dans la foulée :
      1. toast équipement SANS « xN » (l'amount d'une arme = durabilité → « Boomerang x18 ») ;
      2. fuite du suffixe qty sur le bandeau PRÉCÉDENT (string MSBT partagée re-résolue pendant
         l'affichage) → throttle 4 s → 5 s ;
      3. toast des objets COMPANION câblé (paravoile/capacités/tenues/arc n'en avaient AUCUN) ;
      4. toast des lots de rubis (texte : « Vous avez reçu N rubis. ») ;
      5. **compteur de sanctuaires = MAX(DungeonClearCounter, nb Clear_Dungeon* à 1)** —
         confirmé sur save réelle : le s32 reste à 0 malgré 4 sanctuaires clear → goal +
         tracker (ShrinesCleared) étaient MORTS assis sur le seul compteur ;
      6. toast « envoyé à » : rien à corriger — INVISIBLE EN SOLO par design (finder =
         receveur = soi → le bandeau « Vous avez reçu » suffit) ; à valider en session 2 slots.
      NB : les 4 sanctuaires du plateau restaient baselinés dans la ROOM du 13/07 (snapshot
      pris quand la room était vierge) → sur la PROCHAINE seed (save neuve), baseline vide.
- [x] **Retour de run 2026-07-14 (3e run, soirée — crash élucidé + 2 causes racines)** :
      run save neuve + seed neuve, crash Cemu 0xc0000005 (code recompilé) à 18:28:46 pendant
      un reload volontaire. Enquête (logs client DEBUG + Event Log + diff des 4 autosaves) :
      1. **Le client n'a RIEN écrit sur le disque** : les `FSC: File create failed` du log Cemu
         = premières créations de dossiers de slots après le wipe (bénin, CreationTime = l'heure
         du FSC fail, la save passe dans la même seconde). Toutes les gardes fichier ont tenu.
      2. **Cause du crash : splice sur COPIE FREED de la poche.** Slot 2 : boomerang créé/inséré
         trié ✓ mais l'Eightfold créée à 18:26 JAMAIS sérialisée (partie dans une copie freed —
         les « 12/12 self-ref » passent sur de la mémoire libérée intacte) ; slot 3 : liste
         massacrée (ordre aberrant, 5 nœuds perdus dont la **tablette Sheikah**) → reload →
         0xc0000005. **FIX : ancre STATIQUE de la poche** (backref one-shot section data guest
         0x10xxxxxx après une localisation validée → chaque accès RELIT le pointeur = on suit
         toujours le buffer vivant, une copie freed n'est plus adressable) + **gel de TOUTES les
         écritures mémoire** tant que `delivery_ready` est faux : gd-canari re-validé à l'accès,
         poche suivie par l'ancre, **tablette Sheikah en poche** (rien avant la prise de la
         tablette ; re-vérifié après chaque load). Tests : +5 memory_injector.
      3. **« Baseline pas vide » élucidé : le rando pré-init des flags à toute NOUVELLE partie**
         (`rando/BotwRandoLib/Randomizer.cs · UpdateGameData` : InitValue=1 dans
         bootup.pack/gamedata.ssarc) : 4 `Clear_Dungeon` du plateau (en dur, même en AP),
         `MapTower_07`(+Demo), `Location_MapTower07`, `IsGet_MemoryPhoto_008`, runes(+Lv2),
         IsGet_Weapon*/Item*, démos d'intro, `Open_StartPoint` — c'est son « skip plateau »
         (quête donnée au réveil, tour pré-activée). Jamais vu avant : tous les tests couraient
         sur des saves existantes. **Décision : PLATEAU OFFERT** — ces 7 locations partent en
         FREEBIES (whitelist `_RANDO_INIT_LOCATION_IDS` : jamais baselinées, émises à la
         connexion, filtrées aussi au rechargement d'une baseline contaminée) et les 4
         sanctuaires pré-clearés sont EXCLUS du compteur (goal + ShrinesCleared comptent les
         sanctuaires réellement joués). Tests : +2 baseline.
      **RESTE : re-valider in-game** (ancre statique résolue au log, livraisons qui attendent
      la tablette, freebies émis à la connexion, ShrinesCleared=0 au départ).
- [x] **Retour du 4e run (2026-07-14 soir, correctifs du 3e run RÉVISÉS)** : deux ratés —
      1. **Fausse ancre statique** (offset +0x24B1 NON aligné = mot de données quelconque) :
         elle « confirmait » à vie le buffer d'origine périmé → tablette jamais vue → gate
         jamais levée → « je n'ai reçu aucun objet ». Fixes : offset objet ALIGNÉ requis ;
         à chaque localisation VALIDÉE (oracle rubis), une ancre qui ne désigne pas le buffer
         validé est JETÉE et re-résolue ; tant que la tablette n'est pas vue, `delivery_ready`
         force une RE-LOCALISATION complète (cooldown 20 s) — l'early-return « pas prêt »
         court-circuitait la re-localisation du flush.
      2. **« Plateau offert » mal implémenté** : les 7 locations pré-vraies étaient restées
         dans le POOL → la seed y a placé le PARAGLIDER (« Map Tower07 ») → gate morte
         d'entrée + items freebies non désirés. Décision RÉVISÉE (demande user) : **HORS POOL
         partout** — `RANDO_INIT_LOCATION_IDS` dans worlds/botw/locations.py (filtre
         active_locations, pool auto-réduit), table de polling client filtrée (plus d'émission),
         pack PopTracker sans ces checks (**un sanctuaire du plateau se suit via son LIEU +
         son COFFRE** — c'était la demande initiale). Compteur sanctuaires : toujours hors
         pré-clearés. Génération 1 slot revalidée (708 items, playthrough OK). Pack rebuild
         (843 lieux) — ⚠️ `--install` à faire PopTracker FERMÉ. Tests 67 OK (+ miroir
         worlds/client par lecture source).
- [x] **Retour du 5e run (2026-07-14 soir) — gate tablette/ancre/livraisons/toasts/PopTracker
      VALIDÉS in-game** ; deux nouveaux bugs corrigés dans la foulée :
      1. **Crash plat sur catégorie nourriture VIDE** : Meat Stew (Item_Cook_K_01) livré avant
         tout ramassage d'aliment → splice dans une section que le jeu n'a pas encore créée
         (indépendant de la tablette) → crash. Fix : verrou type 8 comme les flèches — un
         plat/aliment est REPORTÉ (retry auto) tant qu'AUCUN item type 8 n'est en poche ;
         log `catégorie nourriture vide — … reporté`. (Si un crash similaire apparaît sur les
         matériaux type 7, étendre le même verrou.)
      2. **Items-clés AP dans les coffres du RANDO** (casque Zora + Urbosa's Fury tirés au
         sort) : `BotwRandoTable` exclut désormais en mode AP (apMode = apConfig != null) les
         acteurs gérés par AP — 4 HeroSouls, Weapon_Bow_071, tenues de gate Armor_011/009/
         053/006 (miroir de gate_items.json). `BotwRandoCLI.exe` recompilé (dotnet Release).
         ⚠️ Nouveau pack/seed requis pour que ça prenne effet (play_local régénère tout).
      3. **Kit de départ JAMAIS JOUÉ sur partie moddée (élucidé)** : le kit (starter-kit,
         8 items dont un type 8) est bien FUSIONNÉ dans le pack (CommonFirst → BOTWSK0
         vérifié dans le .sbeventpack installé) MAIS son entry `CommonFirst` (variante
         « premier téléchargement » du socle) ne joue pas : le rando pré-valide les démos
         d'intro + la première tour (`MapTower_DemoFirst` etc. en InitValue) → c'est la
         variante `Common` qui joue. Tous les tests précédents étaient sur saves aux onglets
         déjà débloqués → jamais vu. Parade côté client : **garde GÉNÉRALE onglet verrouillé**
         (remplace les verrous flèches/nourriture) — aucune création live tant qu'aucun item
         du même ONGLET (armes 0 · arcs/flèches 1-2 · boucliers 3 · armures 4-6 · matériaux 7
         · nourriture 8) n'est en poche ; reporté avec retry, jamais perdu. NB : le layout
         « pack Enforcement séparé » est PÉRIMÉ — build_mod FUSIONNE tout dans BOTWpelago
         (un seul pack à cocher dans Cemu).
- [x] **Kit de départ v3 — ancré à la FIN DU RÉVEIL rando (2026-07-14 soir)**. Historique :
      v1 `CommonFirst` (Demo003_0) ne joue jamais sur partie moddée ; v2 `Common` gardée par
      flag a TOURNÉ (flag `TestQuest_shimizu01_Finish` = 1 sur la save du 6e run) mais dans
      un contexte où la poche ne recevait PAS (0 item livré, grants no-op, flag brûlé) —
      leçon : `Demo_IncreasePorchItem` (params {PorchItemName, Value, IsWaitFinish}, 1122
      usages positifs dans le jeu = LE mécanisme standard) ne prend que dans un contexte
      poche vivant. **v3** : le rando VIDE `Demo700_0` (réveil, 72→25 events) et y enchaîne
      don de la tablette (SUBFLOW GetDemo::GetItemByName) + ses flags de quêtes
      (`FindDungeon_Activated` → `Open_Door` → FIN) → le kit est APPENDU en queue :
      `Open_Door → Demo_WaitFrame(30) → 8 × Demo_IncreasePorchItem → FIN`. Poche garantie
      vivante (elle vient de recevoir la tablette), délai demandé par le joueur, cinématique
      one-shot → pas de garde. Ancre = marqueur rando `FindDungeon_Activated` (une copie non
      -rando est REFUSÉE proprement). Validé hors-jeu (chemin d'exécution complet, idempotence,
      round-trip) + appliqué au pack installé. **À valider in-game : les 8 items tombent ~1 s
      après la fin de la cinématique du réveil.**
- [x] **Retour du 7e run (2026-07-14 nuit) — rafale RELEASE-ALL (703 items)** : livraisons
      live/toasts/tenues/Master Sword/Arc de Lumière/orbes/flèches/rubis TOUS OK pendant la
      rafale (kit v3 OK aussi) — puis inventaire désorganisé et FREEZE (Cemu vivant, jeu
      bloqué). Cause : la rafale a créé des DIZAINES d'armes/arcs/boucliers alors que les
      onglets n'ont que 8/5/4 slots (`WeaponPorchStockNum`/`BowPorchStockNum`/
      `ShieldPorchStockNum`, +Korok) → onglet dans un état illégal → tri/UI en boucle.
      **FIX : cap d'onglet dans live_create_item** (lecture du flag de capacité, défaut
      vanilla si absent) : au cap, le create refuse et signale `_last_create_overflow` →
      le FILLER d'équipement est **converti en 100 rubis** (toast « converti en 100 rubis »,
      item AP compté reçu) ; la progression companion (Master Sword, Arc, tenues) reste en
      retry jusqu'à libération d'un slot. Tests +2 (69 OK). NB : cœurs/endurance NON encore
      confirmés in-game — reload-gated, le freeze est arrivé avant tout rechargement
      (attendu au reload : 3+12 cœurs, +14/5 roues d'endurance).
- [x] **Retour du 8e run (2026-07-14 nuit) — crash au RAMASSAGE élucidé + gardes anti-course** :
      après la rafale (release re-rejoué), le jeu crashe quand LE JOUEUR ramasse un item
      (drops d'ennemi ; un casque barbare de coffre a même disparu) : le jeu INSÈRE son
      ramassage dans une liste pouch que nos splices ont perturbée (ordre interne divergent
      de son comparateur / course insertion-jeu vs splice-client pendant la rafale). Gardes :
      1. **Fenêtre calme** : si la poche a changé depuis notre dernier cycle (ramassage,
         réallocation), la création est différée d'UN cycle (nos propres créations mettent
         la signature à jour → un batch reste fluide) ;
      2. **Intégrité de liste avant chaque batch** (marche réelle sentinelle→sentinelle,
         réciprocité next/prev de chaque maillon, mCount == nœuds traversés ; re-test à
         +250 ms pour tolérer une insertion du jeu en cours) : liste incohérente →
         `créations live SUSPENDUES jusqu'au prochain RECHARGEMENT` (le jeu reconstruit une
         liste propre depuis la save ; suspension levée à l'invalidation gd). Items en file,
         rien n'est perdu. Tests +3 (72 OK).
      **Consigne de run : après une grosse rafale, RECHARGER la save avant de reprendre
      l'exploration** (consolide la liste + applique cœurs/endurance/flags).
- [x] **9e run (2026-07-14 nuit) — coalescence + suspension immédiate** : la rafale rejouée a
      montré (a) MaxStat ENFIN validés en livraison (cœurs 12→44, endurance 1000→3000 +
      overflow 500 rubis ✓ — reste la vérif visuelle au reload), (b) la garde intégrité qui
      détecte la liste cassée mais TROP TARD (contrôle périodique 4 s → plusieurs splices
      s'étaient déjà empilés ; le save/reload du joueur a désérialisé la liste corrompue →
      crash). Améliorations :
      1. **COALESCENCE (idée user)** : les doublons empilables/compteurs de la file (flèches,
         matériaux, rubis, orbes, réceptacles/fioles) sont livrés EN UNE opération à quantité
         cumulée (`Arrows x10 ×60` = un bump +600) — la rafale passe de ~700 opérations à
         ~60 ; granularité d'origine préservée en cas d'échec ; équipement/plats unitaires ;
         stacks clampés à 999 (cap du jeu).
      2. **Vérif post-splice** : l'intégrité de l'anneau est contrôlée immédiatement APRÈS
         chaque insertion — incohérence → suspension SUR-LE-CHAMP + consigne « recharge sans
         re-sauvegarder » (plus d'empilement sur du cassé entre deux contrôles périodiques).
      À re-valider : rafale complète sans corruption ; si suspension → la save d'AVANT la
      rafale reste saine (slots multiples BotW).
- [x] **10e run (2026-07-15) — les gardes v1 SUR-bloquaient, corrigées** : en jeu actif,
      « poche active — différée d'un cycle » tournait en boucle À VIE (la fenêtre calme
      comparait à l'état de la TENTATIVE précédente, parfois 1 min plus tôt → toujours un
      ramassage entre-temps) → « l'envoi n'est pas repris », Urbosa/Master Sword coincés en
      file ; et 2 suspensions « liste INCOHÉRENTE » étaient des FAUX POSITIFS (vérif
      post-splice lue pendant une insertion du jeu, 0,3 s après un ramassage). Fixes :
      1. fenêtre calme TEMPORELLE : splice autorisé dès que la poche est stable ≥ 3 s
         (l'horodatage n'est re-armé que par l'activité du JOUEUR, pas par nos créations) ;
      2. vérif post-splice avec RE-TEST à +250 ms avant suspension (comme la périodique).
      NB validé au passage : cœurs/endurance MAX bien montés au reload — les nouveaux cœurs
      arrivent VIDES (on monte MaxHartValue, pas CurrentHart qui est un miroir non-écrivable)
      → manger un plat les remplit ; comportement documenté, pas un bug.
- [x] **11e run (2026-07-15) — SOURCE PROBABLE de la corruption trouvée : mCount écrit hors
      sentinelle** : coalescence validée in-game (×47 orbes, arrows ×22… en un bump chacun),
      MAIS 2 splices (Master Sword, Urbosa) ont suffi à re-désorganiser la poche. Cause
      identifiée : (a) `_scan_pouch_nodes`/`_iter_inventory_slots` S'ARRÊTAIENT au premier
      slot atypique → sur une poche FRAGMENTÉE (mature, post-rafale), scan TRONQUÉ →
      node_bases incomplet ; (b) `_bump_pouch_count` refaisait sa propre marche « lâche »
      APRÈS le splice et prenait le premier lien inconnu pour la sentinelle → **mCount écrit
      DANS UN NŒUD** (petites valeurs plausibles fréquentes) → liste désorganisée → crash au
      ramassage/reload. FIX : scans COMPLETS des 420 slots (skip des slots atypiques, plus de
      troncature) ; **sentinelle OBLIGATOIRE pré-validée** (marche défensive) AVANT tout
      splice — pas de sentinelle sûre = pas de splice ; mCount incrémenté À cette sentinelle ;
      `_bump_pouch_count` SUPPRIMÉ. Si la corruption persiste malgré ça → plan B : créations
      d'équipement reload-gated pendant les replays de backlog.
- [x] **12e run (2026-07-15) — LE chaînon manquant : le nœud consommé restait dans la
      FREE-LIST du jeu**. Le run a livré 37 créations PROPRES en 8 min (ancres triées,
      sentinelle pré-validée, coalescence ×N) puis l'anneau a cassé entre la dernière
      création et un ramassage — comme à CHAQUE incident depuis le 7e run. Cause (déjà
      notée « latent issue » le 2026-06-13, jamais traitée) : on splice F dans la liste
      ACTIVE + mCount++, mais F reste chaîné dans la liste LIBRE (l'allocateur du jeu) →
      le ramassage suivant RÉ-ALLOUE F, l'écrase et le re-splice → anneau cassé →
      inventaire désorganisé → crash. FIX : F est DÉLIÉ de la free-list AVANT d'être
      écrasé (réciprocité next/prev exigée sinon report ; décrément best-effort du
      free-count S+0x18). **À valider in-game : rafale puis RAMASSAGES + save/reload —
      c'est LE test qui a toujours échoué.**
- [x] **Toast « {item} envoyé à {joueur} » (2026-07-13)** : sur PrintJSON ItemSend dont on est
      le FINDER (receveur ≠ nous) → bandeau natif à TEXTE LIBRE (`toast_enqueue_text` /
      `push_toast(text=…)`) : la zone MSBT victime est réécrite EN ENTIER à chaque bandeau
      (mode « reçu » = préfixe+tags+suffixe ; mode texte = phrase complète, ~90 chars max,
      paddée sur tout le budget). Même canal/throttle que les « reçus ». **À valider in-game.**
- [x] **Bug 1er attach — livraison ratée + spam wallet (2026-07-12)** : au 1er attach juste
      après un load, la poche fraîchement réallouée laisse une COPIE freed mappée ; le
      localisateur s'y accrochait → `heap_base` décalé → `wallet: flagobj hors mapping guest`
      en boucle + items pas livrés jusqu'à un redémarrage client. Fix (sans reco) : sélection
      du buffer VIVANT par ancre rubis (`_flagobj_guest_ok`), validation de couple, reset de
      `heap_base`/wallet à la relocation, détection de dérive de base, warning rate-limité.
      Tests : `tests/test_memory_injector_locate.py` (7). Détails : status.md §gdt-live.
      **RESTE : confirmer in-game** (items de départ livrés au 1er attach, sans déco/reco).
- [ ] **Orbes reçus AVANT le 1er orbe naturel — vérifier le rattrapage** (question user
      2026-07-14) : par design, on ne crée JAMAIS le nœud pouch `Obj_DungeonClearSeal`
      (game-managed, un faux nœud crashe à la réconciliation — appris en juin). Sur une
      save sans orbe, les orbes AP vivent dans `DungeonClearSealNum` (gamedata, persisté)
      et le nœud visible n'apparaît qu'au 1er orbe NATUREL (vrai sanctuaire terminé).
      Le rattrapage du stack complet passe par `_bank_spirit_orbs` (client tournant, Cemu
      FERMÉ un instant) — À VÉRIFIER : après le 1er sanctuaire réel + un passage au menu
      titre/Cemu fermé, le stack d'orbes doit refléter le total AP. Si le rattrapage live
      s'avère nécessaire, attention au double-comptage (le joueur peut DÉPENSER des orbes
      à la statue — un « minimum maintenu » naïf les re-créerait).
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
- [x] **Cap cœurs / endurance + overflow en rubis — IMPLÉMENTÉ + FLAGS CONFIRMÉS (2026-07-13)** :
      nouveaux items AP **Réceptacle de Cœur** (6080128) + **Fiole d'Endurance** (6080129)
      ajoutés à la loot table (`build_loot_table.py` SPECIALS, poids 27). Livraison via
      `InjectionSpec.AddMaxStat` → `_deliver_max_stat` : monte le MAX persistant (flag gamedata,
      reload-gated) jusqu'au plafond DUR du jeu (30 cœurs / 3 roues) ; chaque unité au-delà →
      **don de 500 rubis** (live via le portefeuille câblé, ou CurrentRupee save hors-ligne).
      Planificateur pur `_plan_max_stat` + repli SÛR (flag absent/aberrant → tout en rubis).
      **FLAGS CONFIRMÉS par lecture des saves réelles** (l'ancien candidat `Item_LifeMaxUp`
      n'existe pas dans cette version) : cœurs = **`MaxHartValue`** (s32 ¼-cœurs : lu 12 sur
      save 3 cœurs / 36 sur save 9 cœurs, `CurrentHart` ≤ partout) ; endurance = **`StaminaMax`
      + `StaminaCurrentMax`** (f32 toujours égaux : 1000.0 base, 1200.0 base+1 fiole → les DEUX
      écrits via `also`). +200/fiole, caps 120 / 3000.0. Bandeau natif à la livraison (actors
      `Obj_HeartUtuwa_A_01` / `Obj_StaminaUtuwa_A_01`, localisés par le jeu ; overflow → toast
      texte). Tests : `tests/test_max_stat.py` (13). **Validation finale in-game : premier
      Réceptacle/Fiole reçu d'AP → +1 cœur / +1/5 roue au reload.**
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
- [x] **Livraison des tenues de région + Arc de Lumière — CORRIGÉE (2026-07-12)** : bug — un
      spec MIXTE porch+flag (3 pièces + 3 flags `IsGet_Armor_*`) passé à `_inject_pending`
      était classé « flag-only » (`any(SetFlag)` → `continue`) → log trompeur « Flags écrits —
      RECHARGE » alors que NI les pièces NI les flags n'étaient réellement livrés (le Bow of
      Light avait le même bug). Fix : les items `ap_progression_logical` n'exposent plus
      d'action injectable (item_map) → `queue_item` ne fait que TRACER la réception ; la
      livraison passe par le mécanisme COMPANION du provider — pièces via `_COMPANION_POUCH`
      (tenue complète casque 4 + torse 5 + jambes 6, + l'arc), flags via `_COMPANION_FLAGS`
      (`IsGet_Armor_*` / mailbox de gate), les DEUX construits depuis `gate_items.json`
      (source unique). Idempotent + retenu chaque poll, dans les deux modes (attaché=live
      instantané ; idle=save-fichier). Flags reload-gated → le mur de région s'ouvre au
      rechargement (attendu). Cohérent avec rules.py/regions.py (chaque tenue garde sa
      région). Tests : `test_gate_items.py` (+3). **RESTE : confirmer in-game.**
- [x] **Cap cœurs / endurance + overflow en rubis** — IMPLÉMENTÉ (voir la section « V1 —
      gameplay & enforcement » ci-dessus ; constantes de flags à confirmer in-game).

### Décompilations à étudier (apprendre → ré-implémenter, PAS redistribuer)
- [x] ~~**`DAR 3.6 - BCML - FREE.zip`**~~ — plus nécessaire : le mécanisme vanilla de blocage
      conditionnel par zone (Area→LinkTag→EventTag, + SaveFlag lisibles au niveau map) a été
      décodé directement dans le dump (cf. mod/README.md §4) — plus complet que ce que DAR
      aurait appris. (Le zip n'a d'ailleurs pas été retrouvé sur le disque.)
