#!/bin/bash
# 가짜 볼트만 쓴다. 운영 볼트는 열지 않는다.
set -euo pipefail
root=$(cd "$(dirname "$0")" && pwd)
tool=$root/vault-copy-search-compare.sh
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export TMPDIR=${TMPDIR:-$HOME/tg}

fake=$tmp/sb
cat > "$fake" <<'EOF'
#!/bin/bash
wiki=${SB_COMPARE_WIKI:?}
shopt -s nullglob
for page in "$wiki"/*.md; do
  printf '%s\n' "$(basename "$page" .md)"
done
exit 0
EOF
chmod 755 "$fake"

write_card() {
  local wiki=$1 stem=$2
  mkdir -p "$wiki"
  printf '%s\n' "title: \"$stem title\"" > "$wiki/$stem.md"
}

inventory=$tmp/inventory.json
printf '%s\n' '[["card-a"],["card-b"]]' > "$inventory"
write_card "$tmp/op-equal/wiki" card-a
write_card "$tmp/op-equal/wiki" card-b
write_card "$tmp/cand-equal/wiki" card-a
write_card "$tmp/cand-equal/wiki" card-b
write_card "$tmp/op-short/wiki" card-a
write_card "$tmp/cand-short/wiki" card-a
write_card "$tmp/op-invalid/wiki" card-a

run_case() {
  local name=$1 expected=$2 baseline=$3 candidate=$4
  local out code
  set +e
  out=$(EXPECTED_SAMPLE=0 "$tool" --fixture "$inventory" "$baseline" "$candidate" "$fake" "$fake" 2>&1)
  code=$?
  set -e
  [[ $code == "$expected" ]] || {
    printf '%s\n' "fail $name code=$code out=$out" >&2
    exit 1
  }
  if [[ $expected == 2 && $out != *비교\ 무효* ]]; then
    printf '%s\n' "fail $name missing 비교 무효 out=$out" >&2
    exit 1
  fi
  printf '%s\n' "pass $name"
}

run_case fewer 1 "$tmp/op-equal/wiki" "$tmp/cand-short/wiki"
run_case invalid 2 "$tmp/op-invalid/wiki" "$tmp/cand-equal/wiki"
run_case equal 0 "$tmp/op-equal/wiki" "$tmp/cand-equal/wiki"
printf '%s\n' 'vault-copy-search-compare 3 passed'
