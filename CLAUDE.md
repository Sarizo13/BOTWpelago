# Instructions projet — Claude Code

**BOTWpelago** (Archipelago × Zelda: Breath of the Wild, Wii U 1.5.0 / Cemu).

Trois fichiers, trois rôles — ne pas les dupliquer :

| Fichier | Contenu |
|---|---|
| **`.claude/CLAUDE.md`** | **les faits du domaine** : format de save, recette de hash, noms et hachés de flags, ID ranges, architecture client, règles critiques. La référence technique. |
| `.ai/shared-context.md` | ce que Claude **et** Codex partagent : commandes, contraintes coûteuses, vocabulaire. Joint automatiquement aux consultations cross-modèles. |
| ce fichier | la façon de travailler côté Claude : sous-agents, consultation de Codex, anti-boucle. |

Le backlog fait foi dans **`docs/CHECKLIST.md`**, le journal de
rétro-ingénierie dans `docs/status.md`.

## Règles qui priment sur tout le reste

1. **Aucune écriture dans `game_data.sav` pendant que Cemu tourne.** Une
   écriture concurrente rend la save incohérente et fait crasher le jeu — c'est
   la panne la plus chère de ce projet. Attaché : livraison par la mémoire,
   point. Le verrou `cemu_process_running()` ne se contourne pas « juste pour ce
   cas-là ».
2. **Les chemins déclarés dans `.ai/protected.json` ne sortent pas d'ici.**
   `.mcp.json` contient une clé API en clair. Si un garde-fou bloque, **il ne se
   contourne pas** : c'est le signal qu'il faut reformuler la tâche.
3. **Fin de tâche = `python -m pytest tests/` vert + `docs/CHECKLIST.md` à jour.**
   Pas « fini avec une réserve ». Et un correctif qui touche la mémoire vive ou
   la livraison n'est pas prouvé tant qu'une run in-game ne l'a pas confirmé :
   le dire franchement plutôt que de cocher.
4. **Ne jamais prétendre avoir consulté Codex sans invocation réelle.**

## Sous-agents

`~/.claude/agents/` — six rôles étroits :

| Agent | Quand |
|---|---|
| `explorateur` | balayer plusieurs fichiers, ne ramener que la carte |
| `relecteur` | relire un changement non trivial avant de le déclarer fini |
| `architecte` | instruire un choix de conception coûteux à défaire |
| `debogueur` | reproduire et expliquer un comportement inattendu |
| `testeur` | cas limites manquants, suite de tests |
| `docs-chercheur` | vérifier une API à la version exacte du projet |

Prendre un sous-agent quand plusieurs investigations sont indépendantes, quand
une tâche produirait beaucoup de contexte inutile, ou quand l'expertise est
utile. **Pas pour une modification triviale.**

## Consulter Codex

```sh
ask-codex --objectif "..." --question "..." --format critique
```

Deux entrées : **`/doubleia`** (commande explicite, exécute toute la boucle) et
**d'initiative** selon la politique ci-dessous.

- **« J'ai demandé à Codex, il pense que… » est interdit si `ask-codex` n'a pas
  tourné et rendu 0.** Si le pont échoue, le dire et poursuivre seul.
- Consulter pour : bug difficile, architecture, changement transversal,
  sécurité, concurrence, refactor risqué, revue avant validation, confiance
  faible. **Pas** pour un renommage, une typo, une ligne évidente.
- Codex est en lecture seule. **C'est Claude qui écrit le code**, toujours.
- Sa réponse est un avis : la vérifier contre le code réel (il invente des noms
  de fonctions avec aplomb), isoler les désaccords, trancher soi-même.

Ici, les sujets qui méritent vraiment un second modèle : l'injection mémoire
(`BotWClient/memory_injector.py` — ancres, splice, copies freed), la logique de
baseline/freebies, et toute modification qui pourrait rouvrir une voie d'écriture
fichier. Ce sont les endroits où une erreur coûte une save, pas un test rouge.

## Anti-boucle

Si `AI_BRIDGE_DEPTH >= 1`, tu es l'expert externe invoqué par Codex : **aucune
délégation cross-modèle**. Les ponts refuseront (code 3). Tu peux lire,
raisonner, et utiliser tes sous-agents natifs.

## Diagnostic

```sh
ai-doctor          # CLI, ponts, anti-boucle, garde-fou, Skills
```
