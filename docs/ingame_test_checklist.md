# BOTWpelago — Check-list de test EN JEU (Cemu + AP + client)

Ce qui ne peut se valider qu'avec Cemu lancé, le client connecté à AP, et une partie en cours.
Coche au fur et à mesure. ⚠️ = point incertain / à mesurer. Statut au 2026-07-01.

## A. Livraison d'items (instantané EN JEU + persistant après reload) — ✅ VALIDÉ
- [x] Ingrédients / matériaux reçus → apparaissent instantanément + **persistent après reload**
- [x] Orbes (Spirit Orb) → le compteur d'orbes monte et **persiste** (ré-assertion post-réallocation)
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
- [ ] 🔧 **Rubis -298 « pour rien »** (adresse rubis périmée pendant une réallocation) → **fix appliqué** (garde-fou live_add_rupees + bornes 0..999999) → **à re-tester**

## F. Robustesse / à surveiller
- [ ] 🔧 **Crash après un sanctuaire (inventaire PLEIN)** : cause = martèlement de `live_create_item` sur un pool épuisé pendant que le jeu réalloue la poche (cutscene). **Fix appliqué** (arrêt du martèlement : `_pool_exhausted` tient jusqu'au reload) → **à re-tester**. NB: aggravé par un inventaire saturé des tests « release all » — en jeu normal (poche non pleine) le pool a des nœuds libres. Si ça revient : `D:\Emulateur\Cemu\cemu_1.18.1\log.txt` + contexte.
- [x] Grosse rafale → re-localisation d'inventaire OK, **save jamais corrompue** au reload

## G. PopTracker (overlay, en live) — ✅ VALIDÉ
- [x] Compteurs live : **Shrines Cleared** + **Orbes** montent en jouant (poussés par le client)
- [x] **Required** = la valeur du YAML (ex: 5)
- [x] Marqueurs carte se **colorent** quand les checks arrivent
- [x] Items-clés s'**allument** à la réception (paravoile, champions, épée…)

## H. Après validation
- [ ] Rebuild `BOTWpelago.exe` (`pyinstaller BOTWpelago.spec --noconfirm --clean`)
- [ ] Flux complet (build pack + jouer + atteindre le goal) → merge `dev` → `main` (jalon V1)
