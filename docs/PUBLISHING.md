# Publishing notes / Note di pubblicazione

Internal document: proposals and checklist for the first public release.
Documento interno: proposte e checklist per la prima pubblicazione.

---

## English

### Proposed GitHub repository description (<= 350 characters)

> Optimizer for packing n equal circles of maximal radius in convex containers
> (square, rectangles, polygons, circle, quadrant, semicircle, ...). Soft-to-rigid
> penalty phase, basin hopping, dense SLSQP and sparse LP (HiGHS) polish, parallel
> multi-start, and an exact rational verifier. Packomania-compatible.

(about 306 characters)

### Topics

`circle-packing`, `packing`, `optimization`, `computational-geometry`,
`numerical-optimization`, `scipy`, `numpy`, `linear-programming`,
`basin-hopping`, `exact-arithmetic`, `packomania`, `python`

### Proposed first-release notes (tag `v0.1.0`)

**circlepack 0.1.0**

First public release of circlepack, a generic optimizer for packing n equal
circles of maximal radius in a fixed convex container built from half-planes and
disks, with a stand-alone verifier in exact rational arithmetic.

- Containers: square, rectangles, regular and arbitrary convex polygons,
  triangles, circle, quadrant, semicircle, custom half-plane/disk intersections,
  using Packomania normalisations.
- Search: soft-to-rigid penalty continuation, lattice-seeded starts, basin
  hopping, parallel multi-start.
- Polish: dense SLSQP with analytic Jacobians (n <= 60) and a sparse sequential-LP
  polish on HiGHS (n = 300 in about 0.5 s, 3 to 60 times faster than SLSQP).
- Verification: float and exact rational modes (`circlepack verify --exact`).
- Benchmarks: known Packomania radii reproduced for csq and cci at n = 10..30
  (21/21 each) and for most values of n in the other benchmarked containers.
  Some rectangle results exceed the published values at retrieval time; these are
  candidates pending submission to the maintainer, not claimed records.
- CLI: `run`, `verify`, `bench`, `records` (`records fetch` downloads the
  Packomania tables into a local cache; they are not bundled), `campaign`. 179 tests. MIT
  license.

Credits: inspired by Yohei Nakajima's soft-to-rigid-packing; reference radii and
conventions from Eckard Specht's Packomania.

### Proposed publication commit message

```
Prepare 0.1.0 publication: bilingual docs, changelog, package metadata

Add English and Italian README and docs (method, CLI, file format,
verification, containers, contributing), CHANGELOG for 0.1.0,
PUBLISHING notes, and complete pyproject metadata (authors, keywords,
classifiers, URLs, license-files).
```

### Checklist before publishing

- [x] **Packomania data: not redistributed (decided).** The record tables are
      no longer in the repository or the package. `circlepack records fetch`
      downloads the per-table summary pages from packomania.com on the user's
      machine (one request per table, >= 2 s apart, identifying User-Agent) into
      `$CIRCLEPACK_DATA` or the platform cache, with provenance (source URL,
      fetch time, the page's "Last update", normalisation) stored in each cached
      file. Tests do not need the network: record-dependent tests are skipped
      without the cache, the parser is tested on a synthetic page.
- [ ] **The published history must not contain the old data.** Earlier local
      commits contain `circlepack/data/records_*.txt` and the `known`/`gap`
      columns in `benchmarks/*/summary.json`. Publish a single squashed initial
      commit made from the current tree (e.g. `git checkout --orphan public &&
      git commit`), and check it: `git rev-list --count public` must be 1 and
      `git log public --oneline -- circlepack/data` must print nothing. Push only
      that branch, never the local development branches.
- [x] `<repository-url>` replaced in `circlepack/records.py` (`REPO_URL`, used in
      the User-Agent): https://github.com/Whoneon/circlepack.
- [ ] Moki & Julio data (CC-BY-4.0) is not included; keep it that way, or add
      the required attribution if anything derived is ever committed (the
      re-polished packings are deliberately not committed).
- [x] Repository URL https://github.com/Whoneon/circlepack set in `pyproject.toml`,
      `CHANGELOG.md` links and the READMEs/docs; author and copyright set to
      "Whoneon" (`pyproject.toml`, `LICENSE`). Change to a real name if desired.
- [ ] License headers: the project is MIT with a single `LICENSE`; add an SPDX
      line (`# SPDX-License-Identifier: MIT`) to source files if desired.
- [ ] Remove local paths and personal data: a grep of the tree (excluding
      `.git`) found no `/home/...` paths or e-mail addresses in tracked files;
      repeat it before release. `benchmarks/scripts/mj_compare.py` documents a
      relative path `../external/moki-julio-circle-packing` (generic, harmless).
      Git history author is "Whoneon <whoneon@users.noreply.github.com>" (a GitHub noreply address); confirm that is intended.
- [ ] History: squash (required, see the data item above).
- [ ] Run `pytest -q` twice, with an empty cache (`CIRCLEPACK_DATA=$(mktemp -d)`)
      and with a filled one; run `pip wheel .` and a clean-venv install; check
      that the wheel contains no `circlepack/data/` and no record values.
- [ ] Do not describe the rectangle results as records until accepted by the
      maintainer.
- [ ] Add CI (pytest on 3.10 to 3.13) and, if desired, a `CITATION.cff`.

---

## Italiano

### Descrizione proposta per il repository GitHub (<= 350 caratteri)

> Ottimizzatore per disporre n cerchi uguali di raggio massimo in contenitori
> convessi (quadrato, rettangoli, poligoni, cerchio, quadrante, semicerchio, ...).
> Fase a penalità soft-to-rigid, basin hopping, rifinitura SLSQP densa e LP
> sparsa (HiGHS), multi-start parallelo e verificatore razionale esatto.
> Compatibile con Packomania.

(circa 329 caratteri)

### Argomenti (topics)

Gli stessi della sezione inglese (i topic di GitHub sono in inglese):
`circle-packing`, `packing`, `optimization`, `computational-geometry`,
`numerical-optimization`, `scipy`, `numpy`, `linear-programming`,
`basin-hopping`, `exact-arithmetic`, `packomania`, `python`

### Note di rilascio proposte (tag `v0.1.0`)

**circlepack 0.1.0**

Prima versione pubblica di circlepack, un ottimizzatore generico per disporre n
cerchi uguali di raggio massimo in un contenitore convesso fisso costruito da
semipiani e dischi, con un verificatore autonomo in aritmetica razionale esatta.

- Contenitori: quadrato, rettangoli, poligoni regolari e convessi qualsiasi,
  triangoli, cerchio, quadrante, semicerchio, intersezioni personalizzate di
  semipiani e dischi, con le normalizzazioni di Packomania.
- Ricerca: continuazione della penalità da morbido a rigido, avvii da reticolo,
  basin hopping, multi-start parallelo.
- Rifinitura: SLSQP denso con Jacobiani analitici (n <= 60) e rifinitura a LP
  sequenziale sparsa su HiGHS (n = 300 in circa 0,5 s, da 3 a 60 volte più
  veloce di SLSQP).
- Verifica: modalità float e razionale esatta (`circlepack verify --exact`).
- Benchmark: raggi noti di Packomania riprodotti per csq e cci con n = 10..30
  (21/21 ciascuno) e per la maggior parte degli n negli altri contenitori
  provati. Alcuni risultati sui rettangoli superano i valori pubblicati al
  momento del prelievo; sono candidati in attesa di invio al curatore, non record
  rivendicati.
- CLI: `run`, `verify`, `bench`, `records` (`records fetch` scarica le tabelle
  di Packomania in una cache locale; non sono incluse), `campaign`. 179 test. Licenza MIT.

Riconoscimenti: ispirato a soft-to-rigid-packing di Yohei Nakajima; raggi di
riferimento e convenzioni da Packomania di Eckard Specht.

### Messaggio di commit proposto per la pubblicazione

```
Prepara la pubblicazione 0.1.0: documentazione bilingue, changelog, metadati

Aggiunge README e documentazione in inglese e italiano (metodo, CLI, formato
dei file, verifica, contenitori, contributi), CHANGELOG per la 0.1.0, note
PUBLISHING e metadati pyproject completi (autori, parole chiave, classificatori,
URL, license-files).
```

(Per coerenza con la storia del repository, che è in inglese, si consiglia di
usare il messaggio inglese.)

### Checklist prima della pubblicazione

- [x] **Dati di Packomania: non ridistribuiti (deciso).** Le tabelle dei record
      non sono più nel repository né nel pacchetto. `circlepack records fetch`
      scarica le pagine riassuntive delle tabelle da packomania.com sulla
      macchina dell'utente (una richiesta per tabella, ad almeno 2 s di distanza,
      con uno User-Agent identificativo) in `$CIRCLEPACK_DATA` o nella cache
      della piattaforma, salvando in ogni file la provenienza (URL di origine,
      data del download, "Last update" della pagina, normalizzazione). I test
      non richiedono la rete: quelli che dipendono dai record vengono saltati
      senza cache, il parser è verificato su una pagina sintetica.
- [ ] **La storia pubblicata non deve contenere i vecchi dati.** I commit locali
      precedenti contengono `circlepack/data/records_*.txt` e le colonne
      `known`/`gap` in `benchmarks/*/summary.json`. Pubblicare un unico commit
      iniziale condensato (squash) creato dall'albero attuale (ad esempio
      `git checkout --orphan public && git commit`) e controllarlo:
      `git rev-list --count public` deve dare 1 e
      `git log public --oneline -- circlepack/data` non deve stampare nulla.
      Fare push solo di quel ramo, mai dei rami di sviluppo locali.
- [x] `<repository-url>` sostituito in `circlepack/records.py` (`REPO_URL`, usato
      nello User-Agent): https://github.com/Whoneon/circlepack.
- [ ] I dati di Moki & Julio (CC-BY-4.0) non sono inclusi; mantenere così, oppure
      aggiungere l'attribuzione richiesta se mai venisse committato qualcosa di
      derivato (le disposizioni ri-rifinite non sono volutamente committate).
- [x] URL del repository https://github.com/Whoneon/circlepack impostato in
      `pyproject.toml`, nei link di `CHANGELOG.md` e in README/documentazione;
      autore e copyright impostati a "Whoneon" (`pyproject.toml`, `LICENSE`).
      Sostituire con un nome reale se lo si desidera.
- [ ] Intestazioni di licenza: il progetto è MIT con un solo `LICENSE`; aggiungere
      una riga SPDX (`# SPDX-License-Identifier: MIT`) ai sorgenti se desiderato.
- [ ] Rimuovere percorsi locali e dati personali: una ricerca nell'albero (esclusa
      `.git`) non ha trovato percorsi `/home/...` né indirizzi e-mail nei file
      tracciati; ripeterla prima del rilascio. `benchmarks/scripts/mj_compare.py`
      documenta un percorso relativo `../external/moki-julio-circle-packing`
      (generico, innocuo). Autore nella storia git: "Whoneon <whoneon@users.noreply.github.com>" (indirizzo noreply di GitHub); confermare che sia voluto.
- [ ] Storia: condensare (squash), obbligatorio (si veda la voce sui dati sopra).
- [ ] Eseguire `pytest -q` due volte, con una cache vuota
      (`CIRCLEPACK_DATA=$(mktemp -d)`) e con una cache piena; eseguire
      `pip wheel .` e un'installazione in un venv pulito; verificare che la wheel
      non contenga `circlepack/data/` né valori di record.
- [ ] Non descrivere i risultati sui rettangoli come record finché non sono
      accettati dal curatore.
- [ ] Aggiungere CI (pytest su 3.10-3.13) e, se si vuole, un `CITATION.cff`.
