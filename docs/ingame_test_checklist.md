# BOTWpelago — Check-list de test EN JEU (Cemu + AP + client)

Ce qui ne peut se valider qu'avec Cemu lancé, le client connecté à AP, et une partie en cours.
Coche au fur et à mesure. ⚠️ = point incertain / à mesurer. Statut au 2026-07-01.

## A. Livraison d'items (instantané EN JEU + persistant après reload) — ✅ VALIDÉ
- [x] **Save FRAÎCHE (Plateau) : les items s'ajoutent SANS déco/reco** — le jeu **réalloue le buffer pouch** et le client restait collé sur l'**ancien buffer** (paraît valide → non détecté) → « pool épuisé » jusqu'à une déco/reco. Fix : `refresh_inventory_if_stale` re-localise quand le pool paraît épuisé en **préférant un buffer AVEC nœuds libres** → repart tout seul (validé : `Inventaire re-localisé (réallocation détectée)` + livraison instantanée).
- [ ] 🔧 **Pas de déco AP (1011) pendant la re-localisation** — le scan `prefer_free` appelait le check « nœud libre » (coûteux) sur des centaines de candidats → thread monopolisé → keepalive AP tombé (1011). Fix : check réservé aux candidats **forts** (score ≥ seuil) et **plafonné** (`_FREE_NODE_CHECK_CAP=8`). → **à re-tester** (re-localisation ne doit plus déco)
- [ ] 🔧 **Crash du JEU à la sortie de sanctuaire (save à 0 orbe)** — cause : l'orbe (`Obj_DungeonClearSeal`) absent de la poche était **CRÉÉ** comme faux nœud key-item ; le jeu réconcilie l'inventaire à la sortie du sanctuaire et **crashe**. Fix : `Obj_DungeonClearSeal` est un item **géré par le jeu** → **jamais créé en live** (bump si présent uniquement ; persistance via `DungeonClearSealNum` + banking save). → **à re-tester sur save neuve**
- [ ] 🔧 **Crash du JEU quand on crée un item PENDANT une transition (sortie de sanctuaire)** — pattern des logs : une **re-localisation** (le jeu réalloue la poche pendant le chargement) suivie d'une **création live immédiate** dans un buffer que le jeu reconstruit encore → corruption → crash (+ `[DeathLink] Mort` = HP lu à 0 = transition). Fix : **garde de stabilité** — après un changement de base pouch, aucune création tant que le buffer n'est pas resté stable un cycle de flush (`_INV_SETTLE_TIME=4s`) ; l'item est livré au poll suivant, buffer stabilisé. → **à re-tester**
- [ ] 🔧 **Crash du JEU pendant une création live (générique)** — la liste de nœuds est scannée au début de `live_create_item` ; si le jeu **alloue le nœud libre** (ou déplace l'ancre) entre le scan et l'écriture, splicer corrompt la liste chaînée → crash. Fix : **re-validation juste avant d'écrire** (nœud libre TOUJOURS type 0xFFFFFFFF ? ancre plausible ?) → sinon reporté. → **à re-tester**
- [ ] ℹ️ **-98 rubis** = corruption du **crash jeu**, PAS une écriture client : tous les chemins rubis bornent à `max(0,…)` et refusent une lecture hors `[0, 999999]`. Le strip a en plus une garde symétrique (chute OU bond anormal vs shadow → reporté). Devrait disparaître une fois le crash réglé.
- [x] Ingrédients / matériaux reçus → apparaissent instantanément + **persistent après reload**
- [ ] 🔧 **Orbes (Spirit Orb) : le compteur monte ET tient** — bug : l'orbe reçu d'AP retombait à une valeur d'avant (le jeu restaure le nœud pouch à sa valeur sérialisée + la cible qty était oubliée dès la file vide). Fix : cible PERSISTANTE (jamais oubliée) re-assertée **chaque poll** (`maintain_persistent` : pouch `Obj_DungeonClearSeal` + gamedata `DungeonClearSealNum`, bump-up only) **+ banking dans la save** (survit au reload, comme un flag de gate). ⚠️ dépenser des orbes à une statue de la déesse peut être temporairement contré (limite connue). → **à re-tester** (compter précisément : orbes AP + orbes naturels des coffres)
- [x] Flèches (Arrows/Fire/Ice/Shock/Bomb) → apparaissent même **sans arc** + persistent
- [x] Rubis (Rupees x100) → portefeuille monte
- [x] Bump d'un stack déjà présent (ex: viande) → la quantité monte et **tient** après reload
- [x] Rafale « release all » (~130 items) → **aucun crash**, **aucune déco AP**, le pool se régénère au reload

## B. Gates & quêtes (items de progression, appliqués au rechargement)
- [x] Paravoile reçue → livrée, on peut **quitter le Plateau**
- [ ] ⚠️ **Paravoile → quête** : « En quête d'Impa » devient **active** dans le journal (pas de softlock) — *fix récent à confirmer*
- [ ] 4 Champions → capacité **utilisable** après reload (Daruk's, Revali's, Mipha's, Urbosa's)
- [ ] Master Sword → apparaît / équipable
- [ ] Runes de départ → fonctionnent (Magnésis / Stase / Cryonis / Bombe / Caméra)
- [ ] Tenues (Flamebreaker / Snowquill / Vai / Zora) → équipables

## C. Goal / victoire (option 2 modes)
- [ ] Mode **shrines** : atteindre N sanctuaires → « Goal complete! » envoyé au serveur
- [ ] Mode **full** : sanctuaires + 4 Créatures + Master Sword + Arc de Lumière → goal complete
- [ ] ⚠️ **Vérifier le flag Arc de Lumière** : récupérer l'Arc au combat final → **diff de save** pour confirmer `IsGet_Weapon_Bow_071` (sinon le mode « full » ne se validera jamais)

## D. DeathLink — ✅ VALIDÉ
- [x] Mourir en jeu (chute / combat) → **envoie** une mort au multiworld
- [x] **Recevoir** une mort → Link meurt (HP max → 0)
- [x] Pas de boucle infinie (ne pas se renvoyer sa propre mort reçue)

## E. Checks sortants
- [x] Ouvrir un **coffre de sanctuaire** → check AP envoyé **ET** rubis-placeholder (+1 vert) retiré
- [ ] Certains coffres ouverts pendant un moment « inventaire pas dispo » → le rubis est **quand même** retiré (dette rejouée)
- [ ] Clear sanctuaire / tour / créature / souvenir / lieu / quête → check envoyé selon le mode
- [ ] 🔧 **Rubis -298 « pour rien »** : vraie cause = après un `+300`, le strip d'un coffre relisait le portefeuille sur une **adresse périmée** (lecture `2` au lieu de `300`) et écrivait `current-1` → **SET** le portefeuille à 1 au lieu de retirer 1 (perte de ~298). Fix : `live_add_rupees` mémorise la dernière valeur écrite (`_rupee_shadow`) ; si un strip lit une valeur qui a **chuté anormalement** (≥50) vs shadow → re-localise puis **REPORTE** le strip (dette rejouée) au lieu de corrompre → **à re-tester**

## F. Robustesse / à surveiller
- [ ] 🔧 **Crash « sans raison » (même sans entrer dans un sanctuaire)** : VRAIE cause trouvée dans le log Cemu → `FSC: File create failed for .../game_data.sav`. Le client tenait `game_data.sav` (lecture/écriture) pile quand Cemu faisait une **autosave** → save Cemu ratée → état incohérent → crash. **Fix appliqué** : (1) toutes les **lectures** de `game_data.sav` en **partage total Windows** (`FILE_SHARE_READ|WRITE|DELETE`, `_read_shared`) → ne bloquent plus jamais Cemu ; (2) `get_spirit_orbs` lit le **cache** (`self._raw`) au lieu de relire le fichier à chaque poll ; (3) toutes les **écritures** de save rendues **atomiques** (`_write_atomic` : temp + rename) pour minimiser le verrou. → **à re-tester**. Côté Cemu : activer **AsyncCompile** (Options → Graphics) pour réduire les freezes de compilation shaders.
- [ ] 🔧 **Crash après un sanctuaire (inventaire PLEIN)** : cause = martèlement de `live_create_item` sur un pool épuisé pendant que le jeu réalloue la poche (cutscene). **Fix appliqué** (arrêt du martèlement : `_pool_exhausted` tient jusqu'au reload) → **à re-tester**. NB: aggravé par un inventaire saturé des tests « release all » — en jeu normal (poche non pleine) le pool a des nœuds libres. Si ça revient : `D:\Emulateur\Cemu\cemu_1.18.1\log.txt` + contexte.
- [x] Grosse rafale → re-localisation d'inventaire OK, **save jamais corrompue** au reload

## G. PopTracker (overlay, en live) — ✅ VALIDÉ
- [x] Compteurs live : **Shrines Cleared** + **Orbes** montent en jouant (poussés par le client)
- [ ] 🔧 **Orbes stables** : le compteur d'orbes est maintenant lu en **mémoire live** (pas dans la save) quand Cemu est attaché → plus d'oscillation (2↔3) due à la rotation des auto-saves → **à re-vérifier**
- [x] **Required** = la valeur du YAML (ex: 5)
- [x] Marqueurs carte se **colorent** quand les checks arrivent
- [x] Items-clés s'**allument** à la réception (paravoile, champions, épée…)

## H. Après validation
- [ ] Rebuild `BOTWpelago.exe` (`pyinstaller BOTWpelago.spec --noconfirm --clean`)
- [ ] Flux complet (build pack + jouer + atteindre le goal) → merge `dev` → `main` (jalon V1)
