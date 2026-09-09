# Contexte partagé — BOTWpelago (BotW × Archipelago)

Lu par Claude Code **et** par Codex, et joint automatiquement aux consultations
cross-modèles.

Les faits techniques établis (format de save, recette de hash, noms de flags,
adresses) vivent dans **`.claude/CLAUDE.md`** ; le backlog dans
**`docs/CHECKLIST.md`** ; le journal de rétro-ingénierie dans `docs/status.md`.
Ce fichier-ci ne contient que ce qui ne se lit ni dans le code ni dans ces trois
documents.

## Ce qu'est ce projet

Support Archipelago (randomizer multiworld) pour *Zelda: Breath of the Wild*,
Wii U **1.5.0** sous Cemu. Deux moitiés : un `.apworld` côté hôte qui place les
items, et une application joueur (GUI Tkinter + client AP + copie embarquée du
BotW Randomizer) qui construit un graphic pack Cemu, détecte les checks en
lisant `game_data.sav`, et **injecte les items reçus dans la mémoire vive de
Cemu pendant que le jeu tourne**.

Ce n'est **pas** un mod de jeu classique ni un paquet Python installable : c'est
du code destiné à être déposé dans une installation Archipelago, plus un exe
joueur figé par PyInstaller.

| Dossier | Rôle |
|---|---|
| `worlds/botw/` | le `.apworld` — items, locations, règles, régions, émission du config |
| `BotWClient/` | client AP : parsing de save, WebSocket, injection mémoire live |
| `botwpelago/` | app joueur : GUI + `pack_builder` (config → rando embarqué → pack Cemu) |
| `data/` | JSON **générés** (locations, gate_items, shrines, flags…) — ne pas éditer à la main |
| `tools/` | pipeline de build + outils de rétro-ingénierie ; `tools/archive/` = ancien |
| `mod/` | contenu du graphic pack (murs de région, kit de départ, toasts) |
| `rando/` | BotW Randomizer de MelonSpeedruns, GPL v3, exécuté comme processus séparé |
| `docs/` | CHECKLIST (backlog), status.md (journal RE), memory_map, setup |
| `tests/` | 72 tests — intégrité des données, parser de save, localisation mémoire |

## Commandes

```sh
python -m pytest tests/                    # 72 tests, ~1 s — le critère de fin
ruff check worlds/botw tests               # lint (line-length 100, py311)

python tools/build_apworld.py --install    # -> C:/ProgramData/Archipelago/custom_worlds
python tools/build_poptracker.py --install # -> D:/poptracker/packs/ (puis REDÉMARRER PopTracker)
python -m BotWClient.BotWClient --debug-save --save chemin/game_data.sav
python -m BotWClient.BotWClient --diff-saves before.sav after.sav
```

⚠️ `python tools/play_local.py` **SUPPRIME la save Cemu** et héberge un serveur.
Pour tester la seule génération, ne rejouer que les étapes apworld + generate.

## Contraintes non évidentes

Des faits, pas des préférences — chacune a coûté une session de débogage ou une
save corrompue.

1. **Jamais écrire `game_data.sav` pendant que Cemu tourne.** Cemu garde la main
   sur ses autosaves ; une écriture concurrente produit une save incohérente puis
   un crash. Quand Cemu est attaché, la livraison passe **uniquement** par la
   mémoire ; la voie fichier n'est ouverte que si `cemu_process_running()` est
   faux. Ce verrou est global (`_inject_pending`, `_enforce_retention`,
   `_bank_spirit_orbs`, `can_inject_now`) — ne pas y ouvrir une brèche « juste
   pour ce cas-là ».
2. **`game_data.sav` n'est pas du BYML.** Binaire big-endian maison ; `oead`
   dessus ne produit que des erreurs plausibles. Parser dédié :
   `BotWClient/save_parser.py`. `oead` ne sert qu'aux scripts d'extraction.
3. **La recette de hash est prouvée, ne pas la ré-instruire.**
   `flag_id = zlib.crc32(nom.encode("ascii")) & 0xFFFFFFFF`, stocké big-endian.
   Vérifiée contre les 42 537 champs HashValue de `gamedata.ssarc`.
4. **Une copie freed de la poche ressemble à une poche valide.** Les
   auto-références passent sur de la mémoire libérée intacte : on suit donc la
   poche par une **ancre statique** (section data guest `0x10xxxxxx`, offset
   objet aligné, relue à chaque accès), jamais par une adresse mémorisée. Et
   toute écriture mémoire reste **gelée** tant que `delivery_ready` est faux —
   c'est-à-dire tant que la tablette Sheikah n'est pas en poche. Ignorer ça a
   produit trois crashs `0xc0000005` et une liste d'inventaire détruite.
5. **Le rando pré-initialise des flags à toute nouvelle partie** (son « skip
   plateau »). Les 7 locations concernées sont donc **hors pool**
   (`RANDO_INIT_LOCATION_IDS` dans `worlds/botw/locations.py`) — les remettre
   dans le pool y ferait placer la paravoile, tuant la gate d'entrée.
6. **Les runes sont des items de départ, jamais dans le pool.** Sans elles, les
   sanctuaires du plateau — qui sont des checks — sont infaisables : softlock.
   Ne jamais retenir un flag de rune.
7. **Le compteur de sanctuaires = `MAX(DungeonClearCounter, nb Clear_Dungeon* à 1)`.**
   Le `s32` du jeu reste à 0 sur une partie moddée : s'appuyer dessus seul rend
   le goal et le tracker morts. Les sanctuaires pré-clearés par le rando sont
   exclus du compte.
8. **DeathLink est du pur Python et il est validé — ne pas y toucher.** Pas de
   codecave (le hook natif bute sur le recompilateur Cemu). Piège de protocole :
   on **envoie** `Bounce`, le serveur rediffuse en `Bounced` — c'est `Bounced`
   qu'il faut écouter.
9. **La numérotation interne des sanctuaires n'est pas l'ordre de jeu**
   (Oman Au = `Dungeon038`, pas 001). Le flag de complétion est
   `Clear_DungeonNNN`, pas `Location_MainField_*` (ancien, faux).
10. **Consigne de release (2026-07-11) : pas de rebuild d'exe ni de merge
    `dev` → `main` tant que toute la checklist n'est pas verte.** La préparation
    est déjà faite ; c'est la dernière étape, pas une étape de confort.

## Conventions

- **Critère de fin de tâche** : `python -m pytest tests/` vert **et**
  `docs/CHECKLIST.md` mis à jour. Beaucoup de correctifs ne sont réellement
  prouvés qu'**in-game** : tant qu'une case dit « RESTE : re-valider in-game »,
  la tâche n'est pas finie, elle attend une run.
- Branche de travail : **`dev`**. `main` ne reçoit qu'un merge de release.
- Python **3.11+**. Dépendance runtime unique : `websockets`. `oead` est réservé
  aux outils hors-ligne. Une nouvelle dépendance runtime se justifie.
- Cemu émule du **PPC big-endian** : les booléens 1 octet sont neutres, tout
  `u16`/`u32` doit être byte-swappé. Les vtables `0x10xxxxxx` sont constantes en
  v208 ; les adresses guest se re-basent, ne se recopient pas.
- Le code et les commentaires sont en anglais ; la documentation et les messages
  de commit, en français.

### Vocabulaire — sa confusion fausse le résultat

- **check / location** = un endroit du jeu qui, une fois atteint, est signalé au
  serveur. **item** = ce que le serveur envoie en retour. Un sanctuaire est les
  deux à des titres différents : ne pas dire « item » pour un check.
- **flag** = entrée GameData `(flag_id, valeur)` dans la save ou en mémoire.
- **gate** / **mur de région** = blocage logique (règle de l'apworld) ou physique
  (téléport posé par le pack). Les deux doivent rester cohérents.
- **baseline** = checks déjà vrais au premier poll, jamais réémis. **freebies** =
  les 7 locations pré-vraies du rando, elles, toujours émises.
- **poche / pouch node** = nœud d'inventaire en mémoire vive. **splice** =
  insertion triée dans cette liste.

## Données protégées

`.ai/protected.json` (projet) + `~/.ai/protected.json` (machine). Ce qui ne sort
pas d'ici :

- **`.mcp.json`** — il contient une clé API Perplexity en clair. Le fichier est
  gitignoré et n'a jamais été commité ; il ne doit pas non plus partir dans un
  prompt. Le motif `pplx-*` est bloqué en plus du chemin.
- Aucun autre chemin n'est filtré : le code, les données générées, les saves de
  test et les logs peuvent être joints à une consultation.

Pour travailler sur des données de save, `before.sav` / `after.sav` à la racine
sont des saves de test, comparables par
`python -m BotWClient.BotWClient --diff-saves` — la save réelle du joueur n'est
jamais nécessaire.
