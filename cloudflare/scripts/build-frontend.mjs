// Builds the existing frontend/ (unmodified) and copies the output into
// cloudflare/public, which is what wrangler serves as static assets. This
// keeps frontend/ itself untouched and usable by the original Docker/Render
// deployment at the same time.
import { execSync } from "node:child_process";
import { existsSync, rmSync, cpSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const cloudflareDir = path.resolve(here, "..");
const repoRoot = path.resolve(cloudflareDir, "..");
const frontendDir = path.join(repoRoot, "frontend");
const distDir = path.join(frontendDir, "dist");
const publicDir = path.join(cloudflareDir, "public");

console.log("[build-frontend] npm ci in frontend/ ...");
execSync("npm ci --no-fund --no-audit", { cwd: frontendDir, stdio: "inherit" });

console.log("[build-frontend] npm run build in frontend/ ...");
execSync("npm run build", { cwd: frontendDir, stdio: "inherit" });

if (!existsSync(path.join(distDir, "index.html"))) {
  throw new Error("frontend build did not produce dist/index.html");
}

if (existsSync(publicDir)) rmSync(publicDir, { recursive: true, force: true });
mkdirSync(publicDir, { recursive: true });
cpSync(distDir, publicDir, { recursive: true });

console.log(`[build-frontend] copied ${distDir} -> ${publicDir}`);
