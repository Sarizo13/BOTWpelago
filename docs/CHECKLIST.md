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
- [ ] Rebuild `BOTWpelago.exe` + merge `dev` → `main`
- [ ] Potions / plats cuisinés (type 8, portent des effets → un peu de RE)
- [ ] Validation end-to-end : une vraie run AP multi-slot complète
- [ ] (option) TODO-7 : remplir `region` dans `locations.json` (graphe de régions / règles plus fines)

### Loot & rubis (ex-V1.1)
- [x] Rareté du loot : 4 tiers (common ×8 / uncommon ×4 / rare ×2 / epic ×1) assignés par
      mots-clés dans `build_loot_table.py` ; quantités plafonnées (rare ≤ 2, epic = 1) ;
      specials rescalés (~14 % du tirage). Vérifié sur seed : 50/17/11/1.5 %.
- [ ] Rubis : trouver le vrai portefeuille (pas le miroir) → strip fonctionnel

### Gate difficulté (ex-V1.2)
- [ ] Gate armure Créature Divine : tuer le joueur s'il entre sans l'équipement adapté (réutilise le kill DeathLink)

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

## 🔲 V2 — gros chantiers (différés)

- [ ] Mod romfs « hard enforcement » (retirer grant paravoile vanilla, gate Ganon) — optionnel
- [ ] Popup natif in-game « item reçu » (code cave RPX / createPorchItem) — l'overlay desktop suffit pour V1
- [ ] Rendu live catégorie vide (couche `ksys::ui`) — investigué, différé (reload suffit)
- [ ] Relics of the Past : décompiler → ré-implémenter des features choisies
- [ ] Chests comme locations (TODO-8)

### Idées gameplay V2
- [ ] **Gate région par TÉLÉPORT** (alternative douce au kill) : quand le joueur entre dans une
      région sans l'objet requis, le TP en arrière à la façon des **Bois Korogu / forêt perdue**
      (sortie du chemin prévu → renvoi) + **message** « il te manque X pour aller ici ». Remplace le
      kill DeathLink de la gate armure Créature Divine (V1) par une mécanique moins punitive.
- [ ] **Cap cœurs / endurance + overflow en rubis** : plafonner le max de cœurs et d'endurance ;
      si le joueur en gagnerait au-delà du plafond → convertir en **don de 500 rubis**.

### Décompilations à étudier (apprendre → ré-implémenter, PAS redistribuer)
- [ ] **`DAR 3.6 - BCML - FREE.zip`** : bloque une action selon une autre (ex : **en combat → sanctuaire
      non ouvrable** + affichage d'un message). Mécanisme réutilisable pour nos **zones non accessibles**
      / gates (message + blocage conditionnel). Décompiler pour comprendre le HOW, puis ré-implémenter.
