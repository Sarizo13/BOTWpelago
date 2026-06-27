# BOTWpelago — Mod natif « addItem » (V2)

Objectif : ajouter un item par la **voie officielle du jeu** (instantané **et** persistant,
icône/compte corrects, zéro fantôme) en appelant `PauseMenuDataMgr::addItem` depuis un
**codecave par frame** (graphic pack Cemu) qui lit une **mailbox** écrite par le client Python.

BotW WiiU **v208/1.5.0** uniquement. `moduleMatches = 0x6267BFD0`.

## Adresses (guest, constantes v208 — toutes validées)

| Élément | Adresse | Note |
|---|---|---|
| `addItem(mgr, name, type, list, count, f6, f7, f8)` | **`0x02EB3DD0`** | entrée réelle (Ghidra disait 02eb3df0) |
| Singleton PorchItem manager | **`*(0x10469978)`** | validé live (liste active → sentinelle → .data) |
| Liste items | `manager + 0x4C` | sead::OffsetList (sentinelle = mgr+0x4c) |
| vtable nom (sead::SafeString) | `0x1021B58C` | utilisé par le jeu pour les noms d'items |
| Item DB (lookups) | `*(0x1046CA84)` | non requis si le `type` vient de Python |
| createNode (interne) | `0x02EB0A70` | appelé par addItem si l'item est absent |
| vtable PouchItem / FixedSafeString | `0x1021B5D4` / `0x1021B524` | repères structure |

### Convention d'appel d'`addItem` (PPC)
```
r3 = manager            (*(0x10469978))
r4 = &SafeString        ({ cstr@0x00 -> nom ; vtable@0x04 = 0x1021B58C })
r5 = type               (0..9 : 0 arme,1 arc,2 flèche,3 bouclier,4-6 armure,7 matériau,8 nourriture,9 key)
r6 = manager + 0x4C     (liste)
r7 = count
r8 = r9 = r10 = 0       (flags ; 0 = cas simple matériau/nourriture)
```
Le `SafeString` = 2 mots : `[0]=ptr vers le buffer du nom (ASCII null-terminé)`, `[1]=0x1021B58C`.

## Mailbox (mémoire scratch, écrite par Python, lue par le codecave)
Allouée DANS le codecave (`.data` du graphic pack), à une adresse guest fixe `MB` :
```
MB+0x00  u32  trigger   (Python -> 1 pour demander ; codecave remet 0)
MB+0x04  u32  count
MB+0x08  u32  type
MB+0x0C  u32  cstr_ptr  = MB+0x14  (champ [0] du SafeString)
MB+0x10  u32  vtable    = 0x1021B58C (champ [1] du SafeString)
MB+0x14  char[64] name  (ASCII, null-terminé)
```
Le SafeString passé à addItem = `&(MB+0x0C)`.

## Codecave (pseudo-PPC, par frame)
```
hook:
  <instruction originale écrasée>
  load   r11, MB+0x00            ; trigger
  cmpwi  r11, 0
  beq    done
  lis    r3, 0x1047 ; lwz r3, -0x6688(r3)   ; r3 = *(0x10469978) = manager
  cmpwi  r3, 0
  beq    done                    ; manager pas prêt
  addi   r4, MB, 0x0C            ; &SafeString
  lwz    r5, MB+0x08             ; type
  addi   r6, r3, 0x4C            ; liste
  lwz    r7, MB+0x04             ; count
  li     r8,0 ; li r9,0 ; li r10,0
  bla    0x02EB3DD0              ; addItem
  li     r0, 0
  stw    r0, MB+0x00            ; trigger = 0
done:
  b      <retour au hook+4>
```
(Sauver/restaurer r0/CR/LR autour de l'appel ; `bla` = branch-link-absolute pour franchir >32 Mo.)

## Python (client)
`tools`/`BotWClient` écrit en mémoire Cemu (via `CemuMemoryBridge`) :
1. écrire `name` (ASCII) à `MB+0x14`, `count` à `MB+0x04`, `type` à `MB+0x08`,
   `cstr_ptr=MB+0x14` à `MB+0x0C`, `vtable=0x1021B58C` à `MB+0x10`.
2. écrire `trigger=1` à `MB+0x00`.
3. attendre que le codecave remette `trigger=0` (item ajouté) avant la demande suivante.
   (mappage guest MB -> host = MB + cemu_mem_base de session.)

## Reste à finaliser
1. **Point de hook par frame** v208 (style FPS++) — instruction sûre exécutée chaque frame.
2. **Adresse guest `MB`** = `.origin` du codecave (zone libre, ex. 0x02EC8000+ dans un trou de .text,
   ou une zone data du codecave).
3. **Vérifier le vtable 0x1021B58C** : sa méthode +0x1c doit juste lire/longueur le nom (lecture
   seule) — confirmer live avant l'appel réel (un mauvais appel crashe Cemu → tester prudemment).
4. Format exact du fichier `patches.txt` Cemu + intégration au `.exe` (install du graphic pack).
