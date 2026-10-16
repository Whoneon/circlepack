# Formato dei file di soluzione

[English](../en/file-format.md) | [README](../../README.it.md)

Le soluzioni sono file JSON con `"format": "circlepack/1"`, scritti da
`circlepack run` / `bench` (`solution.py`) e letti da `verify`.

| Chiave | Tipo | Significato |
|---|---|---|
| `format` | stringa | sempre `circlepack/1` |
| `container.name` | stringa | nome leggibile |
| `container.spec` | oggetto | `{"type": ..., parametri}` che ricostruisce il contenitore; usato anche dal verificatore per ricostruire le primitive razionali |
| `container.halfplanes` | `[[a1, a2, b], ...]` | `a . x <= b` (normali unitarie) |
| `container.disks` | `[[cx, cy, R], ...]` | `|x - c| <= R` |
| `n` | intero | numero di cerchi (deve essere uguale a `len(centers)`) |
| `r` | float | raggio comune |
| `centers` | `[[x, y], ...]` | centri dei cerchi |
| `meta` | oggetto | provenienza in forma libera (generatore, seme, avvii, hop, tempo, tabella del record e, se la tabella era nella cache, miglior valore noto) |

I float sono scritti con precisione `repr` (17 cifre significative), quindi i file
si rileggono esattamente. Il verificatore autonomo richiede solo
`container.halfplanes`, `container.disks` (e `container.spec` per le primitive
razionali esatte), `centers`, `r` e facoltativamente `n`.

Esempio (abbreviato: un file reale ha 10 centri ed è formattato con un numero per
riga):

```json
{
 "format": "circlepack/1",
 "container": {
  "name": "square 1",
  "spec": {"type": "square", "side": 1.0},
  "halfplanes": [[1.0, 0.0, 0.5], [-1.0, 0.0, 0.5], [0.0, 1.0, 0.5], [0.0, -1.0, 0.5]],
  "disks": []
 },
 "n": 10,
 "r": 0.14820432256522864,
 "centers": [[0.35179567743477086, -0.24091158209230082],
             [0.343720034134077, 0.35179567743477125]],
 "meta": {"generator": "circlepack 0.1.0", "seed": 3, "starts": 8, "first_seed": 0,
          "hops": 10, "wall_seconds": 1.5, "record_table": "square", "known_best": 0.148204322565}
}
```

API Python: `circlepack.solution.save_solution(path, container, X, r, meta)` e
`load_solution(path) -> (container, X, r, meta)`.
