#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./publish_pr.sh                # current branch, base=main
#   ./publish_pr.sh feature-branch # explicit branch, base=main
#   ./publish_pr.sh feature main   # explicit branch + base
#
# What it does:
# 1) syncs branch with base using ./sync_pr.sh (keeps current branch versions on conflicts)
# 2) if GitHub CLI is available and authenticated:
#    - creates PR if missing
#    - marks PR as ready for review (if draft)
#    - prints mergeability state

BRANCH="${1:-$(git branch --show-current)}"
BASE_BRANCH="${2:-main}"

if [[ -z "${BRANCH}" ]]; then
  echo "❌ Не удалось определить текущую ветку"
  exit 1
fi

if [[ "${BRANCH}" == "${BASE_BRANCH}" ]]; then
  echo "❌ Для PR нужна feature-ветка (сейчас: ${BRANCH})"
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "❌ Есть незакоммиченные изменения. Сначала commit/stash."
  exit 1
fi

echo "[1/3] Синхронизация ветки с ${BASE_BRANCH}"
./sync_pr.sh "${BRANCH}"

if ! command -v gh >/dev/null 2>&1; then
  echo "[2/3] gh CLI не найден — PR создайте/проверьте в вебе"
  echo "✅ Ветка синхронизирована и запушена"
  exit 0
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "[2/3] gh не авторизован — PR создайте/проверьте в вебе"
  echo "✅ Ветка синхронизирована и запушена"
  exit 0
fi

echo "[2/3] Создание/обновление PR"
PR_URL="$(gh pr view "${BRANCH}" --json url -q .url 2>/dev/null || true)"
if [[ -z "${PR_URL}" ]]; then
  gh pr create --base "${BASE_BRANCH}" --head "${BRANCH}" --fill
  PR_URL="$(gh pr view "${BRANCH}" --json url -q .url)"
fi

DRAFT_STATE="$(gh pr view "${BRANCH}" --json isDraft -q .isDraft)"
if [[ "${DRAFT_STATE}" == "true" ]]; then
  gh pr ready "${BRANCH}"
fi

MERGE_STATE="$(gh pr view "${BRANCH}" --json mergeStateStatus -q .mergeStateStatus)"
echo "[3/3] Готово"
echo "PR: ${PR_URL}"
echo "mergeStateStatus: ${MERGE_STATE}"
if [[ "${MERGE_STATE}" == "DIRTY" ]]; then
  echo "⚠️ GitHub всё ещё видит конфликт. Перезапустите ./publish_pr.sh ещё раз после обновления base или проверьте правила репозитория."
fi
