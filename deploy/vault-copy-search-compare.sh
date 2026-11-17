#!/bin/bash
# Read-only search compare. Default mode reflink-copies operating roots, then searches the copy.
# It does not relink, restart, or write the operating vault.
# --fixture compares two given vaults and does not read the operating vault.
set -euo pipefail

inventory=${INVENTORY:-$HOME/.dori/knowledge-inventory/search-check-1101.json}
copy_parent=${VAULT_COPY_PARENT:-$HOME/tg}
work_parent=${SEARCH_WORK_PARENT:-$HOME/tg}
tmpdir_default=${TMPDIR:-$HOME/tg}
operating_vault=${OPERATING_VAULT:-/home/jm/.local/share/second-brain/vault}
operating_generations=${OPERATING_VAULT_GENERATIONS:-/home/jm/.local/share/second-brain/vault-generations}
operating_sources=${OPERATING_SOURCES:-/home/jm/.local/share/second-brain-sources}
operating_share=${OPERATING_SHARE:-/home/jm/.local/share/second-brain}
operating_requests=${OPERATING_REQUESTS:-/home/jm/.local/state/second-brain/requests}
operating_exports=${OPERATING_EXPORTS:-/home/jm/.local/state/second-brain/exports}
operating_state=${OPERATING_STATE:-/home/jm/.local/state/second-brain}
operating_hermes=${OPERATING_HERMES:-/home/jm/.hermes}
expected_sample=${EXPECTED_SAMPLE:-129}

compare_vaults() {
  local inventory_path=$1 baseline_wiki=$2 candidate_wiki=$3 baseline_sb=$4 candidate_sb=$5 config_path=${6:-}
  INVENTORY_PATH=$inventory_path \
  BASELINE_WIKI=$baseline_wiki \
  CANDIDATE_WIKI=$candidate_wiki \
  BASELINE_SB=$baseline_sb \
  CANDIDATE_SB=$candidate_sb \
  COMPARE_CONFIG=$config_path \
  COMPARE_TMPDIR=$tmpdir_default \
  EXPECTED_SAMPLE=$expected_sample \
  python3 - <<'PY'
import os, re, subprocess, sys
from pathlib import Path

inventory = Path(os.environ["INVENTORY_PATH"])
baseline_wiki = Path(os.environ["BASELINE_WIKI"])
candidate_wiki = Path(os.environ["CANDIDATE_WIKI"])
baseline_sb = os.environ["BASELINE_SB"]
candidate_sb = os.environ["CANDIDATE_SB"]
config = os.environ.get("COMPARE_CONFIG") or ""
expected = int(os.environ.get("EXPECTED_SAMPLE") or "0")
rows = __import__("json").loads(inventory.read_text(encoding="utf-8"))
if not rows or any(not row or not isinstance(row[0], str) for row in rows):
    print("비교 무효", file=sys.stderr)
    raise SystemExit(2)
if expected and len(rows) != expected:
    print("비교 무효", file=sys.stderr)
    raise SystemExit(2)
stems = [row[0] for row in rows]

def title_of(wiki, stem):
    page = wiki / f"{stem}.md"
    if not page.is_file():
        return None
    for line in page.read_text(encoding="utf-8").splitlines():
        match = re.match(r'^title:\s*"?(.+?)"?\s*$', line) or re.match(r"^#\s+(.+)$", line)
        if match:
            return match.group(1)
    return None

def hits_for(sb, wiki):
    env = {**os.environ, "SB_COMPARE_WIKI": str(wiki), "TMPDIR": os.environ.get("COMPARE_TMPDIR", "")}
    if config:
        env["SB_CONFIG"] = config
    found = []
    for stem in stems:
        title = title_of(wiki, stem)
        if not title:
            continue
        query = re.sub(r"[^\w가-힣 .-]", " ", title)[:80]
        completed = subprocess.run([sb, "search", query], capture_output=True, text=True, timeout=180, env=env)
        if completed.returncode == 0 and stem in completed.stdout:
            found.append(stem)
    return found

base_found = hits_for(baseline_sb, baseline_wiki)
if len(base_found) != len(stems):
    print(f"비교 무효 운영 {len(base_found)}/{len(stems)}", file=sys.stderr)
    raise SystemExit(2)
cand_found = hits_for(candidate_sb, candidate_wiki)
lost = sorted(set(base_found) - set(cand_found))
print(f"운영 {len(base_found)}/{len(stems)}, 후보 {len(cand_found)}/{len(stems)}, 후보에서만 빠진 {len(lost)}")
if lost:
    print("lost_stems=" + ",".join(lost))
if len(cand_found) < len(base_found) or lost:
    raise SystemExit(1)
PY
}

if [[ ${1:-} == --fixture ]]; then
  compare_vaults "${2:?inventory}" "${3:?baseline wiki}" "${4:?candidate wiki}" "${5:?baseline sb}" "${6:?candidate sb}"
  exit 0
fi

repo=${1:?repo}
candidate=${2:?candidate}
baseline=${3:?baseline}
operating_config=${SB_OPERATING_CONFIG:-$HOME/.config/second-brain/config.toml}
stamp=$(date +%Y%m%dT%H%M%S%N)
dest=${VAULT_COPY_ROOT:-$copy_parent/sb-vc-$stamp}
work=${SEARCH_WORK_ROOT:-$work_parent/sb-search-wt-$stamp}

case $dest in
  "$HOME/.local/share/second-brain"*|"$HOME/.local/state/second-brain"*|"$HOME/.hermes"*)
    printf '%s\n' 'blocked: copy destination is an operating root' >&2
    exit 2
    ;;
esac
[[ -d $repo/.git || -f $repo/.git ]] || { printf '%s\n' 'blocked: repo is not a git checkout' >&2; exit 2; }
[[ -f $inventory && -f $operating_config ]] || { printf '%s\n' 'blocked: inventory or operating config missing' >&2; exit 2; }

mkdir -p "$dest" "$work"
chmod 700 "$dest" "$work"

copy_root() {
  local old=$1 new=$2
  [[ -e $old ]] || { printf '%s\n' "blocked: operating root missing: $old" >&2; exit 2; }
  [[ ! -e $new ]] || { printf '%s\n' "blocked: copy target already exists: $new" >&2; exit 2; }
  mkdir -p "$(dirname "$new")"
  cp -a --reflink=always "$old" "$new"
}

copy_root "$operating_generations" "$dest/gen"
vault_real=$(readlink -f "$operating_vault")
[[ -d $vault_real ]] || { printf '%s\n' 'blocked: operating vault generation missing' >&2; exit 2; }
cp -a --reflink=auto "$vault_real" "$dest/vault"
[[ ! -L $dest/vault && -d $dest/vault/wiki ]] || { printf '%s\n' '비교 무효' >&2; exit 2; }
copy_root "$operating_sources" "$dest/sources"
copy_root "$operating_share" "$dest/share"
copy_root "$operating_requests" "$dest/req"
copy_root "$operating_exports" "$dest/exp"
mkdir -p "$dest/bak"
copy_root "$operating_state" "$dest/state"
chmod -R u+w "$dest/state/backups"
rm -rf "$dest/state/backups"
wiki_pages=$(find "$dest/vault/wiki" -name '*.md' | wc -l)
[[ $wiki_pages -ge $expected_sample ]] || { printf '%s\n' "비교 무효 vault/wiki=$wiki_pages" >&2; exit 2; }
copy_root "$operating_hermes" "$dest/hermes"

python3 - "$operating_config" "$dest/config.toml" "$dest" \
  "$operating_generations" "$operating_vault" "$operating_sources" "$operating_share" \
  "$operating_requests" "$operating_exports" "$operating_state" "$operating_hermes" <<'PY'
import sys
from pathlib import Path

source_config, out_path, dest_root, generations, vault, sources, share, requests, exports, state, hermes = sys.argv[1:]
dest = Path(dest_root)
text = Path(source_config).read_text(encoding="utf-8")
replacements = [
    (generations, str(dest / "gen")),
    (vault, str(dest / "vault")),
    (sources, str(dest / "sources")),
    (share, str(dest / "share")),
    (requests, str(dest / "req")),
    (exports, str(dest / "exp")),
    (str(Path(state) / "backups"), str(dest / "bak")),
    (state, str(dest / "state")),
    (hermes, str(dest / "hermes")),
]
for old, new in replacements:
    if old not in text:
        raise SystemExit(f"blocked: config root missing: {old}")
    text = text.replace(old, new)
for old, _new in replacements:
    if old in text:
        raise SystemExit(f"blocked: operating root remains in copy config: {old}")
out = Path(out_path)
out.write_text(text, encoding="utf-8")
out.chmod(0o600)
PY

sync_sha() {
  local sha=$1
  local wt=$work/$sha
  git -C "$repo" worktree add --detach "$wt" "$sha"
  (
    cd "$wt"
    PATH="${SB_TOOL_PATH:-$HOME/.local/bin}:$PATH" uv sync --python 3.12
  )
  [[ -x $wt/.venv/bin/sb ]] || { printf '%s\n' "blocked: $sha has no sb" >&2; return 2; }
}

sync_sha "$baseline"
sync_sha "$candidate"
compare_vaults "$inventory" "$dest/vault/wiki" "$dest/vault/wiki" "$work/$baseline/.venv/bin/sb" "$work/$candidate/.venv/bin/sb" "$dest/config.toml"
printf '%s\n' "vault_copy=$dest"
