# Verifica

[English](../en/verification.md) | [README](../../README.it.md)

`circlepack/verify.py` è un unico file che usa solo la libreria standard di
Python. Può essere copiato accanto a qualsiasi file di soluzione ed eseguito come
`python verify.py soluzione.json [--tol 1e-12] [--exact] [--eps 1e-12]`, oppure
tramite `circlepack verify`. Lo stato di uscita è 0 se VALID, 1 altrimenti; i file
illeggibili sono segnalati come errori senza far terminare il programma.

## Modalità float

Per ogni coppia, `gioco = |x_i - x_j| - 2r`; per ogni semipiano,
`(b - a.x)/|a| - r`; per ogni disco, `R - |x - c| - r`. Il rapporto mostra il
gioco minimo tra coppie (con la coppia peggiore) e il gioco minimo rispetto al
contenitore; la disposizione è VALID se entrambi sono `>= -tol` (predefinito
1e-12) e `r > 0`. È un controllo numerico soggetto agli arrotondamenti in virgola
mobile (giochi di -5e-17 sono tipici per cerchi a contatto).

## Modalità esatta (`--exact`)

Ogni float del file viene convertito *esattamente* in `fractions.Fraction`. Il
raggio è ridotto a `r' = r - eps` (`eps` razionale, predefinito 1e-12). Poi,
senza alcuna radice quadrata:

- coppie: `|x_i - x_j|^2 >= (2 r')^2`
- semipiani: `b - a.x >= 0` e `(b - a.x)^2 >= r'^2 |a|^2`
- dischi: `R - r' >= 0` e `|x - c|^2 <= (R - r')^2`

**Primitive.** Per i contenitori la cui `spec` ha dati razionali (quadrato,
rettangolo, poligono, triangolo, triangolo rettangolo isoscele, cerchio,
quadrante, semicerchio) i semipiani e i dischi sono ricostruiti esattamente dalla
`spec` (ad esempio l'ipotenusa del triangolo rettangolo è esattamente
`x + y <= 1`), quindi il controllo riguarda il vero contenitore. Per le altre
spec (poligoni regolari, i cui vertici sono irrazionali) si usano le primitive
float memorizzate e l'output riporta `primitives from stored float primitives`.

## Che cosa viene dimostrato

- VALID in modalità esatta dimostra che cerchi di raggio `r - eps` con centro nei
  centri memorizzati (in virgola mobile binaria) stanno dentro il contenitore e
  non si sovrappongono. Per i contenitori razionali, "il contenitore" è quello
  esatto.
- Per i poligoni regolari dimostra la stessa affermazione per il poligono definito
  dai semipiani float memorizzati, che differisce dal poligono regolare ideale per
  un arrotondamento (circa 1e-16).

## Che cosa non viene dimostrato

- Non l'ottimalità: nulla qui afferma che un `r` maggiore sia impossibile.
- La riduzione `r - eps` fa sì che l'affermazione riguardi `r - 1e-12`, non `r`;
  ciò assorbe l'arrotondamento di `r` memorizzato.
- Il verificatore si fida dell'input: in modalità float non controlla che
  `halfplanes` e `disks` corrispondano alla `spec`, e si assume corretta
  l'implementazione di `Fraction` e `float` di Python.
- Il costo è O(n^2) operazioni razionali per le coppie; è rapido per n
  nell'ordine delle centinaia.
