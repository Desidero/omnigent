# deploy-overlay

Needs: none
Covers: 57c49ec25f2b6235

A Databricks Apps deployment keeps its own settings in one untracked YAML file
instead of hand-editing `databricks.yml`, `deploy.py` and `src/`: the
workspace host, extra `omnigent` extras for the app install (such as `kms`),
app env vars, env vars backed by a secret scope, and files for the app source.

- **Turn on:** `deploy.py --overlay deploy/databricks/deploy.local.yml`; a
  deploy without `--overlay` is unchanged.
- **Docs:** [Deployment overlay](../../deploy/databricks/README.md#deployment-overlay)
  in the deploy guide, and the quick deploy in [Databricks](../databricks.md).
- **Upstream:** not upstream yet and not proposed.

## Must hold

- A deploy without `--overlay` deploys the selected target exactly as before and removes any `overlay.generated.yml` left by an earlier deploy; an overlay with only `extras` or `files` also deploys the selected target as it is.
- With `host`, `env` or `secret_env`, the deploy binds, deploys and runs `<target>-overlay`, written to `overlay.generated.yml`: the selected target (`prod`, or `prod-no-otel` with `--no-otel`) with the overlay's host, the target's env list followed by the overlay's, one app `secret` resource with `READ` per secret-backed variable, and the base target's `root_path`.
- `extras` are added to the generated `src/pyproject.toml` beside `databricks` and `tracing`; `files` are copied into `src/` for the deploy and removed when `deploy.py` exits.
- The overlay is checked before the build starts: an unknown key fails, a variable the target already sets (such as `OMNIGENT_FEATURES`) or a secret-looking name under plain `env` is refused, and a file may not replace anything in `src/` or use a gitignored name.
- Values are never printed (the log names variables only), and `deploy/databricks/*.local.yml` and `*.generated.yml` are gitignored, so neither is committed or uploaded.
- TODO(owner): the patch says binding `<target>-overlay` to state created through the base target was not tried against a workspace; confirm an existing deployment is reused, not recreated.

## Key code

- `deploy/databricks/deploy.py`: `load_overlay`, `_parse_overlay`, `build_overlay_bundle`, `write_overlay_bundle`, `copy_overlay_files`
- `deploy/databricks/databricks.yml`: `include` (the glob that picks up the generated fragment)

## Tests

- `tests/deploy/test_databricks_deploy_overlay.py::test_a_deploy_carries_the_whole_overlay`
- `tests/deploy/test_databricks_deploy_overlay.py::test_the_overlay_target_is_the_base_target_plus_the_overlay`
- `tests/deploy/test_databricks_deploy_overlay.py::test_an_overlay_cannot_replace_what_the_bundle_sets`
- `tests/deploy/test_databricks_deploy_overlay.py::test_anything_unexpected_in_the_overlay_fails`
- `tests/deploy/test_databricks_deploy_overlay.py::test_the_fragment_is_written_logged_by_name_and_cleared`
