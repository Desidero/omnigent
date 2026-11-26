# tolerate-retired-preferences

Needs: none
Covers: 6b46393a60581bed

A stored shared preference of a kind this build doesn't know, such as one a
parked or newer series saved, no longer makes every read of that user's
preferences fail with a 500. Reads skip it and log the kind once; the row
stays stored for a build that knows it, and writing an unknown kind is still
refused.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/tolerate-retired-preferences`.

## Must hold

- Reading a user's shared preferences succeeds when a stored entry or conflict has a kind this build doesn't know; the read leaves those records out instead of failing.
- The skipped rows stay stored, so a build that knows the kind reads them back unchanged.
- Each unknown kind is logged once as a warning, not on every read.
- Writing a preference of an unknown kind is still refused.

## Key code

- `omnigent/stores/preference_store/sqlalchemy_store.py`: `_decode_known`, `_KNOWN_KINDS`, `_logged_unknown_kinds`

## Tests

- `tests/stores/test_preference_store.py::test_read_skips_stored_kinds_this_build_does_not_know`
