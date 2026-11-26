# mcp-registry-icons

Needs: none
Covers: ceb0003633eac94b

A service in the MCP registry file can set `icon`, an embedded SVG or PNG
(`data:image/svg+xml;base64,` or `data:image/png;base64,`, at most 16,384
characters), which the managed MCP picker shows in place of the plug. An SVG
is drawn in the muted text colour, so it follows the theme. Remote URLs and
payloads that are not an image of the named type fail registry validation.

- **Turn on:** add `icon` to a service in the `OMNIGENT_MCP_REGISTRY` file.
  Upgrade the server first, and remove the field before rolling back: a build
  without this series rejects it as an unknown key and fails startup.
- **Docs:** "Administrator configuration" in the
  [registry README](../../examples/mcp-registry/README.md#administrator-configuration);
  the picker in the [composer feature map](../../feature-map/composer.md).
- **Upstream:** not proposed upstream yet.

## Must hold

- A registry service may set `icon` to a `data:image/svg+xml;base64,` or `data:image/png;base64,` URI of at most 16,384 characters; a service without it loads as before.
- A remote URL, another media type, a payload that is not strict base64, an oversize value, or a payload that does not decode to an SVG document or a PNG fails registry validation.
- `GET /v1/mcp-registry/services` returns each service's `icon`, `null` when unset.
- The picker draws an SVG icon as a CSS mask in the muted text colour and a PNG as an image; with no icon, or a value that is not one of the two embedded forms, it shows the plug and loads nothing.
- A server without this series rejects `icon` as an unknown key, so the field is added after the upgrade and removed before a rollback.

## Key code

- `omnigent/server/mcp_registry.py`: `_require_embedded_icon`, `_ICON_MAX_LENGTH`, `McpService`
- `omnigent/server/routes/mcp_registry.py`: `create_mcp_registry_router`
- `web/src/components/McpRegistry.tsx`: `RegistryServiceIcon`, `McpRegistryPicker`
- `web/src/lib/mcpRegistry.ts`: `RegistryService`

## Tests

- `tests/server/test_mcp_registry.py::test_icon_rejects_remote_malformed_oversize_and_non_image_values`
- `tests/server/test_mcp_registry.py::test_icon_accepts_a_self_contained_svg_or_png`
- `tests/server/test_mcp_registry.py::test_catalog_returns_each_services_icon`
- `tests/server/test_mcp_registry.py::test_a_registry_file_with_an_icon_loads`
- `web/src/components/McpRegistry.test.tsx`
