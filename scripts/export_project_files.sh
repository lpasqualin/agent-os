#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$HOME/agent-os"
DOWNLOADS="$HOME/Downloads"
EXPORT_DIR="$HOME/agent-os-project-export"
ZIP_PATH="$HOME/agent-os-project-export.zip"

FILES=(
  "$DOWNLOADS/agent-os-roadmap-v3.md"
  "$PROJECT_ROOT/README.md"
  "$PROJECT_ROOT/constitution/v0.4.0.md"
  "$PROJECT_ROOT/capabilities/registry.yaml"
  "$PROJECT_ROOT/schema/agent.schema.yaml"
  "$PROJECT_ROOT/contracts/runtime.md"
  "$PROJECT_ROOT/contracts/governance.md"
  "$PROJECT_ROOT/contracts/memory.md"
  "$PROJECT_ROOT/contracts/observability.md"
  "$PROJECT_ROOT/contracts/lifecycle.md"
  "$PROJECT_ROOT/contracts/action-taxonomy.md"
  "$PROJECT_ROOT/identity/SOUL.md"
  "$PROJECT_ROOT/identity/USER.md"
  "$PROJECT_ROOT/specs/clawbot.agent.yaml"
)

usage() {
  echo "Usage:"
  echo "  export_project_files.sh list"
  echo "  export_project_files.sh view"
  echo "  export_project_files.sh copy"
  echo "  export_project_files.sh zip"
}

check_files() {
  local missing=0
  echo "Checking files..."
  for f in "${FILES[@]}"; do
    if [[ -f "$f" ]]; then
      echo "  OK   $f"
    else
      echo "  MISS $f"
      missing=1
    fi
  done
  if [[ $missing -ne 0 ]]; then
    echo
    echo "One or more files are missing. Fix paths, then rerun."
    exit 1
  fi
}

copy_files() {
  rm -rf "$EXPORT_DIR"
  mkdir -p "$EXPORT_DIR"

  cp "$DOWNLOADS/agent-os-roadmap-v3.md" "$EXPORT_DIR/ROADMAP.md"
  cp "$PROJECT_ROOT/README.md" "$EXPORT_DIR/README.md"
  cp "$PROJECT_ROOT/constitution/v0.4.0.md" "$EXPORT_DIR/CONSTITUTION.md"
  cp "$PROJECT_ROOT/capabilities/registry.yaml" "$EXPORT_DIR/CAPABILITY_REGISTRY.yaml"
  cp "$PROJECT_ROOT/schema/agent.schema.yaml" "$EXPORT_DIR/AGENT_SCHEMA.yaml"
  cp "$PROJECT_ROOT/contracts/runtime.md" "$EXPORT_DIR/RUNTIME_CONTRACT.md"
  cp "$PROJECT_ROOT/contracts/governance.md" "$EXPORT_DIR/GOVERNANCE_CONTRACT.md"
  cp "$PROJECT_ROOT/contracts/memory.md" "$EXPORT_DIR/MEMORY_CONTRACT.md"
  cp "$PROJECT_ROOT/contracts/observability.md" "$EXPORT_DIR/OBSERVABILITY_CONTRACT.md"
  cp "$PROJECT_ROOT/contracts/lifecycle.md" "$EXPORT_DIR/LIFECYCLE.md"
  cp "$PROJECT_ROOT/contracts/action-taxonomy.md" "$EXPORT_DIR/ACTION_TAXONOMY.md"
  cp "$PROJECT_ROOT/identity/SOUL.md" "$EXPORT_DIR/SOUL.md"
  cp "$PROJECT_ROOT/identity/USER.md" "$EXPORT_DIR/USER.md"
  cp "$PROJECT_ROOT/specs/clawbot.agent.yaml" "$EXPORT_DIR/clawbot.agent.yaml"

  echo
  echo "Copied files to: $EXPORT_DIR"
  ls -lah "$EXPORT_DIR"
}

case "${1:-}" in
  list)
    check_files
    ;;
  view)
    check_files
    for f in "${FILES[@]}"; do
      echo
      echo "============================================================"
      echo "$f"
      echo "============================================================"
      sed -n '1,200p' "$f"
    done
    ;;
  copy)
    check_files
    copy_files
    ;;
  zip)
    check_files
    copy_files
    rm -f "$ZIP_PATH"
    cd "$HOME"
    zip -r "$(basename "$ZIP_PATH")" "$(basename "$EXPORT_DIR")"
    echo
    echo "Created zip: $ZIP_PATH"
    ls -lh "$ZIP_PATH"
    ;;
  *)
    usage
    ;;
esac
