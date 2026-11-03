import { resolve } from "node:path";

// Build: web/node_modules/.bin/vite build --config <this file>; the bundle is committed.
export default {
  resolve: {
    alias: {
      "@omnigent/extension-sdk": resolve(
        __dirname,
        "../../../../../../sdks/web-extension/src/index.ts",
      ),
    },
  },
  build: {
    outDir: resolve(__dirname, "../src/omnigent_state_page_test/dist"),
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, "src/main.ts"),
      name: "OmnigentStatePageTest",
      formats: ["iife"],
      fileName: () => "extension.js",
    },
  },
};
