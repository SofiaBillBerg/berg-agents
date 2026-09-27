#!/usr/bin/env bash

# ==============================================================================
# HOW TO USE LOCAL_ONLY TAGS:
#
# MARKDOWN / QUARTO (.md, .qmd):
# <!-- LOCAL_ONLY_START -->
# Local-only notes or documentation here.
# <!-- LOCAL_ONLY_END -->
#
# PYTHON / TOML / GITIGNORE (.py, .toml, .gitignore):
# # LOCAL_ONLY_START
# dev_mode = True
# # LOCAL_ONLY_END
#
# JAVASCRIPT / TYPESCRIPT (.js, .ts):
# // LOCAL_ONLY_START
# console.log("Local debug logs")
# // LOCAL_ONLY_END
#
# YAML (.yml):
# # LOCAL_ONLY_START
# environment: "localhost"
# # LOCAL_ONLY_END
#
# JSON (.json):
# {
#   "api_url": "https://production.com",
#   "LOCAL_ONLY_START": "",
#   "dev_key": "secret-local-token",
#   "LOCAL_ONLY_END": ""
# }
# ==============================================================================

# 1. Update .gitattributes for all target file types
EXTENSIONS=("*.md" "*.qmd" "*.py" "*.toml" ".gitignore" "*.js" "*.ts" "*.jsx" "*.tsx" "*.yml" "*.yaml" "*.json")

for ext in "${EXTENSIONS[@]}"; do
    if ! grep -q "$ext filter=strip-local" .gitattributes 2>/dev/null; then
        echo "$ext filter=strip-local" >> .gitattributes
        echo "Added filter for $ext to .gitattributes"
    fi
done
# 2. Configure Git clean filter to strip local blocks before staging
git config filter.strip-local.clean "$(cat << 'EOF'
python3 -c '
import sys, re
content = sys.stdin.read()
pattern = re.compile(r"\s*(<!-- LOCAL_ONLY_START -->|# LOCAL_ONLY_START|// LOCAL_ONLY_START|\"LOCAL_ONLY_START\").*?(<!-- LOCAL_ONLY_END -->|# LOCAL_ONLY_END|// LOCAL_ONLY_END|\"LOCAL_ONLY_END\")\s*", re.DOTALL)
sys.stdout.write(pattern.sub("\n", content))
'
EOF
)"

# 3. Configure Git smudge filter
git config filter.strip-local.smudge "cat"


echo "Git filter for 'LOCAL_ONLY' content is successfully configured."
