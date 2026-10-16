# Contenitori

[English](../en/containers.md) | [README](../../README.it.md)

Un contenitore è `{x : a_k . x <= b_k per ogni k}` intersecato con
`{x : |x - c_j| <= R_j per ogni j}`. Qualsiasi contenitore con una descrizione di
questo tipo funziona con l'ottimizzatore e con il verificatore, purché sia
convesso e limitato (un disco, oppure abbastanza semipiani da chiudere la
regione). Le normali dei semipiani sono normalizzate alla costruzione.

## Tipi predefiniti (`type` della spec)

| `type` | Parametri | Geometria |
|---|---|---|
| `square` | `side=1` | `[-s/2, s/2]^2` |
| `rectangle` | `width=1, height=1` | `[-w/2, w/2] x [-h/2, h/2]` |
| `regular_polygon` | `k=6, circumradius=1, rotation=None` | k-gono centrato nell'origine, lato inferiore orizzontale di default |
| `polygon` | `vertices` | poligono convesso, orientazione qualsiasi |
| `triangle` | `vertices` (tre punti) | triangolo qualsiasi |
| `right_isosceles_triangle` | `leg=1` | vertici (0,0), (L,0), (0,L) |
| `circle` | `radius=1` | disco nell'origine |
| `quadrant` | `radius=1` | `x >= 0, y >= 0, |x| <= R` |
| `semicircle` | `radius=1` | `y >= 0, |x| <= R` |

Anche i nomi brevi della CLI `right_triangle`, `pentagon`, `hexagon`, `nonagon`,
`dodecagon` sono accettati come `type`.

## Normalizzazione di Packomania

Quadrato di lato 1 centrato nell'origine (csq); rettangolo `1 x h` centrato
nell'origine (crc); cerchio di raggio 1 (cci); triangolo rettangolo con cateti 1 e
angolo retto nell'origine (crt); quadrante e semicerchio di raggio 1 (ccq, csc);
k-gono regolare con raggio circoscritto 1 (cpt, chx, cno, cdd). Sono state
verificate sui file di coordinate del sito e sui raggi per n = 1 (il raggio
inscritto).

## Contenitori personalizzati tramite spec

Da riga di comando, `--spec` accetta una stringa JSON o un file:

```bash
circlepack run --n 10 --spec '{"type": "polygon", "vertices": [[0,0],[3,0],[2,1],[0,1]]}'
circlepack run --n 8  --spec '{"type": "triangle", "vertices": [[0,0],[1,0],[0.3,0.8]]}'
circlepack run --n 12 --spec mio_contenitore.json
```

Un'esecuzione reale del primo contenitore con n = 6, 4 avvii e 5 hop ha dato
`r = 0.289528631083438`, VALID in modalità float (il controllo esatto delle spec
di poligoni lavora a partire dai vertici razionali).

## Lenti e intersezioni arbitrarie di semipiani e dischi

I costruttori predefiniti sono scorciatoie; ogni altra regione richiede la classe
generica. Un contenitore `custom` è descritto direttamente dalle sue primitive,
che è anche il modo in cui ogni file di soluzione lo memorizza
(`container.halfplanes`, `container.disks`):

```python
import numpy as np
from circlepack import Container, run_many, SearchConfig

if __name__ == "__main__":      # necessario: i worker sono avviati con "spawn"
    # lente: intersezione di due dischi unitari centrati in (-0.5, 0) e (0.5, 0)
    lens = Container(A=np.zeros((0, 2)), b=np.zeros(0),
                     C=[[-0.5, 0.0], [0.5, 0.0]], R=[1.0, 1.0], name="lens")
    res = run_many(lens, n=7, starts=4, workers=2, cfg=SearchConfig(hops=3))
    print(res.best.r)           # 0.19724606981995318 nella nostra esecuzione
```

Note: un contenitore costruito così ha `spec == {}`, quindi non è ricostruibile
tramite `--spec` della CLI; salvando una soluzione si memorizzano le primitive e
la lettura ricostruisce un contenitore `custom`. La verifica esatta di tali file
usa le primitive float memorizzate (non una `spec` razionale), e l'area (usata
per la scala della penalità) è calcolata con Monte Carlo quando sono presenti
dischi. Assicurarsi che la regione sia convessa e non vuota; regioni vuote o
illimitate sollevano `ValueError`.

## Record

Una tabella di record è associata a un contenitore solo per le normalizzazioni
elencate sopra; qualsiasi altro parametro (ad esempio un quadrato di lato 2) non
ha tabella. Le tabelle si scaricano con `circlepack records fetch` (si veda
[cli.md](cli.md#records)); non fanno parte del pacchetto.
