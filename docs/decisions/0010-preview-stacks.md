# 10. Preview stacks: any branch, on seeded data, by label

## Status
Accepted.

## Context
Testing a change on a phone meant merging it to `development` first. The
local preview (`scripts/preview.sh` in the SMS site) is seeded and has the
dev sign-in, so every role can be tried, the cadet side included, but it only
runs on a laptop. What was wanted:

- Any branch of the API, the SMS site or the cadet portal, running somewhere
  a phone can reach.
- Every role: staff (the owner), SNCO, NCO, and a plain cadet on the portal.
- Not every branch at once. home has 16GB, and most branches are never
  looked at.
- No production data. A copy of prod would put children's personal data
  behind a sign-in button.

## Decision
**Label a pull request `preview`** in any of the three repos, and a stack
for its branch appears within a few minutes. Remove the label, or merge or
close the pull request, and the stack is deleted. A label is one tap in the
GitHub app and shows on the pull request which branches are up.

**A stack** (`previews/stack`, a Helm chart) is one namespace, `pv-<branch>`,
with:

- the API running `app/scripts/dev_server.py`: the same seed as the local
  preview, about 60 cadets, fake sign-in, scheduler and email off, on an
  emptyDir SQLite database. It never connects to Postgres.
- the SMS site and the cadet portal, built by each repo's `Dockerfile`: a
  production build that also offers the dev sign-in, because the build sets
  `NEXT_PUBLIC_PREVIEW_BUILD`. That flag is inlined at build time, so a
  Vercel deployment can't gain the sign-in from an env var, and the
  production API refuses the fake token anyway.
- three tailnet names: `pv-<branch>-sms`, `pv-<branch>-portal` and
  `pv-<branch>-api` (the SMS site calls the API from the browser). No Funnel:
  the sign-in buttons make anyone who reaches a stack the owner, so a stack
  is only for devices on the tailnet.

Everything runs on home (`role=interactive`, [ADR 0004](0004-workload-placement.md)).
The images are amd64-only.

**One branch, all three repos.** For each part, the stack runs that branch's
image if the repo has one, and main's otherwise. A change that spans repos on
one branch name is one stack, and a change to one repo runs against main for
the other two. Each repo's `preview-image.yml` pushes
`preview-<branch>` on every push, and `preview-main` from main.

**The resolver** (`previews/system/resolver.py`) is an Argo CD ApplicationSet
plugin generator: a small stdlib Python service that lists the labelled pull
requests on GitHub, groups them by branch and looks up each image's digest on
ghcr.io. Stacks reference images by digest, so a push rolls its stack without
anything committing a tag. The built-in pull request generator covers only
one repo, and merging three of them by branch name is not something
ApplicationSet generators can express.

**At most three stacks** (`MAX_STACKS`). Beyond that, the newest label waits
for a slot rather than displacing a stack someone is looking at.

## Consequences
- **Every push to every branch builds an image**, so a stack can start from
  any branch without a rebuild. The repos are public, so Actions minutes are
  free; the cost is ghcr.io storage. Old `preview-*` tags are not cleaned up.
- **A failure to read GitHub or ghcr.io is an error, not an empty list.** An
  empty list would make Argo CD delete every stack; an error leaves them as
  they are until the next try.
- **Without a GitHub token, labels show up in up to about 5 minutes**: the
  anonymous API allows 60 requests an hour, so the resolver caches for 4
  minutes. A `preview-resolver-github` Secret with any fine-grained token
  brings that down to about a minute.
- **The data resets** when the API pod restarts or a new build lands. That
  is the point: each stack starts from the same squadron.
- **A branch from before `preview-image.yml` existed has no image** until
  something is pushed to it (or the workflow is run on it by hand). Until
  then it runs main's.
- **The packages must be public.** The resolver looks digests up
  anonymously and the kubelet pulls without a secret, as for the other apps
  ([ADR 0009](0009-private-app-repositories.md)).
