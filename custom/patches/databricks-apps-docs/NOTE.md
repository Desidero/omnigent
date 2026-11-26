# databricks-apps-docs

Needs: deploy-overlay, kms-uc-service-credential
Covers: e2100adc51c88e9e

Documentation only: what a Databricks App needs after the first deploy. How the
server config and the MCP registry reach the app, which config keys the Apps
entry point honours, turning on smart routing, the per-user Databricks
connection and its credential store, sharing defaults, that sessions need a
host, telemetry, and deploy practicalities. Needs `deploy-overlay` and
`kms-uc-service-credential`, whose settings it uses.

- **Turn on:** nothing to turn on.
- **Docs:** [Configuring the app](../../deploy/databricks/README.md#configuring-the-app)
  in the deploy guide.
- **Upstream:** not upstream yet and not proposed.

## Must hold

- `deploy/databricks/README.md` has a "Configuring the app" section (anchor `#configuring-the-app`) that `docs/databricks.md` links to, and its env var table lists the optional variables the section uses.
- Its examples set everything through the deployment overlay (`host`, `extras`, `env`, `secret_env`, `files`) and name `OMNIGENT_CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL`, so the text is only correct on top of `deploy-overlay` and `kms-uc-service-credential`.
- The section describes the code at the series' base: the config keys the Apps entry point honours (`admins` and `allowed_domains` are not passed through), when smart routing is on, the five `sandbox.databricks` keys and the account connection's callback path. Re-check these against the code when the base moves.
- Statements that come from one deployment's experience and cannot be checked in this repository (managed MCP URL shapes, the read-only catalog failure, the `--compute-size` resize) stay marked as not verified.

## Key code

- none (docs only)

## Tests

- none (docs only)
