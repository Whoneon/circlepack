# Riferimento della riga di comando

[English](../en/cli.md) | [README](../../README.it.md)

Si invoca come `circlepack ...` (script di console) oppure `python -m circlepack ...`.
Opzioni globali: `-h/--help`, `--version`.

```
circlepack {run,verify,bench,records} ...
```

## Scelta del contenitore (`run`, `bench`)

| Opzione | Significato |
|---|---|
| `--container NOME` | uno tra `circle, dodecagon, hexagon, nonagon, pentagon, polygon, quadrant, rectangle, regular_polygon, right_triangle, semicircle, square, triangle` (predefinito `square`) |
| `--param CHIAVE=VALORE` | parametro del contenitore, ripetibile; il valore è interpretato come JSON, ad esempio `--param height=0.5`, `--param k=7` |
| `--spec JSON_O_FILE` | specifica del contenitore come stringa JSON o percorso di un file JSON; ha la precedenza su `--container`. Si veda [containers.md](containers.md) |

Una tabella di record di Packomania viene associata automaticamente a `square`,
`circle`, `right_triangle`, `quadrant`, `semicircle`, ai k-goni regolari con
k = 5..17 (`pentagon`, ..., `regular_polygon --param k=K`, raggio circoscritto
1, rotazione predefinita) e a `rectangle` con base 1 e altezza 0.1, 0.2, ...,
0.8. I contenitori da `--spec` non hanno mai un record. La tabella deve essere
stata scaricata con [`records fetch`](#records); se manca, `run` stampa una
nota e salta il confronto, mentre `bench` si ferma con un errore.

## Opzioni di ricerca (`run`, `bench`)

| Opzione | Predefinito | Significato |
|---|---|---|
| `--starts N` | 32 | avvii indipendenti |
| `--workers N` | `min(10, cpu_count - 2)` | processi worker |
| `--seed S` | 0 | primo seme (l'avvio `i` usa il seme `S + i`) |
| `--hops N` | 20 | mosse di basin hopping per avvio |
| `--patience N` | nessuno | interrompe l'hopping dopo N mosse senza miglioramento |
| `--polish-method M` | `auto` | `auto`, `SLSQP`, `trust-constr`, `sparse`, `slp` (`sparse` è un alias di `slp`); `auto` = SLSQP per n <= 60, SLP oltre |
| `--nice N` | 10 | priorità (nice) del processo e dei worker |
| `--quiet` | disattivo | sopprime l'output di avanzamento |

## `run`

Ricerca multi-start per un singolo `n`.

```
circlepack run --n N [opzioni di contenitore e ricerca] [--out FILE_O_DIR]
```

`--out`: un file `.json` oppure una directory (predefinita `results/`); il nome
del file è `<tabella o custom>_n<N>.json`. Stampa il raggio migliore e, se la
tabella dei record è nella cache, il valore noto, lo scarto e i successi. L'avanzamento va su stderr.

```
$ circlepack run --container square --n 10 --starts 8 --workers 4 --hops 10 --quiet --out results/sq10.json
circlepack 0.1.0: n = 10 in square 1, 8 starts
[total 1.5s]
best r = 0.148204322565229  (seed 3)  known 0.148204322565000  gap -2.287e-13  hits 2/8
wrote results/sq10.json  [1.5s wall]
```

Altri esempi:

```bash
circlepack run --container rectangle --param height=0.5 --n 30
circlepack run --container regular_polygon --param k=7 --n 15
circlepack run --container square --n 300 --starts 8 --polish-method auto
circlepack run --spec '{"type": "polygon", "vertices": [[0,0],[3,0],[2,1],[0,1]]}' --n 10
```

## `verify`

```
circlepack verify FILE [FILE ...] [--tol TOL] [--exact] [--eps EPS]
```

| Opzione | Predefinito | Significato |
|---|---|---|
| `--tol` | 1e-12 | tolleranza della modalità float sul gioco minimo |
| `--exact` | disattivo | esegue anche il controllo razionale esatto |
| `--eps` | 1e-12 | modalità esatta: il raggio è ridotto a `r - eps` |

Stato di uscita 0 se ogni file è VALID, 1 altrimenti. Lo stesso verificatore
funziona in modo autonomo: `python circlepack/verify.py FILE --exact`. Si veda
[verification.md](verification.md).

## `bench`

Esegue `run` per un intervallo di `n` contro la tabella dei record del
contenitore (il contenitore deve averne una e la tabella deve essere nella
cache: `circlepack records fetch --tables NOME`).

```
circlepack bench [opzioni di contenitore e ricerca] [--n INTERVALLO] [--rtol RTOL] [--out DIR]
```

| Opzione | Predefinito | Significato |
|---|---|---|
| `--n` | `10-30` | intervallo o elenco, ad esempio `10-30` oppure `5,7,12` |
| `--rtol` | 1e-9 | tolleranza relativa per un "successo" |
| `--out` | `results/bench_<tabella>` | directory di output (un JSON per n più `summary.json`) |

Stampa una tabella Markdown (`n | known best | ours | gap | hits | s/start`),
segnalando `**NEW?**` quando il raggio supera il record di più di 1e-11 in
relativo; la segnalazione è solo uno stimolo a verificare, non una rivendicazione.

## `records`

Le tabelle di Packomania **non** sono distribuite con circlepack. Vengono
scaricate su richiesta in una cache locale e lette da lì.

```
circlepack records [list]                         # tabelle supportate e stato della cache
circlepack records fetch [--tables NOMI] [...]    # scarica nella cache
circlepack records show NOME [--n INTERVALLO] [--digits]  # stampa "n raggio" (predefinito n = 1-30)
circlepack records NOME [--n INTERVALLO]          # abbreviazione di `records show NOME`
circlepack records path                           # stampa la directory della cache
```

Nomi delle tabelle (codice Packomania tra parentesi): `square` (csq), `circle`
(cci), `right_triangle` (crt), `quadrant` (ccq), `semicircle` (csc),
`rectangle_0.1` ... `rectangle_0.8` (crc_100 ... crc_800), `pentagon` (cpt),
`hexagon` (chx), `heptagon` (chp), `octagon` (coc), `nonagon` (cno),
`decagon` (cdc), `hendecagon` (chd), `dodecagon` (cdd), `tridecagon` (ctd),
`tetradecagon` (crd), `pentadecagon` (cpd), `hexadecagon` (cxd),
`heptadecagon` (ced). Sono accettati sia i nomi sia i codici.

### `records fetch`

| Opzione | Predefinito | Significato |
|---|---|---|
| `--tables NOMI` | tutte | nomi o codici separati da virgole, ripetibile (`all` = tutte le tabelle) |
| `--force` | no | riscarica anche le tabelle già nella cache |
| `--delay S` | 2.5 | secondi tra due richieste; mai meno di 2 |
| `--offline-from DIR` | - | analizza pagine salvate in precedenza in `DIR` (`<codice>.html`, `<codice>_<pagina>.html` o la struttura del sito `<codice>/<pagina>`) invece di scaricarle |
| `--save-html DIR` | - | conserva anche una copia di ogni pagina scaricata |
| `--dest DIR` | cache | scrive in `DIR` invece che nella directory della cache |
| `--timeout S` | 30 | timeout di rete per richiesta |

Viene richiesta solo la pagina riassuntiva di ogni tabella (una richiesta per
tabella, ad esempio `https://www.packomania.com/csq/csq.html`), con uno
`User-Agent` che identifica circlepack. Gli errori di rete sono segnalati
tabella per tabella (codice di uscita 1) e non interrompono le altre tabelle; le
tabelle già nella cache vengono saltate.

**Posizione della cache**: `$CIRCLEPACK_DATA` se definita; altrimenti
`$XDG_CACHE_HOME/circlepack/records` (predefinito `~/.cache/circlepack/records`)
su Linux, `~/Library/Caches/circlepack/records` su macOS e
`%LOCALAPPDATA%\circlepack\Cache\records` su Windows.

**Struttura della cache**: un file `<codice>.json` per tabella, ad esempio
`csq.json`:

```json
{"format": "circlepack-records/1", "name": "square", "code": "csq",
 "source_url": "https://www.packomania.com/csq/csq.html",
 "retrieved_from": "https://www.packomania.com/csq/csq.html",
 "fetched_at": "2026-10-16T14:17:04+00:00", "table_last_update": "10-Sep-2026",
 "normalization": "square of side 1, [-1/2, 1/2]^2", "notes": [],
 "attribution": "...", "n_min": 1, "n_max": 9996, "count": 3147,
 "proven_optimal": [1, 2, ...], "radii": {"1": "0.500000000000", ...}}
```

I raggi sono conservati come stringhe con tutte le cifre stampate sul sito (12
o 30 decimali a seconda della tabella). Normalizzazioni applicate durante
l'analisi (elencate in `notes`): per le righe duplicate dello stesso n si tiene
il raggio maggiore (crt n = 166, 294; crc_100 n = 88); le righe n = 1 di cno e
cdc sono scartate perché incoerenti con la convenzione del raggio circoscritto 1
delle altre righe. `proven_optimal` elenca gli n il cui raggio è stampato in
grassetto sul sito.

Da Python:

```python
from circlepack.records import fetch_records, load_records, known_radius, load_table_meta

fetch_records(["square"])               # come la CLI; restituisce {nome: stato}
known_radius("square", 10)              # float, oppure None se n non è nella tabella
load_records("csq")[10]                 # stringa esatta come stampata
```

Una tabella mancante solleva `RecordTableMissing` ("record table X not found;
run `circlepack records fetch --tables X`").

```
$ circlepack records show square --n 2-4 --digits
2 0.292893218813
3 0.254333095030
4 0.250000000000
```
