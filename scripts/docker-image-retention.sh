#!/usr/bin/env bash
#
# Keep Docker disk usage bounded without touching images used by containers.
#
# Environment:
#   KEEP_PER_REPOSITORY  Number of recent tagged images to keep (default: 2).
#   BUILDER_CACHE_UNTIL Keep build cache newer than this (default: 168h).
#   DRY_RUN             Set to 1 to print removals without applying them.
set -euo pipefail

KEEP_PER_REPOSITORY="${KEEP_PER_REPOSITORY:-2}"
BUILDER_CACHE_UNTIL="${BUILDER_CACHE_UNTIL:-168h}"
DRY_RUN="${DRY_RUN:-0}"

if ! [[ "$KEEP_PER_REPOSITORY" =~ ^[1-9][0-9]*$ ]]; then
    echo "KEEP_PER_REPOSITORY must be a positive integer" >&2
    exit 2
fi

declare -A protected_image_ids=()
declare -A repository_counts=()
declare -A seen_repository_images=()
declare -a removal_candidates=()

# An image referenced by any running or stopped container is never eligible.
while IFS= read -r image_id; do
    [[ -n "$image_id" ]] && protected_image_ids["$image_id"]=1
done < <(
    docker container ls -aq |
        xargs -r docker container inspect --format '{{.Image}}'
)

# Docker lists images newest first. Count unique image IDs per repository so
# multiple tags pointing at one image consume only one retention slot.
while IFS=$'\t' read -r repository image_id; do
    [[ "$repository" == "<none>" ]] && continue

    repository_image_key="${repository}"$'\t'"${image_id}"
    [[ -n "${seen_repository_images[$repository_image_key]+set}" ]] && continue
    seen_repository_images["$repository_image_key"]=1

    count="${repository_counts[$repository]:-0}"
    if (( count < KEEP_PER_REPOSITORY )); then
        protected_image_ids["$image_id"]=1
    fi
    repository_counts["$repository"]=$((count + 1))
done < <(docker image ls --all --no-trunc --format '{{.Repository}}\t{{.ID}}')

while IFS= read -r image_id; do
    [[ -z "$image_id" ]] && continue
    if [[ -z "${protected_image_ids[$image_id]+set}" ]]; then
        removal_candidates+=("$image_id")
    fi
done < <(docker image ls -aq --no-trunc | sort -u)

if ((${#removal_candidates[@]} == 0)); then
    echo "No images exceed the retention policy."
elif [[ "$DRY_RUN" == "1" ]]; then
    printf 'Would remove image %s\n' "${removal_candidates[@]}"
else
    for image_id in "${removal_candidates[@]}"; do
        if ! docker image rm "$image_id"; then
            echo "Warning: could not remove image $image_id" >&2
        fi
    done
fi

if [[ "$DRY_RUN" == "1" ]]; then
    echo "Would prune build cache older than $BUILDER_CACHE_UNTIL."
else
    docker builder prune --force --filter "until=$BUILDER_CACHE_UNTIL"
fi
