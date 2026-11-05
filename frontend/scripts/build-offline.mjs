// Offline production build with esbuild (used where `npm ci` is impossible).
// The normal path is `npm ci && npm run build` (Vite); both emit dist/.
import { build } from "esbuild";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
mkdirSync(join(root, "dist/assets"), { recursive: true });
await build({
  entryPoints: [join(root, "src/main.tsx")], bundle: true, minify: true, sourcemap: true,
  format: "esm", target: "es2020", jsx: "automatic", outdir: join(root, "dist/assets"),
  entryNames: "main", nodePaths: (process.env.NODE_PATH || "").split(":").filter(Boolean),
  define: { "process.env.NODE_ENV": '"production"' }, logLevel: "info",
});
writeFileSync(join(root, "dist/index.html"), `<!doctype html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'" />
<title>AutoLink OTA</title><link rel="stylesheet" href="/assets/main.css" /></head>
<body><div id="root"></div><script type="module" src="/assets/main.js"></script></body></html>
`);
