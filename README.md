# [Project Title]

**[Powered by NamoID](https://namoid.in)** ·
[NamoID documentation](https://docs.namoid.in) ·
[Challenge catalog](https://challenges.namoid.in)

> Built on the NamoID identity platform for the **NamoID Community Challenges** program.

This repository is a contributor-owned response to the
`[challenge-id]` problem statement. It was created from the official
[NamoID challenge template](https://github.com/namoidhq/namoid-challenge-template).

This project is an independent community build. It is not an official
NamoID product, security recommendation, or endorsement.

## NamoID integration

This project must use **NamoID Hosted Auth as the application's sign-in
system**. Hosted Auth is the application's authentication system, not a
social-login button.

Describe the application/client type, issuer/environment configuration,
callback path, application session, and complete user journey. Do not commit
credentials, authorization codes, or tokens.

## Community project metadata

- **Challenge ID:** `[challenge-id]`
- **Contributor:** [Contributor Name]
- **Live demo:** Add URL
- **Final commit:** Add the full 40-character SHA at submission time
- **Time spent:** Add estimate
- **License:** MIT

## Start here

1. Create your repository using **[Use this template](https://github.com/namoidhq/namoid-challenge-template/generate)**.
2. In the new repository, run:

```bash
npm run setup -- --challenge=[challenge-id] --name="Your Name" --title="Your Project" --repo=https://github.com/you/project
npm run check
```

Replace `[challenge-id]` with the ID shown in the selected problem statement.
Setup removes
the remaining template placeholders and records machine-readable attribution in
[`namoid-challenge.json`](./namoid-challenge.json).

3. [Create an application in the NamoID Console](https://console.namoid.in/login).
4. Configure its callback URL and integrate NamoID Hosted Auth into your POC.
5. Build, test, deploy, and submit the pinned commit.

## Run locally

```bash
npm run dev
```

Open `http://localhost:8080`. Replace the starter page with your application or
keep its branded footer and metadata when adapting it to another framework.

## What works

Describe the required paths you completed.

## Known limitations

State what remains incomplete. Stopping at the challenge timebox is expected.

## AI and external resources

List meaningful AI assistance, adapted code, tutorials, and libraries.

## NamoID attribution

Keep the factual challenge attribution in this README,
`namoid-challenge.json`, and the deployed page. You may change the surrounding
design and implementation. Attribution must not imply that NamoID authored,
audited, or endorses your solution.

## Submit to the catalog

Commit and push the exact version you want reviewed, then copy its full SHA:

```bash
git push
git rev-parse HEAD
```

Open the [Submit a community build](https://github.com/namoidhq/namoid-challenges/issues/new?template=community-build.yml)
form and paste the 40-character SHA into **Pinned commit SHA**. This identifies
one immutable version even if you continue changing the repository later. You
can request a catalog update or removal later.
