import { readFile } from "node:fs/promises";

const metadata = JSON.parse(await readFile(new URL("../namoid-challenge.json", import.meta.url), "utf8"));
if (metadata.templateMode === true) {
  console.log("Validated the uninitialized NamoID community project template.");
  process.exit(0);
}

const paths = ["README.md", "LICENSE", "index.html", "namoid-challenge.json"];
const errors = [];
for (const path of paths) {
  const content = await readFile(new URL(`../${path}`, import.meta.url), "utf8");
  if (/\[(challenge-id|Contributor Name|Project Title)\]|Add your public repository URL/.test(content)) errors.push(`${path} still contains setup placeholders`);
}
if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(metadata.challengeId)) errors.push("challengeId must use lowercase kebab-case");
if (metadata.independentSubmission !== true) errors.push("independentSubmission must remain true");
if (metadata.programUrl !== "https://challenges.namoid.in") errors.push("programUrl must identify the NamoID challenge program");
if (metadata.platformUrl !== "https://namoid.in") errors.push("platformUrl must identify the NamoID platform");
if (metadata.documentationUrl !== "https://docs.namoid.in") errors.push("documentationUrl must identify the NamoID documentation");
try {
  const repository = new URL(metadata.repositoryUrl);
  if (repository.protocol !== "https:" || repository.hostname !== "github.com" || repository.pathname.split("/").filter(Boolean).length !== 2) throw new Error();
} catch { errors.push("repositoryUrl must be a GitHub repository root URL"); }
if (errors.length) { console.error(errors.map((error) => `- ${error}`).join("\n")); process.exit(1); }
console.log(`Validated ${metadata.projectTitle} as an independent ${metadata.challengeId} community build.`);
