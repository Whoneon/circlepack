# Contribuire

[English](../en/contributing.md) | [README](../../README.it.md)

## Ambiente di sviluppo

```bash
git clone https://github.com/Whoneon/circlepack.git circlepack && cd circlepack
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest -q                 # 164 test, circa 20 s
pytest -q -m "not slow"   # salta i test di ottimizzazione più lunghi
```

Python >= 3.10, NumPy >= 1.24, SciPy >= 1.10. I thread BLAS sono forzati a 1
all'importazione (`circlepack/__init__.py`); imposta esplicitamente
`OPENBLAS_NUM_THREADS` ecc. se vuoi davvero altro.

## Test

`tests/` copre i contenitori (raggi per n = 1 confrontati con il raggio
inscritto in forma chiusa e, se presente nella cache, con la tabella di
Packomania), la cache dei record e il suo parser, i Jacobiani analitici contro le differenze finite, la
rifinitura sparsa, il verificatore (float, esatto, file malformati), la pipeline
e gli ottimi noti. Esegui i benchmark solo quando modifichi la ricerca:
`circlepack bench` almeno su csq, cci, crt e ccq per n = 10..30, poi confronta
con `benchmarks/*/summary.json`. Ogni disposizione aggiunta a `benchmarks/` deve
superare `circlepack verify --exact`.

I test non usano mai la rete. Il parser è verificato su una pagina scritta a mano
con numeri inventati (`tests/data/packomania/csq.html`). I test che confrontano
con i raggi reali di Packomania sono marcati `@pytest.mark.records("nome", ...)`
e vengono saltati, con il comando di download nel motivo, quando la tabella non
è nella cache. Per eseguirli, riempi una cache una volta e fai puntare
`CIRCLEPACK_DATA` a essa:

```bash
CIRCLEPACK_DATA=~/.cache/circlepack/records pytest -q -rs   # oppure solo `pytest` (cache predefinita)
CIRCLEPACK_DATA=$(mktemp -d) pytest -q                      # comportamento senza dati
```

La suite deve passare in entrambe le modalità. Non committare mai valori di
record copiati da Packomania (tabelle, fixture o colonne dei benchmark); i test
usano ottimi in forma chiusa oppure la cache.

## Stile

- Annotazioni di tipo e `from __future__ import annotations`; docstring brevi che
  indicano la matematica o la convenzione.
- NumPy vettorizzato nei punti critici; nessun ciclo Python sulle coppie.
- Il verificatore (`verify.py`) deve restare basato solo sulla libreria standard.
- Mantieni esplicite le convenzioni di scala; non cambiare mai una normalizzazione
  in silenzio.

## Aggiungere un tipo di contenitore

1. In `circlepack/containers.py`, scrivi un costruttore che restituisca un
   `Container` (semipiani `A x <= b`, dischi `C`, `R`) con un dizionario `spec`
   `{"type": "<nome>", ...parametri}` che lo ricostruisca.
2. Registralo in `_FACTORIES` (e in `CONTAINER_NAMES` per un nome breve della CLI
   con parametri predefiniti). Se Packomania ha una tabella corrispondente,
   aggiungila a `PACKOMANIA`.
3. Per la verifica esatta di un contenitore razionale, aggiungi il tipo a
   `exact_primitives` in `circlepack/verify.py` (solo dati razionali; altrimenti
   si usano le primitive float memorizzate).
4. Se Packomania ha una tabella per il contenitore, aggiungi una voce `Table`
   (nome, codice, percorso della pagina, normalizzazione) in
   `circlepack/records.py` ed estendi `record_key` in `cli.py`; controlla con
   `circlepack records fetch --tables NOME` che la pagina venga analizzata e che
   n = 1 coincida con il raggio inscritto. Non committare i dati.
5. Aggiungi test in `tests/test_containers.py` e un test di verifica.

## Aggiungere un backend GPU tramite `backend.py`

Solo la fase globale sta dietro il punto di innesto:

```python
class Backend(Protocol):
    name: str
    def relax(self, container, X, r, scale, mus, r_floor=None) -> (X, r):
        """X: (B, n, 2), r: (B,) -- un intero lotto di avvii."""
```

`NumpyBackend` scorre il lotto con L-BFGS-B di SciPy. Un backend PyTorch/JAX
terrebbe tutti i `B` avvii in un unico tensore `(B, n, 2)`, valuterebbe la
penalità `E` con distanze di coppia a lotti (dense per n piccolo, cell list per n
grande) ed eseguirebbe un ottimizzatore del primo ordine a lotti (FIRE, Adam,
L-BFGS a lotti) lungo la stessa schedule di `mu`, escludendo gli avvii il cui
raggio scende sotto `r_floor`. Basin hopping, rifinitura e verifica non cambiano.

Per aggiungerne uno: implementa una classe con `name` e `relax`, aggiungila a
`_BACKENDS` in `circlepack/backend.py` (`get_backend(name, **kw)` la istanzia;
`run_start` passa gli argomenti nominali visibili in `search.py`, cioè
`floor_mu`, `ftol` e `ftol_final`, quindi accettali o ignorali), selezionala con
`SearchConfig(backend="<nome>")`, mantieni torch/jax una dipendenza *facoltativa*
(importata in modo pigro) e verifica che i raggi rifiniti concordino con il
backend NumPy su casi piccoli. Nota che `run_start` oggi chiama `relax` per ogni
avvio; per sfruttare il batching il driver deve raggruppare gli avvii, ed è il
principale lavoro di integrazione.

## Pull request

Mantieni le modifiche focalizzate, includi i test, aggiorna `CHANGELOG.md` sotto
`[Unreleased]` e non committare dati che non hai il diritto di ridistribuire.
