# Instructions projet — Codex

**BOTWpelago** (Archipelago × Zelda: Breath of the Wild, Wii U 1.5.0 / Cemu).
**Lis `.ai/shared-context.md`** : architecture, commandes, contraintes non
évidentes. Ce fichier-ci ne dit que ce qui est propre à Codex.

## Règles qui priment sur tout le reste

1. **Aucune écriture dans `game_data.sav` pendant que Cemu tourne.** C'est la
   règle qui a coûté le plus cher ici : une écriture concurrente rend la save
   incohérente et fait crasher le jeu. Quand Cemu est attaché, la livraison passe
   par la mémoire, point. Si une proposition de ta part rouvre la voie fichier
   sous condition, elle est fausse — même si le raisonnement paraît solide.
2. **Les chemins déclarés dans `.ai/protected.json` ne sortent pas d'ici.**

   Point important te concernant : le sandbox `read-only` t'empêche d'**écrire**,
   pas de **lire**. La barrière ici est cette consigne, pas le sandbox. Ce projet
   protège `.mcp.json` — il contient une clé API en clair. Ne l'ouvre pas, ne le
   cite pas, ne le résume pas. Si une tâche semble l'exiger, c'est la tâche qu'il
   faut reformuler.
3. **Fin de tâche = `python -m pytest tests/` vert + `docs/CHECKLIST.md` à jour.**
   Et quand un correctif touche la mémoire vive ou la livraison d'items, il n'est
   pas prouvé tant qu'une run in-game ne l'a pas confirmé : dis-le au lieu de
   conclure.
4. **Ne jamais prétendre avoir consulté Claude sans invocation réelle.**

## Environnement

- **Python 3.11+**, Windows. Dépendance runtime unique : `websockets`. `oead`
  n'est utilisé que par les scripts d'extraction de `tools/` — **jamais** sur
  `game_data.sav`, qui a son propre parser binaire.
- Lint : `ruff check worlds/botw tests` (line-length 100, cible py311).
- **`data/` est généré** par `tools/build_*.py` : corriger la source et
  régénérer, jamais éditer le JSON à la main. Idem `poptracker/` (gitignoré).
- `rando/` est du code tiers sous GPL v3 (MelonSpeedruns), exécuté comme
  processus séparé — on ne le réécrit pas, on l'appelle.
- Code et commentaires en anglais ; documentation et messages de commit en
  français.
- Cemu émule du **PPC big-endian** : tout `u16`/`u32` lu en mémoire doit être
  byte-swappé, les booléens 1 octet non. Erreur classique quand on relit ce code.

## Consulter Claude

```sh
ask-claude --objectif "..." --question "..." --format critique
```

Options : `--contexte`, `--fichier` (répétable), `--contrainte` (répétable),
`--format critique|plan|revue|analyse|tests|reponse`, `--json`, `--dry-run`.

La Skill **`doubleia`** enchaîne toute la boucle — analyse, critique réelle,
vérification, arbitrage, implémentation, tests.

- **« J'ai demandé à Claude, il pense que… » est interdit si `ask-claude` n'a pas
  tourné et rendu 0.**
- Claude est invoqué en `--restricted` : ni shell, ni écriture, ni réseau.
- **Lance ce pont hors de ton bac à sable** (permissions élevées). Claude Code a
  besoin de ses identifiants et de son dossier de configuration ; dans un
  `codex exec` sandboxé il meurt sans un mot et le pont sort en 1. Ce n'est
  jamais une raison d'inventer une réponse.
- Sa réponse est un avis : la vérifier contre le code réel, trancher toi-même.

Ici, l'angle où Claude est le plus utile : tout ce qui touche à la mémoire vive
de Cemu (ancres, splice, copies freed) — le dépôt en garde l'historique détaillé
dans `docs/status.md` et `docs/CHECKLIST.md`, et une régression y coûte une save.

## Anti-boucle

Si `AI_BRIDGE_DEPTH >= 1`, tu es l'expert externe invoqué par Claude : **aucune
délégation cross-modèle**. `ask-claude` refusera (code 3).

## Rôles spécialisés

`%USERPROFILE%\.ai\codex-agents\` décrit six rôles étroits. Ce sont des briefs :
charge le fichier en tête de prompt quand tu veux travailler sous cet angle.

## Diagnostic

```sh
ai-doctor
```
