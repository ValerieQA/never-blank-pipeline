#!/usr/bin/env bash
# Make the publication idempotency authority outlive the runner (S3-I1, #287).
#
# The store is written inside the publishing step, intent before each
# irreversible call and marker immediately after that destination succeeds.
# On a GitHub-hosted runner that tree dies with the job, so a key published by
# one run is invisible to the next and the authority can never catch the
# partial-failure republication it exists for.
#
# This is the whole seam: one step, its own commit, nothing but the store.
#
# Why it is a separate step and not part of the existing "mark signal" commit:
# that step is guarded by `success()`, so a run where the second destination
# fails commits nothing — and the marker of the destination that DID publish
# is exactly what must survive that failure. This step runs under `always()`.
#
# It is not a second idempotency architecture and it is not the learning
# ledger. It persists the files the authority already writes, and nothing else.
set -uo pipefail

STORE="data/editorial/publication_markers"

# A rehearsal must never leave durable publication evidence. The workflow
# guards this too; the second check is here because the cost of being wrong is
# a real publication suppressed by evidence of one that never happened.
if [ "${DRY_RUN:-false}" = "true" ]; then
    echo "dry run — publication markers are not persisted"
    exit 0
fi

if [ ! -d "$STORE" ]; then
    echo "no publication marker store in this workspace — nothing to persist"
    exit 0
fi

git config user.name  "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

git add -- "$STORE"
if git diff --staged --quiet -- "$STORE"; then
    echo "no new publication markers to persist"
    exit 0
fi

echo "persisting publication markers:"
git diff --staged --name-only -- "$STORE"

git commit -q -m "publication markers: $(git diff --staged --name-only -- "$STORE" | wc -l | tr -d ' ') file(s) from run ${GITHUB_RUN_ID:-local} [skip ci]" -- "$STORE" || {
    echo "ERROR: could not commit the publication markers"
    exit 1
}

# Concurrent publishers share this branch. Rebase and retry rather than
# force-push: a lost marker is a permitted double publication.
for attempt in 1 2 3 4 5; do
    if git push; then
        echo "publication markers persisted"
        exit 0
    fi
    echo "push attempt $attempt failed — rebasing onto origin/main and retrying"
    git pull --rebase --autostash origin main || break
    sleep $(( attempt * 3 ))
done

# Loud on purpose. The publication already happened; what failed is the
# evidence that stops the NEXT run repeating it.
echo "ERROR: publication markers were committed but could not be pushed."
echo "The next run will not see them and may republish. This needs a person."
exit 1
