import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "bundle-third-party-notices",
      generateBundle() {
        for (const name of [
          "RIVE-MIT.txt",
          "RIVE-SOURCE.md",
          "SHADCN-MIT.txt",
          "SHADCN-SOURCE.md",
        ]) {
          this.emitFile({
            type: "asset",
            fileName: "licenses/" + name,
            source: readFileSync(
              new URL("./licenses/" + name, import.meta.url),
              "utf8",
            ),
          });
        }
      },
    },
  ],
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
  server: { host: "127.0.0.1", strictPort: true },
});
