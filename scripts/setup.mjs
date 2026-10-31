import { readFile, writeFile } from "node:fs/promises";

const options = Object.fromEntries(process.argv.slice(2).map((argument) => {
  const [key, ...parts] = argument.replace(/^--/, "").split("=");
  return [key, parts.join("=").trim()];
}));
const required = ["challenge", "name", "title", "repo"];
const missing = required.filter((key) => !options[key]);
if (missing.length) {
  console.error(`Missing ${missing.map((key) => `--${key}=...`).join(", ")}`);
  process.exit(1);
}
if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(options.challenge)) {
  console.error("Challenge ID must use lowercase kebab-case.");
  process.exit(1);
}
let repositoryUrl;
try {
  repositoryUrl = new URL(options.repo);
  if (repositoryUrl.protocol !== "https:" || repositoryUrl.hostname !== "github.com" || repositoryUrl.pathname.split("/").filter(Boolean).length !== 2) throw new Error();
} catch {
  console.error("Repository must be an HTTPS GitHub repository root URL.");
  process.exit(1);
}

const replacements = new Map([
  ["[challenge-id]", options.challenge],
  ["[Contributor Name]", options.name],
  ["[Project Title]", options.title],
  ["Add your public repository URL", options.repo.replace(/\/$/, "")]
]);
const files = ["README.md", "LICENSE", "index.html", "namoid-challenge.json"];
for (const path of files) {
  let content = await readFile(new URL(`../${path}`, import.meta.url), "utf8");
  for (const [from, to] of replacements) content = content.replaceAll(from, to);
  await writeFile(new URL(`../${path}`, import.meta.url), content);
}
const metadataUrl = new URL("../namoid-challenge.json", import.meta.url);
const metadata = JSON.parse(await readFile(metadataUrl, "utf8"));
metadata.templateMode = false;
await writeFile(metadataUrl, `${JSON.stringify(metadata, null, 2)}\n`);
console.log(`Initialized “${options.title}” for ${options.challenge}. Run npm run check next.`);
