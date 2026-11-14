#!/usr/bin/env bash
# Battery of the repo's git hooks (.githooks/): every case builds a throwaway world (a bare remote,
# a clone wired to this repo's hooks, stub tools on PATH and a throwaway global git config), pushes
# or commits for real, and reads what ran. The last case runs the hook's real Postgres probe.
# Run from the repo root with bash 5 (on the Mac, Homebrew's: bash 3.2 gives false greens):
#   bash .githooks/pre-push.test.sh
set -u

HERE=$(cd "$(dirname "$0")/.." && pwd -P)
# Resolved (-P): the stubs log `pwd -P`, and on the Mac $TMPDIR sits behind the /var symlink.
SCRATCH=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/live-hooks-test.XXXXXX")" && pwd -P)
# No case reads a terminal: the stub hooks read their stdin to the end.
exec < /dev/null
trap 'rm -rf "${SCRATCH:?}"' EXIT
BASE_PATH=$PATH
ZERO=0000000000000000000000000000000000000000
passed=0
failed=0
n=0

ok() { passed=$((passed + 1)); echo "ok   - $1"; }
ko() { failed=$((failed + 1)); echo "FAIL - $1"; [ -f "$W/out" ] && sed 's/^/       | /' "$W/out"; }
check() { local name=$1; shift; if "$@"; then ok "$name"; else ko "$name"; fi; }

# The global hooks are stubs: each one records its arguments and stdin and exits with the code in
# <world>/<hook>.rc (0 when the file is missing).
write_global_stub() {
  cat > "$1" <<'EOF'
#!/usr/bin/env bash
world=$(cd "$(dirname "$0")/.." && pwd -P)
name=$(basename "$0")
printf '%s\n' "$@" > "$world/$name.args"
cat > "$world/$name.stdin"
exit "$(cat "$world/$name.rc" 2>/dev/null || echo 0)"
EOF
  chmod +x "$1"
}

# new_world [--no-global-path | --global-path <dir>]: a fresh world in $W, its clone in $W/work.
# The caller's environment carries what must not reach the suite: another session's TEST_DB_NAME,
# a settings module, pytest options, a PYTHONPATH and another project's virtualenv.
new_world() {
  n=$((n + 1))
  W="$SCRATCH/case$n"
  mkdir -p "$W/bin" "$W/global-hooks"
  local global_path="$W/global-hooks"
  case "${1:-}" in
    --no-global-path) global_path= ;;
    --global-path) global_path=$2 ;;
  esac
  {
    printf '[user]\n\tname = test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n'
    printf '[advice]\n\tdetachedHead = false\n'
    [ -n "$global_path" ] && printf '[core]\n\thooksPath = %s\n' "$global_path"
  } > "$W/gitconfig"
  export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$W/gitconfig" CALLS="$W/calls"
  export TEST_DB_NAME=test_hub_next DJANGO_SETTINGS_MODULE=config.settings PYTEST_ADDOPTS="-k nothing" \
    PYTHONPATH="$W/elsewhere" VIRTUAL_ENV="$W/other-venv"
  for h in pre-push commit-msg pre-commit applypatch-msg; do write_global_stub "$W/global-hooks/$h"; done
  # uv stub: logs `uv <args> @ <commit> <clean|dirty> <dir> | <environment>` and exits with the code
  # in tests/uv-<args, _ for spaces and slashes>.rc of its checkout. What it gets on stdin is the
  # probe's script (kept in <world>/probe.py) or nothing: never the refs of the push.
  cat > "$W/bin/uv" <<'EOF'
#!/usr/bin/env bash
world=$(dirname "$CALLS")
input=$(cat)
case "$input" in *refs/heads/*) echo "STDIN-REFS uv $*" >> "$CALLS" ;; esac
[ "$*" = "run --locked python -" ] && printf '%s\n' "$input" > "$world/probe.py"
state=clean; [ -n "$(git status --porcelain 2>/dev/null)" ] && state=dirty
echo "uv $* @ $(git rev-parse HEAD 2>/dev/null) $state $(pwd -P) | db=${TEST_DB_NAME-unset} dsm=${DJANGO_SETTINGS_MODULE-unset} addopts=${PYTEST_ADDOPTS-unset} pythonpath=${PYTHONPATH-unset} venv=${VIRTUAL_ENV-unset}" >> "$CALLS"
key=$(printf '%s' "$*" | tr ' /' '__')
exit "$(cat "tests/uv-$key.rc" 2>/dev/null || echo 0)"
EOF
  chmod +x "$W/bin/uv"
  PATH="$W/bin:$BASE_PATH"
  git init -q --bare "$W/remote.git"
  git init -q "$W/work"
  cp -R "$HERE/.githooks" "$W/work/.githooks"
  mkdir -p "$W/work/live" "$W/work/tests"
  echo "" > "$W/work/live/__init__.py"
  echo "def test_x(): pass" > "$W/work/tests/test_x.py"
  echo "# live" > "$W/work/README.md"
  git -C "$W/work" config core.hooksPath .githooks
  git -C "$W/work" remote add origin "$W/remote.git"
  git -C "$W/work" add -A
  git -C "$W/work" commit -q -m "initial"
  : > "$W/calls"
}

push() { (cd "$W/work" && git push "$@") > "$W/out" 2>&1; }
remote_tip() { git -C "$W/remote.git" rev-parse -q --verify "refs/heads/$1" || echo none; }
head_sha() { git -C "$W/work" rev-parse HEAD; }
commit_file() {
  mkdir -p "$(dirname "$W/work/$1")"
  echo "$2" > "$W/work/$1"
  git -C "$W/work" add -A
  git -C "$W/work" commit -q -m "$1=$2"
}
called() { grep -qF -- "$1" "$W/calls"; }
not_called() { ! grep -q . "$W/calls"; }
# The environment the stub saw for a step: everything after « | » on its line.
env_of() { grep -F -- "$1 @ " "$W/calls" | head -1 | sed 's/.* | //'; }
db_of() { env_of "$1" | sed -E 's/^db=([^ ]*).*/\1/'; }

SYNC="uv sync --locked"
PROBE="uv run --locked python -"
PYTEST="uv run --locked pytest -q"

echo "== pre-push: the checks of the removed test workflow"

new_world
push origin main
sha=$(head_sha)
check "first push of main (new branch) is accepted when the checks pass" test "$(remote_tip main)" = "$sha"
check "uv sync --locked runs on the pushed commit" called "$SYNC @ $sha clean"
check "the Postgres probe runs on the pushed commit" called "$PROBE @ $sha clean"
check "pytest runs on the pushed commit" called "$PYTEST @ $sha clean"
check "the order is: sync, Postgres probe, pytest" \
  test "$(sed -E 's/ @ .*//' "$W/calls" | tr '\n' ',')" = "$SYNC,$PROBE,$PYTEST,"
check "the checks run in a checkout other than the working tree" \
  bash -c "grep -q . '$W/calls' && ! grep -qF ' $W/work ' '$W/calls'"
check "pytest runs on a test database of its own, never the caller's TEST_DB_NAME" \
  bash -c "[[ '$(db_of "$PYTEST")' =~ ^test_live_prepush_[0-9a-f]{12}$ ]]"
check "the caller's settings module, pytest options, PYTHONPATH and virtualenv do not reach the checks" \
  bash -c "grep -q . '$W/calls' && ! grep -qE 'dsm=[^u]|addopts=[^u]|pythonpath=[^u]|venv=[^u]' '$W/calls'"
check "the checks never read the refs of the push from stdin" \
  bash -c "grep -qF '$PYTEST @ ' '$W/calls' && ! grep -q STDIN-REFS '$W/calls'"
check "the probe loads tests.settings and opens a connection" \
  bash -c "grep -q 'tests.settings' '$W/probe.py' && grep -q 'ensure_connection' '$W/probe.py'"
check "the global pre-push gets the same arguments" \
  test "$(cat "$W/pre-push.args" 2>/dev/null)" = "$(printf 'origin\n%s' "$W/remote.git")"
check "the global pre-push gets the same stdin" \
  test "$(cat "$W/pre-push.stdin" 2>/dev/null)" = "refs/heads/main $sha refs/heads/main $ZERO"
first_db=$(db_of "$PYTEST")

commit_file README.md "docs only"
: > "$W/calls"
push origin main
sha2=$(head_sha)
check "an update touching only docs is checked too (the workflow had no path filter)" called "$PYTEST @ $sha2 clean"
check "the global pre-push gets the update's old and new tips" \
  test "$(cat "$W/pre-push.stdin" 2>/dev/null)" = "refs/heads/main $sha2 refs/heads/main $sha"
check "the same working tree reuses its test database (a leftover is dropped, not piled up)" \
  test -n "$first_db" -a "$(db_of "$PYTEST")" = "$first_db"

git -C "$W/work" worktree add -q -b other "$W/second" main > /dev/null 2>&1
echo other > "$W/second/README.md"
git -C "$W/second" commit -q -am other
: > "$W/calls"
(cd "$W/second" && git push origin other) > "$W/out" 2>&1; rc=$?
second_db=$(db_of "$PYTEST")
check "a push from a second worktree of the same clone is checked" test "$rc" -eq 0 -a -n "$second_db"
check "a second worktree of the same clone runs on another test database" \
  test -n "$second_db" -a "$second_db" != "$first_db"

for step in "$SYNC" "$PROBE" "$PYTEST"; do
  new_world
  push origin main
  before=$(remote_tip main)
  key=$(printf '%s' "${step#uv }" | tr ' /' '__')
  # The probe exits 3 when Postgres is out of reach, 1 when it breaks for any other reason.
  red=1; [ "$step" = "$PROBE" ] && red=3
  commit_file "tests/uv-$key.rc" "$red"
  : > "$W/calls"
  push origin main; rc=$?
  check "a red «${step}» aborts the push" test "$rc" -ne 0 -a "$(remote_tip main)" = "$before"
  if [ "$step" = "$PROBE" ]; then
    check "an unreachable Postgres says so" grep -q "pre-push: Postgres is not reachable" "$W/out"
    check "an unreachable Postgres says how to start it" grep -qF "docker compose up -d" "$W/out"
    check "an unreachable Postgres stops before pytest" \
      bash -c "grep -qF '$PROBE @ ' '$W/calls' && ! grep -qF '$PYTEST' '$W/calls'"
  else
    check "the abort names «${step}»" grep -qF "pre-push: $step (" "$W/out"
    check "the abort after «${step}» says so" grep -q "failed on .*: push aborted" "$W/out"
  fi
done

# A probe that breaks for another reason (say, a broken tests/settings.py in the pushed commit) is no
# reason to start a Postgres: the abort must not send anyone to docker compose.
new_world
push origin main
before=$(remote_tip main)
commit_file "tests/uv-run_--locked_python_-.rc" 1
: > "$W/calls"
push origin main; rc=$?
check "a probe that breaks aborts the push" test "$rc" -ne 0 -a "$(remote_tip main)" = "$before"
check "a probe that breaks says the probe failed" grep -q "pre-push: the Postgres probe failed on .*: push aborted" "$W/out"
check "a probe that breaks does not blame Postgres" bash -c "! grep -qE 'not reachable|docker compose' '$W/out'"
check "a probe that breaks stops before pytest" \
  bash -c "grep -qF '$PROBE @ ' '$W/calls' && ! grep -qF '$PYTEST' '$W/calls'"

new_world
push origin main
before=$(remote_tip main)
commit_file "tests/uv-run_--locked_pytest_-q.rc" 1
echo 0 > "$W/work/tests/uv-run_--locked_pytest_-q.rc"
push origin main; rc=$?
check "a red commit is refused even if the working tree is green" test "$rc" -ne 0 -a "$(remote_tip main)" = "$before"
git -C "$W/work" checkout -q -- tests
commit_file "tests/uv-run_--locked_pytest_-q.rc" 0
echo 1 > "$W/work/tests/uv-run_--locked_pytest_-q.rc"
echo junk > "$W/work/untracked.txt"
push origin main; rc=$?
check "a green commit is pushed even if the working tree is red" test "$rc" -eq 0 -a "$(remote_tip main)" = "$(head_sha)"

new_world
push origin main
git -C "$W/work" checkout -q -b feature
commit_file README.md feature
: > "$W/calls"
push origin feature; rc=$?
fsha=$(head_sha)
check "a new non-main branch is checked (the workflow ran on every pull request)" \
  test "$rc" -eq 0 -a "$(remote_tip feature)" = "$fsha" -a -n "$(grep -F "$PYTEST @ $fsha" "$W/calls")"
: > "$W/calls"
push origin --delete feature; rc=$?
check "deleting a remote branch is accepted" test "$rc" -eq 0 -a "$(remote_tip feature)" = none
check "deleting a remote branch runs no checks" not_called
check "the global pre-push still sees the deletion" \
  test "$(cat "$W/pre-push.stdin" 2>/dev/null)" = "(delete) $ZERO refs/heads/feature $fsha"

new_world
git -C "$W/work" checkout -q -b one
commit_file README.md one
one=$(head_sha)
git -C "$W/work" checkout -q -b two main
commit_file README.md two
two=$(head_sha)
git -C "$W/work" branch -q three "$two"
push origin one two three; rc=$?
check "several branches pushed at once are all accepted" \
  test "$rc" -eq 0 -a "$(remote_tip one)" = "$one" -a "$(remote_tip two)" = "$two" -a "$(remote_tip three)" = "$two"
check "several branches pushed at once are all checked" bash -c "grep -qF '$PYTEST @ $one' '$W/calls' && grep -qF '$PYTEST @ $two' '$W/calls'"
check "a commit pushed under two names is checked once" test "$(grep -cF "$PYTEST @ $two" "$W/calls")" -eq 1
check "with several refs, no check reads the refs left for the next one from stdin" \
  bash -c "grep -qF '$PYTEST @ ' '$W/calls' && ! grep -q STDIN-REFS '$W/calls'"

new_world
echo 1 > "$W/pre-push.rc"
push origin main; rc=$?
check "a failing global pre-push aborts the push" test "$rc" -ne 0 -a "$(remote_tip main)" = none
check "a failing global pre-push stops before the checks" not_called

new_world --no-global-path
push origin main; rc=$?
check "without a global hooksPath the push works" test "$rc" -eq 0 -a "$(remote_tip main)" = "$(head_sha)"
check "without a global hooksPath the checks still run" called "$PYTEST @ $(head_sha)"

new_world --global-path "$SCRATCH/empty-global-hooks"
mkdir -p "$SCRATCH/empty-global-hooks"
push origin main; rc=$?
check "a global hooksPath without pre-push does not break the push" test "$rc" -eq 0 -a "$(remote_tip main)" = "$(head_sha)"

new_world
git -C "$W/work" config core.hooksPath "$W/work/.githooks"
printf '[core]\n\thooksPath = %s\n' "$W/work/.githooks" >> "$W/gitconfig"
perl -e 'alarm 60; exec @ARGV' bash -c 'cd "$1" && git push origin main' _ "$W/work" > "$W/out" 2>&1; rc=$?
check "a global hooksPath that is .githooks itself does not loop" test "$rc" -eq 0 -a "$(remote_tip main)" = "$(head_sha)"

new_world
mkdir -p "$W/minbin"
for tool in git bash; do ln -s "$(command -v "$tool")" "$W/minbin/$tool"; done
if PATH="$W/minbin:/usr/bin:/bin" command -v uv > /dev/null; then
  echo "skip - uv is in /usr/bin or /bin: the missing-uv case cannot hide it"
else
  PATH="$W/minbin:/usr/bin:/bin" push origin main; rc=$?
  check "without uv the push is aborted" test "$rc" -ne 0 -a "$(remote_tip main)" = none
  check "the abort says uv is missing" grep -q "pre-push: uv is missing" "$W/out"
fi

echo "== the real Postgres probe of the hook"

# The probe the stub kept from the first case of this world, run for real with the repo's own
# virtualenv against a port where no Postgres listens.
new_world
push origin main
if [ ! -x "$HERE/.venv/bin/python" ] || ! command -v uv > /dev/null 2>&1; then
  echo "skip - no .venv in $HERE (uv sync) or no uv: the real probe cannot run"
else
  (cd "$HERE" && env -u VIRTUAL_ENV -u DJANGO_SETTINGS_MODULE -u PYTHONPATH DB_HOST=127.0.0.1 DB_PORT=1 \
    PATH="$BASE_PATH" uv run --no-sync python - < "$W/probe.py") > "$W/out" 2>&1; rc=$?
  check "the stub kept the probe the hook sent" test -s "$W/probe.py"
  check "the real probe exits 3 when nothing listens on DB_HOST:DB_PORT" test -s "$W/probe.py" -a "$rc" -eq 3
  check "the real probe names the address it tried" grep -qF "127.0.0.1:1" "$W/out"
  check "the real probe fails with its message, not a traceback" \
    bash -c "test -s '$W/probe.py' && ! grep -q Traceback '$W/out'"
fi

echo "== delegates to the global hooks"

for hook in commit-msg pre-commit applypatch-msg; do
  new_world
  echo msg > "$W/msg"
  # pre-commit takes no arguments; commit-msg and applypatch-msg take the message file.
  args="$W/msg"; [ "$hook" = pre-commit ] && args=
  (cd "$W/work" && bash ".githooks/$hook" $args) > "$W/out" 2>&1; rc=$?
  check "$hook: passes when the global one passes" test "$rc" -eq 0
  check "$hook: the global one gets the same arguments" test -f "$W/$hook.args" -a "$(cat "$W/$hook.args" 2>/dev/null)" = "$args"
  echo 1 > "$W/$hook.rc"
  (cd "$W/work" && bash ".githooks/$hook" $args) > "$W/out" 2>&1; rc=$?
  check "$hook: fails when the global one fails" test "$rc" -ne 0
  new_world --no-global-path
  (cd "$W/work" && bash ".githooks/$hook" $args) > "$W/out" 2>&1; rc=$?
  check "$hook: exits 0 without a global hooksPath" test "$rc" -eq 0
done

new_world
echo 1 > "$W/commit-msg.rc"
echo x > "$W/work/x.txt"
git -C "$W/work" add x.txt
before=$(head_sha)
git -C "$W/work" commit -q -m "x" > "$W/out" 2>&1; rc=$?
check "git commit runs the global commit-msg through .githooks" test "$rc" -ne 0 -a "$(head_sha)" = "$before"
rm "$W/commit-msg.rc"
echo 1 > "$W/pre-commit.rc"
git -C "$W/work" commit -q -m "x" > "$W/out" 2>&1; rc=$?
check "git commit runs the global pre-commit through .githooks" test "$rc" -ne 0 -a "$(head_sha)" = "$before"

echo
if [ "$failed" -eq 0 ]; then echo "GREEN: $passed passed"; else echo "RED: $failed failed, $passed passed"; fi
[ "$failed" -eq 0 ]
