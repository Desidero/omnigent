# deploy-features-list

Needs: none
Covers: df4aef7ae777a84d

`deploy/databricks/deploy.py --features a,b` deploys again. The list used to
go to the bundle as `--var features=a,b`, which the Databricks CLI splits on
commas, so any deploy naming more than one feature failed. It now travels as
`BUNDLE_VAR_features` in the environment of the `databricks bundle` commands.

- **Turn on:** on by default.
- **Docs:** none of its own (a fix); the variable is noted beside `--features`
  in [the Databricks Apps deploy guide](../../deploy/databricks/README.md).
- **Upstream:** not upstream yet and not proposed; upstream has the same bug.

## Must hold

- `deploy.py --features a,b` reaches the bundle whole: the list goes to `databricks bundle` as `BUNDLE_VAR_features` in the child process's environment, and never as a `--var features=...` pair.
- Every bundle command the deploy runs (`deployment bind`, `deploy`, `run`) gets the variable, through one helper.
- An empty or blank feature list is passed as a single space, so the app's env entry has a non-empty source and no feature is turned on.
- The deploy's own environment is not changed; only the child process sees the variable.

## Key code

- `deploy/databricks/deploy.py`: `_bundle_env`, `_run_bundle`, `_bundle_vars`
- `deploy/databricks/databricks.yml`: `BUNDLE_VAR_features` (the comment on the features variable)

## Tests

- `tests/deploy/test_databricks_empty_features.py::test_every_bundle_command_gets_the_features_by_environment`
- `tests/deploy/test_databricks_empty_features.py::test_feature_list_never_travels_as_a_var_pair`
- `tests/deploy/test_databricks_empty_features.py::test_bundle_env_provides_a_valid_feature_source`
