import { resolve } from "node:path";

// Build: ../../../../web/node_modules/.bin/vite build (from this folder); the bundle is committed.
export default {
  resolve: {
    alias: {
      "@omnigent/extension-sdk": resolve(
        __dirname,
        "../../../../sdks/web-extension/src/index.ts",
      ),
    },
  },
  build: {
    outDir: resolve(__dirname, "../src/desidero_goal_loop/dist"),
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, "src/main.ts"),
      name: "DesideroGoalLoop",
      formats: ["iife"],
      fileName: () => "extension.js",
    },
    rollupOptions: {
      output: {
        assetFileNames: (asset: { names: string[] }) =>
          asset.names.some((name) => name.endsWith(".css")) ? "extension.css" : "[name][extname]",
      },
    },
  },
  test: {
    environment: "jsdom",
  },
};
