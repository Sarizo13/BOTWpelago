# Recherche — Injection d'objets en LIVE dans BotW (Wii U 1.5.0, Cemu)

> Source : Perplexity (Sonar), 2026-06-28. Question : comment ajouter un pouch item à
> l'inventaire de Link **en temps réel** (instantané + persistant) depuis un **processus
> externe** (RWProcessMemory sur cemu.exe), sachant que (1) écrire la GameData PorchItem
> en live ne persiste pas, (2) cloner/splicer un nœud PouchItem donne un nœud « No Image »
> qui corrompt la liste, (3) appeler `PauseMenuDataMgr::addItem` exige un hook qui bute sur
> le JIT de Cemu.

## TL;DR exploitable
- **Aucune technique publique** pour appeler une fonction PPC guest (ex. `addItem`) **une
  seule fois de façon fiable depuis un process externe** sous le JIT de Cemu. Tous les
  outils « qui appellent du code » sont **internes** (Cheat Engine Auto-Assembler, trainers
  injectés dans cemu.exe) et hookent le x86 JIT, pas le guest depuis l'extérieur.
- **MAIS** les trainers live qui MARCHENT (table CE de **Drivium**, « BOTW Trainer 1.5.0 »)
  ajoutent/éditent l'inventaire par **écriture mémoire directe** des structures d'inventaire
  RUNTIME (méthode « a ») — PAS par appel d'`addItem`. La table « playerbase » de Drivium
  « peuple tous les slots d'inventaire » puis on édite chaque slot → l'objet apparaît en jeu.
- Donc la voie réaliste = **faire ce que fait la table CE : écrire correctement la structure
  PouchItem runtime** (avec TOUS les champs : identité d'objet, type, quantité, ET le
  pointeur de ressource/icône). Notre `live_create_item` échouait car la mise en page exacte
  du PouchItem v208 était fausse (d'où « No Image » = pointeur de ressource non résolu).

## Pourquoi « run once then freeze » (notre codecave DeathLink)
Cemu traduit les blocs PPC en x86 et les **cache**. Patcher les octets PPC APRÈS la
compilation d'un bloc → l'ancienne traduction x86 continue de tourner (patch ignoré) jusqu'à
invalidation/recompilation ; patcher le x86 JIT directement casse le flot de contrôle →
stalls/freeze. Cemu **n'expose pas d'API publique** pour invalider le cache JIT depuis
l'extérieur. Les trainers qui marchent hookent des **données** (HP, stamina, position),
pas du code, ou injectent en interne (CE) sur des hotspots testés empiriquement.

## Layout PouchItem / PauseMenuDataMgr
- **Pas publiquement documenté** pour BotW Wii U v208 (zeldaret/botw cible le Switch, offsets
  non figés). À RE nous-mêmes.
- Un `PouchItem` est un nœud de `sead::OffsetList<PouchItem>` ; il contient : liens de liste,
  **identité d'objet** (tag string `Item_Fruit_A` ou hash + enum catégorie), flags
  (équipé/favori/durabilité), et **pointeur(s) vers les données de ressource** (icône, message).
- **« No Image »** = soit le pointeur de ressource pointe encore vers le template cloné, soit
  l'ID est posé mais l'asset n'est pas résolu → placeholder. C'est le champ critique à poser.

## Fonction de reconstruction poche ← GameData
- Pas de symbole public « rebuild pouch from GameData » figé dans zeldaret. Existe (tourne au
  chargement de save) mais nom/adresse non publiés → à localiser par analyse si on veut la voie
  GameData+resync.

## Mods item-give sur Cemu/Wii U
- Tous les item-give LIVE documentés ciblent le **Switch/Atmosphere** (hook NSO/KIP d'`addItem`).
  Sur Wii U/Cemu : uniquement des **éditeurs de save** ou des **trainers à écriture directe**.
  **Aucun** multiworld/mod Cemu connu n'injecte des objets reçus en live via `addItem`.

## Sources
- [4] FearLess — table CE BotW Cemu (Drivium) : https://fearlessrevolution.com/viewtopic.php?t=2335&start=210
- [5] r/cemu mirror : https://www.reddit.com/r/cemu/comments/c25qi0/
- [7] GBAtemp — BoTW Trainer codes (items/armor) : https://gbatemp.net/threads/botw-trainer-codes-for-items-armor-and-more-wip.480316/
- [8] YouTube — BOTW Trainer 1.5.0 Wii U : https://www.youtube.com/watch?v=j3A0qfM5NQE
- [9] Nexus — Cemu BotW CE utilities : https://www.nexusmods.com/games/legendofzeldabreathofthewild/mods?categoryName=Utilities

## Conclusion / piste retenue
La méthode (a) — **écriture directe de la structure PouchItem runtime** — est PROUVÉE
viable (les trainers le font, objets visibles + persistants car le jeu sérialise la liste
runtime au save). Notre échec = **mauvais layout PouchItem**. Donc next step = **RE précis du
PouchItem v208** : faire un **diff mémoire de l'inventaire avant/après un ramassage normal**
in-game (un objet connu) pour capturer la mise en page EXACTE d'un nœud fraîchement ajouté
(tous les champs, dont le pointeur de ressource), puis répliquer ça correctement dans
`live_create_item`. C'est notre propre RE (comme HP/DeathLink), pas du public.
