| what | status | wire bytes | body bytes | encoding | median ms | p90 ms | stubs |
|---|---|---|---|---|---|---|---|
| items limit=20 full gzip=off | 200 | 40,489 | 40,489 | none | 5.5 | 6.9 | 0 |
| items limit=20 full gzip=on | 200 | 8,874 | 40,489 | gzip | 6.3 | 7.7 | 0 |
| items limit=20 lean gzip=off | 200 | 8,606 | 8,606 | none | 6.7 | 11.7 | 7 |
| items limit=20 lean gzip=on | 200 | 1,880 | 8,606 | gzip | 6.1 | 6.6 | 7 |
| items limit=200 full gzip=off | 200 | 495,940 | 495,940 | none | 18.1 | 22.9 | 0 |
| items limit=200 full gzip=on | 200 | 103,984 | 495,940 | gzip | 24.4 | 26.4 | 0 |
| items limit=200 lean gzip=off | 200 | 86,325 | 86,325 | none | 14.8 | 15.1 | 75 |
| items limit=200 lean gzip=on | 200 | 13,655 | 86,325 | gzip | 17.1 | 18.7 | 75 |
| item GET (largest output) gzip=off | 200 | 11,694 | 11,694 | none | 4.6 | 5.4 | 0 |
| item GET (largest output) gzip=on | 200 | 3,278 | 11,694 | gzip | 4.8 | 6.0 | 0 |
