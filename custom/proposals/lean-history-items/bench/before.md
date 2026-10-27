| what | status | wire bytes | body bytes | encoding | median ms | p90 ms | stubs |
|---|---|---|---|---|---|---|---|
| items limit=20 full gzip=off | 200 | 40,489 | 40,489 | none | 5.9 | 6.2 | 0 |
| items limit=20 full gzip=on | 200 | 40,489 | 40,489 | none | 7.9 | 9.2 | 0 |
| items limit=20 lean gzip=off | 200 | 40,489 | 40,489 | none | 6.1 | 7.9 | 0 |
| items limit=20 lean gzip=on | 200 | 40,489 | 40,489 | none | 6.2 | 8.6 | 0 |
| items limit=200 full gzip=off | 200 | 495,940 | 495,940 | none | 18.6 | 20.7 | 0 |
| items limit=200 full gzip=on | 200 | 495,940 | 495,940 | none | 18.0 | 18.6 | 0 |
| items limit=200 lean gzip=off | 200 | 495,940 | 495,940 | none | 18.4 | 21.1 | 0 |
| items limit=200 lean gzip=on | 200 | 495,940 | 495,940 | none | 21.1 | 27.0 | 0 |
| item GET (largest output) gzip=off | 404 | 52 | 52 | none | 2.3 | 4.6 | 0 |
| item GET (largest output) gzip=on | 404 | 52 | 52 | none | 3.0 | 4.4 | 0 |
