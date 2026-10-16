# Metodo

[English](../en/method.md) | [README](../../README.it.md)

## Il problema

Dati un contenitore convesso `K` e un intero `n`, trovare i centri `x_1..x_n` e
il massimo `r` tali che

```
massimizzare   r
soggetto a     |x_i - x_j| >= 2 r                  per i < j        (nessuna sovrapposizione)
               a_k . x_i + r <= b_k               per ogni semipiano k, |a_k| = 1
               |x_i - c_k| + r <= R_k             per ogni disco k
```

`K` è l'intersezione di semipiani `{a_k . x <= b_k}` e dischi
`{|x - c_k| <= R_k}` (le normali sono normalizzate alla costruzione). Un cerchio
di raggio `r` con centro `x` sta in `K` se e solo se soddisfa le condizioni di
parete qui sopra; per primitive convesse questo è esatto. Il contenitore non
cambia mai dimensione (convenzione di Packomania): si massimizza il raggio di
cerchi uguali in un contenitore fisso.

## Fase 1: rilassamento da morbido a rigido

Sia `s` il raggio di `n` dischi la cui area totale è uguale a quella del
contenitore. Per un peso di penalità `mu` si minimizza su `(X, r)`

```
f = -r/s + (mu/n) E(X, r) / s^2
E = sum_{i<j}  max(0, 2r - d_ij)^2
  + sum_{i,k}  max(0, a_k.x_i + r - b_k)^2
  + sum_{i,k}  max(0, |x_i - c_k| + r - R_k)^2
```

con L-BFGS-B e il gradiente analitico (`energy.py`), lungo una schedule
geometrica `mu = 0,5, 2, 8, ...` (fattore 4), ogni stadio partendo dal
precedente. Per `mu` piccolo i dischi sono morbidi e si sovrappongono di circa
`s/mu`; al crescere di `mu` si induriscono e `r` decresce verso un ottimo locale
rigido. È l'analogo per i cerchi dell'idea soft-to-rigid di Nakajima: il raggio
si "gonfia" da uno stato mobile e molto sovrapposto fino a uno stato bloccato. La
schedule termina a `mu = 1e3` quando ogni candidato è poi rifinito, altrimenti a
`1e10`.

I punti iniziali sono punti casuali uniformi (75%) oppure un reticolo quadrato o
esagonale tagliato dal contenitore, allineato a un lato casuale e con vacanze
casuali (25%; questi entrano nella schedule a `mu = 30`). I reticoli contano per i
contenitori con ottimi cristallini, ad esempio 15 = 1+2+3+4+5 cerchi nel triangolo
rettangolo isoscele.

I termini di coppia usano una lista di vicini di Verlet (raggio di taglio
`2r(1 + skin)`, costruita con un k-d tree, ricostruita solo quando un centro si è
spostato di metà skin), quindi l'energia è esatta mentre ogni valutazione costa
O(n). Le forze di coppia sono accumulate con un unico `bincount`.

## Fase 2: basin hopping

Dalla configurazione migliore si *agitano* tutti i centri (gaussiana, circa
0,35 r) oppure si *spostano* da 1 a 3 cerchi (quelli con più gioco, cioè i
rattler, o casuali) nelle cavità più grandi (trovate campionando punti candidati
e massimizzando la distanza dagli altri centri e dalle pareti). La configurazione
viene rilassata di nuovo da una morbidezza scelta log-uniformemente in
`mu in [1, 100]`, rifinita e accettata se il raggio migliora. Un hop viene
abbandonato presto quando il suo raggio di penalità scende sotto il migliore
corrente a `mu >= 100`. I metodi di rifinitura densi rifiniscono ogni hop solo
per n <= 150; la rifinitura sparsa è abbastanza economica da essere usata per
ogni candidato.

## Fase 3: rifinitura

La rifinitura risolve il problema vincolato originale fino alla precisione di
macchina. Il raggio riportato è sempre il **raggio ammissibile** dei centri
finali, `min(min_ij d_ij / 2, min_i clearance(x_i))`, quindi il risultato è
ammissibile per costruzione (a meno di arrotondamenti) e la rifinitura non
peggiora mai un risultato.

### Densa: SLSQP con Jacobiani analitici (n <= 60, predefinita)

Si massimizza `r` su `(X, r)` con SLSQP, mantenendo solo i vincoli quasi attivi:

```
coppie       (|x_i - x_j|^2 - 4 r^2) / (4 r_ref)  >= 0
semipiani     b - a.x - r                          >= 0
dischi       ((R - r)^2 - |x - c|^2) / (2 R)       >= 0
```

con Jacobiani analitici. L'insieme attivo viene aggiornato e la risoluzione
ripetuta finché è stabile. `trust-constr` (Jacobiano sparso, Hessiano sparso
esatto della lagrangiana) è disponibile ma a n = 300 non è convergito in tempi
ragionevoli e non è usato di default.

### Sparsa: LP sequenziale con HiGHS (`circlepack/slp.py`, n > 60)

Attorno al punto ammissibile corrente, in una regione di fiducia a scatola
`|dx_i|_inf <= delta`, ogni vincolo il cui gioco è alla portata di un passo di
tale ampiezza viene linearizzato. L'LP nel passo scalato `dX = delta * xi` e
`dr = delta * sigma`:

```
max   sigma
s.t.  -u_ij . (xi_i - xi_j) + 2 sigma <= (d_ij - 2 r) / delta          coppie
       a_k . xi_i + sigma             <= (b_k - a_k.x_i - r) / delta    semipiani
       v_ik . xi_i + sigma            <= (R_k - |x_i - c_k| - r) / delta  dischi
       -1 <= xi <= 1,   0 <= sigma <= sigma_max
```

ha `2n + 1` variabili e `O(n)` righe con al più 5 elementi non nulli ciascuna;
HiGHS (`scipy.optimize.linprog`, `A_ub` sparsa) lo risolve in millisecondi.

**Perché la linearizzazione è conservativa.** La distanza `|x_i - x_j|` è una
funzione convessa dei centri, quindi sta sopra il suo piano tangente:
`d(x + dx) >= d + u . dx`. Il vincolo di coppia linearizzato sottostima dunque il
gioco reale, e un passo ammissibile per l'LP è ammissibile per le coppie. I
vincoli dei semipiani sono lineari (esatti). La parete del disco `R - |x - c|` è
concava in `x`, quindi la tangente la sovrastima; si sottrae dalle righe dei
dischi il limite del secondo ordine `delta^2 / |x - c|` per ripristinare la
conservatività. Perciò il vero raggio ammissibile dopo un passo non è mai
inferiore alla previsione dell'LP. Un passo è comunque accettato solo se il
raggio ammissibile esatto aumenta.

La regione di fiducia raddoppia quando i limiti del passo hanno costi ridotti non
nulli (la scatola limita il guadagno) e si riduce di 4 quando l'ottimo dell'LP è
interno (regime tipo Newton; questo evita che le tolleranze dell'LP, relative a
`delta`, limitino le ultime cifre). L'iterazione si ferma quando l'LP non prevede
guadagno (`dr <= 1e-15 r`); tipicamente da 4 a 30 LP. SLP trova punti
stazionari del primo ordine. Una via di fuga facoltativa del secondo ordine
(`polish_slp(..., escapes=k)`) esiste ma nei nostri test non ha mai migliorato un
risultato ed è disattivata di default.

## Parallelismo e punto di innesto del backend

Gli avvii sono indipendenti e girano in un `ProcessPoolExecutor` (contesto spawn,
`os.nice(10)`, di default `min(10, cpu_count - 2)` worker, BLAS forzato a un
thread: il BLAS multithread rende circa 100 volte più lente le piccole operazioni
vettorizzate). La fase globale sta dietro `circlepack.backend.Backend`, si veda
[contributing.md](contributing.md).

## Note sulla complessità

- Valutazione della penalità: O(n) con la lista di Verlet (più la ricostruzione
  del k-d tree, O(n log n), quando lo skin si esaurisce).
- Rifinitura SLSQP densa: circa cubica nel numero di variabili (`2n + 1`); con
  n = 300 richiede da 10 a 35 s.
- Rifinitura SLP sparsa: un LP sparso con `2n + 1` variabili per iterazione,
  millisecondi ciascuno; n = 300 in circa 0,5 s.
- A n grande domina la fase globale: il profilo di un avvio con n = 300 mostra
  oltre il 90% del tempo in L-BFGS sulla penalità (circa 13k valutazioni per
  rilassamento). Un avvio con 6 hop richiede circa 30 s.
- La verifica esatta costa O(n^2) operazioni razionali sulle coppie.
