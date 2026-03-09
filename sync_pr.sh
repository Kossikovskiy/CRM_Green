#!/usr/bin/env bash
set -euo pipefail

# Usage: ./sync_pr.sh [branch]
# Re-syncs feature branch with origin/main and auto-resolves conflicts
# by preferring current branch content ("replace old with new").

BRANCH="${1:-$(git branch --show-current)}"

if [[ -z "${BRANCH}" ]]; then
  echo "❌ Не удалось определить текущую ветку"
  exit 1
fi

if [[ "${BRANCH}" == "main" ]]; then
  echo "❌ Запустите скрипт из feature-ветки, не из main"
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "❌ Есть незакоммиченные изменения. Сначала commit/stash."
  exit 1
fi

echo "[1/6] fetch origin"
git fetch origin main

echo "[2/6] checkout ${BRANCH}"
git checkout "${BRANCH}"

echo "[3/6] merge origin/main (пытаемся авто-merge с приоритетом текущей ветки)"
set +e
git merge -X ours origin/main -m "Sync ${BRANCH} with origin/main (prefer branch changes)"
MERGE_EXIT=$?
set -e

if [[ ${MERGE_EXIT} -ne 0 ]]; then
  echo "[4/6] найдены сложные конфликты — принудительно оставляем текущую ветку"
  git checkout --ours .
  git add -A
  git commit -m "Sync ${BRANCH} with origin/main (force keep branch versions)"
else
  echo "[4/6] merge завершён без ручных конфликтов"
fi

echo "[5/6] push ${BRANCH}"
git push -u origin "${BRANCH}"

echo "[6/6] done"
echo "✅ Ветка ${BRANCH} обновлена. Если PR был Draft — нажмите Ready for review."
