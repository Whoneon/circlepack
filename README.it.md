# circlepack

[English](README.md) | **Italiano**

`circlepack` dispone **n cerchi uguali di raggio massimo** in un **contenitore
convesso fisso** costruito da semipiani e dischi (quadrato, rettangoli, poligoni
regolari e convessi qualsiasi, triangoli, cerchio, quadrante, semicerchio,
lenti, ...). Combina un rilassamento a penalità "da morbido a rigido", il basin
hopping e una rifinitura locale ad alta precisione (SLSQP denso oppure una
programmazione lineare sequenziale sparsa su HiGHS), esegue molti avvii in
parallelo e include un verificatore autonomo in grado di controllare ogni
disposizione in **aritmetica razionale esatta**.

## Caratteristiche

- Qualsiasi contenitore convesso ottenuto come intersezione di semipiani e
  dischi; il raggio comune `r` viene massimizzato mentre il contenitore resta
  fisso (convenzione di Packomania).
- Fase globale: continuazione della penalità da morbido a rigido (L-BFGS-B,
  NumPy vettorizzato, liste di vicini di Verlet), avvii casuali e da reticolo.
- Basin hopping con mosse di *agitazione* e di *spostamento in una cavità*.
- Rifinitura locale che raggiunge gli ottimi noti a circa 1e-15: SLSQP denso con
  Jacobiani analitici (n piccolo) e rifinitura SLP sparsa con HiGHS (n grande;
  n = 300 in circa 0,5 s invece di circa 30 s).
- Esecuzione multi-start parallela (processi generati con spawn, a bassa
  priorità, in numero limitato).
- Verificatore autonomo, basato solo sulla libreria standard, con modalità
  razionale esatta.
- `circlepack records fetch` scarica i raggi migliori noti di Packomania (27
  tabelle) in una cache locale sulla tua macchina; `bench` li usa per il
  confronto. Le tabelle non sono distribuite con circlepack.
- Un punto di innesto `Backend` per una futura fase globale su GPU.

## Avvio rapido

```bash
git clone https://github.com/Whoneon/circlepack.git circlepack && cd circlepack
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"        # numpy, scipy (+ pytest)
pytest -q                        # 164 test, circa 20 s (quelli che usano i record vengono saltati senza cache)
circlepack records fetch --tables square   # facoltativo: scarica una tabella di record (si veda sotto)

circlepack run --container square --n 10 --starts 8 --workers 4 --hops 10 --out results/sq10.json
circlepack verify results/sq10.json --exact
```

Output reale dei due comandi (8 avvii richiedono 1,5 s su un desktop; la parte
`known ... hits` compare solo dopo aver scaricato la tabella del quadrato con
`circlepack records fetch --tables square`):

```text
circlepack 0.1.0: n = 10 in square 1, 8 starts
best r = 0.148204322565229  (seed 3)  known 0.148204322565000  gap -2.287e-13  hits 2/8
wrote results/sq10.json  [1.5s wall]

results/sq10.json
  n = 10  r = 0.14820432256522864
  min pair slack      = -5.551115e-17  (pair (2, 3))
  min container slack = 1.110223e-16
  float check (tol 1e-12): VALID
  exact check, r - 1e-12, primitives from spec (exact): VALID
```

(La tabella csq di Packomania riporta 12 decimali, quindi uno scarto dell'ordine
di 1e-13 è un arrotondamento, non un miglioramento.) `python -m circlepack ...`
equivale allo script `circlepack`. Da Python:

```python
from circlepack import make_container, run_many, SearchConfig

if __name__ == "__main__":   # necessario con workers > 1 (metodo di avvio spawn)
    res = run_many(make_container("quadrant"), n=12, starts=16, workers=4, cfg=SearchConfig(hops=20))
    print(res.best.r, res.best.X)
```

Riferimento completo della CLI: [docs/it/cli.md](docs/it/cli.md).

### Campagne lunghe

`circlepack campaign {run,status,report,plan}` esegue una ricerca riprendibile e
adattiva al carico su molti bersagli `(tabella Packomania, n)`, con stato in
SQLite, file dei migliori scritti in modo atomico, verifica esatta e confronto
con Packomania (dalla cache dei record) e, opzionalmente, Moki & Julio;
`scripts/run_campaign.sh start|status|stop` la avvia in background impedendo la
sospensione. Vedi [campaigns/README.md](campaigns/README.md) (in inglese).

## Tabelle dei record (scaricate, non incluse)

I raggi migliori noti sono raccolti da E. Specht su
[Packomania](https://www.packomania.com/). circlepack **non** li distribuisce:
le funzioni di confronto (`known` in `run`, `bench`, `records show`) leggono una
cache locale che si riempie una volta sola:

```bash
circlepack records fetch                       # tutte le 27 tabelle supportate, almeno 2 s tra le richieste
circlepack records fetch --tables square,circle
circlepack records list                        # stato della cache, intervallo di n, "Last update" di ogni tabella
circlepack records show square --n 1-10 --digits
```

La cache si trova in `$CIRCLEPACK_DATA` se definita, altrimenti nella directory
di cache della piattaforma (`~/.cache/circlepack/records` su Linux,
`~/Library/Caches/circlepack/records` su macOS,
`%LOCALAPPDATA%\circlepack\Cache\records` su Windows). Ogni tabella è un file
JSON con i raggi così come sono stampati sul sito e la loro provenienza (URL di
origine, data e ora del download, data "Last update" della pagina,
normalizzazione, eventuali righe scartate). Tutto il resto (`run`, `verify`,
l'API Python) funziona senza cache; senza tabella `run` omette semplicemente il
confronto. Dettagli: [docs/it/cli.md](docs/it/cli.md#records).

## Contenitori supportati

Le scale seguono Packomania, quindi i risultati sono confrontabili direttamente
con le sue tabelle.

| Nome CLI | Geometria (normalizzazione Packomania) | Tabella |
|---|---|---|
| `square` | lato 1, centrato nell'origine: `[-1/2, 1/2]^2` | csq |
| `rectangle` (`--param height=h`) | `1 x h`, centrato nell'origine | crc_XXX (`1 x 0.XXX`) |
| `circle` | raggio 1, centro nell'origine | cci |
| `right_triangle` | cateti 1, vertici (0,0), (1,0), (0,1) | crt |
| `quadrant` | quadrante circolare di raggio 1: `x >= 0, y >= 0, |x| <= 1` | ccq |
| `semicircle` | semicerchio di raggio 1: `y >= 0, |x| <= 1` | csc |
| `pentagon`, `hexagon`, `nonagon`, `dodecagon`, `regular_polygon` (`--param k=K`) | k-gono regolare, raggio circoscritto 1, lato inferiore orizzontale | cpt, chx, chp, coc, cno, cdc, chd, cdd, ctd, crd, cpd, cxd, ced (k = 5..17) |
| `triangle`, `polygon` (tramite `--spec`) | vertici qualsiasi (convessi) | - |

Contenitori personalizzati: [docs/it/containers.md](docs/it/containers.md).

## Come funziona

Ogni avvio ha tre fasi: (1) un **rilassamento da morbido a rigido**, che
minimizza un obiettivo penalizzato su centri e raggio mentre il peso della
penalità cresce geometricamente, così il raggio "si gonfia" da uno stato mobile
e sovrapposto fino a uno stato bloccato; (2) il **basin hopping** a partire dalla
configurazione migliore; (3) una **rifinitura** che risolve il problema fino alla
precisione di macchina come ottimizzazione vincolata, con SLSQP (n <= 60) oppure
programmazione lineare sequenziale sparsa (n più grandi). Il raggio riportato è
sempre il raggio ammissibile dei centri finali, quindi il risultato è ammissibile
per costruzione. Dettagli: [docs/it/method.md](docs/it/method.md).

## Verifica esatta

`circlepack/verify.py` usa solo la libreria standard e può essere copiato accanto
a un file di soluzione. In modalità `--exact` ogni float viene convertito
esattamente in razionale, il raggio è ridotto a `r - 1e-12` e tutti i vincoli di
coppia, parete e disco sono controllati senza radici quadrate. VALID è una
dimostrazione che cerchi di quel raggio nei centri memorizzati formano una
disposizione ammissibile; **non** è una dimostrazione di ottimalità. Si veda
[docs/it/verification.md](docs/it/verification.md).

## Benchmark

Tutto ciò che segue è riproducibile con `circlepack bench` e con gli script in
`benchmarks/scripts/`; ogni disposizione salvata in `benchmarks/*/` supera
`verify --exact`. I file salvati contengono solo i nostri risultati;
`benchmarks/scripts/compare_records.py` li affianca ai raggi noti presi dalla
cache locale. "Successo" significa che un avvio ha raggiunto il raggio di
Packomania entro uno scarto relativo di 1e-9. Hardware: un desktop, 10 processi
worker con `nice 10`.

| Contenitore (tabella) | n | Avvii x hop | n raggiunti | Avvii con successo |
|---|---|---|---:|---:|
| quadrato (csq) | 10..30 | 40 x 20 | 21/21 | 511/840 (61%) |
| cerchio (cci) | 10..30 | 40 x 20 | 21/21 | 667/840 (79%) |
| triangolo rettangolo (crt) | 10..30 | 24 x 20 | 16/21 | 103/504 (20%) |
| quadrante (ccq) | 10..30 | 24 x 20 | 19/21 | 263/504 (52%) |
| rettangolo 1x0,3 (crc_300) | 10..40 | 16 x 15 | 27/31 | 45% |
| rettangolo 1x0,6 (crc_600) | 10..40 | 16 x 15 | 28/31 | 46% |
| 9-gono (cno) | 10..30 | 16 x 15 | 19/21 | 65% |
| 12-gono (cdd) | 10..30 | 16 x 15 | 19/21 | 64% |
| semicerchio (csc) | 10..30 | 16 x 15 | 19/21 | 53% |

I fallimenti riguardano per lo più ottimi cristallini (ad esempio 15 cerchi nel
triangolo rettangolo) che gli avvii casuali trovano raramente; gli avvii da
reticolo ne recuperano alcuni.

**Rifinitura sparsa contro densa** (`benchmarks/scripts/polish_compare.py`, stessi
output della fase globale, processo singolo): la rifinitura SLP sparsa è da 3 a
60 volte più veloce di SLSQP per n = 100..300 (ad esempio quadrato n = 300:
0,54 s contro 33,9 s). Su 12 casi grandi, 7 finiscono nello stesso ottimo (a
circa 1e-14) e gli altri in uno vicino (|diff| <= 5e-6, di segno qualsiasi). Su
60 casi più piccoli (n = 10..60) SLP ha eguagliato SLSQP a 1e-12 in 53, è stato
migliore in 7 e mai peggiore.

**n grande** (8 avvii x 6 hop): lo scarto relativo dal raggio di Packomania va da
5,4e-5 (cerchio n = 100) a 3,6e-3 (quadrato e cerchio n = 200); un avvio con
n = 300 richiede circa 30 s. Il divario residuo dello 0,1-1% a n grande dipende
dalla fase globale, non dalla rifinitura.

**Oltre le tabelle pubblicate.** Nei benchmark sui rettangoli alcuni raggi
superano i valori di Packomania al momento del prelievo (crc_300 n = 22, 29;
crc_600 n = 26, rispettivamente di +1,1e-4, +6,9e-5, +3,4e-4 in relativo,
verificati esattamente con `r - 1e-13`), e la nuova rifinitura di un insieme di
disposizioni di terzi ne ha migliorate 12 su 1.551 di una quantità relativa da
1e-10 a 2e-7. Sono **solo candidati**: non sono stati inviati e non sappiamo se
ci siano altre segnalazioni in attesa presso il curatore dei record. Non
rivendichiamo alcun nuovo record finché non saranno inviati e accettati.

**Controllo incrociato.** Disposizioni del data set di Moki & Julio (CC-BY-4.0,
non incluso) sono state convertite e verificate con il nostro verificatore;
`benchmarks/scripts/mj_compare.py` legge un clone locale per il confronto.

## Limiti

- Ricerca euristica: i risultati non sono dimostrazioni di ottimalità. Il
  verificatore esatto dimostra solo l'ammissibilità della disposizione salvata.
- I tassi di successo calano per gli n "irregolari" (ad esempio cerchi in un
  cerchio, n >= 25) e per n >= 100 un avvio finisce dallo 0,1 all'1% sotto i
  record; non è implementata una strategia dedicata per n grande.
- La rifinitura SLP trova punti stazionari del primo ordine (la via di fuga del
  secondo ordine è facoltativa e disattivata di default).
- La verifica esatta dei poligoni regolari usa le primitive float memorizzate
  (vertici irrazionali): dimostra una disposizione nel poligono definito da quei
  float.
- Solo contenitori convessi; il backend GPU non è ancora implementato.

## Citazione e riconoscimenti

- L'idea soft-to-rigid e lo stile del verificatore minimale e autonomo si
  ispirano a [soft-to-rigid-packing](https://github.com/yoheinakajima/soft-to-rigid-packing)
  di Yohei Nakajima.
- Dati dei record e convenzioni di normalizzazione: Eckard Specht,
  [Packomania](https://www.packomania.com/). I raggi sono opera dei rispettivi
  scopritori, come raccolti da E. Specht. circlepack non li ridistribuisce:
  `circlepack records fetch` li scarica sulla macchina dell'utente, solo per
  confronto, e salva la provenienza accanto a ogni tabella.
- Moki & Julio
  ([repository](https://github.com/Hashirama1337s/moki-julio-circle-packing))
  hanno pubblicato disposizioni con certificati; ne abbiamo usate alcune per un
  controllo incrociato indipendente.
- Parti del codice e della documentazione sono state scritte con Claude
  (Anthropic).

Se usi questo software, cita il repository (versione 0.1.0) e Packomania per i
raggi di riferimento.

## Licenza

MIT, si veda [LICENSE](LICENSE). Si vedano anche [CHANGELOG.md](CHANGELOG.md) e
la documentazione in [docs/it](docs/it) ([docs/en](docs/en) in inglese).
