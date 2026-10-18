#!/usr/bin/env bash
# Runs `obelize scan --sarif` for the action. Every input arrives as an environment variable and is
# checked against the shape it may have before it joins a command line; none is expanded into this
# file. The scan's exit code goes to $GITHUB_OUTPUT and this script exits 0, so the annotations and
# the upload happen before the job fails on it.
set -uo pipefail
set -f

die() {
  echo "::error::$1"
  exit 2
}

version=${OBELIZE_VERSION:-}
[[ $version =~ ^[0-9]+(\.[0-9]+)*([.-]?(a|b|rc|dev|post)[0-9]+)*$ ]] ||
  die "version takes a release such as 0.7.0, got '$version'"

args=(scan --sarif)
for pack in ${OBELIZE_PACKS:-}; do
  [[ $pack =~ ^[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9]+(-[a-z0-9]+)*$ ]] ||
    die "packs takes pack ids such as py-pdf/pypdf2-to-pypdf, got '$pack'"
  args+=(--pack "$pack")
done

library=${OBELIZE_LIBRARY:-}
if [[ -n $library ]]; then
  [[ $library =~ ^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$ ]] ||
    die "library takes a distribution name such as requests, got '$library'"
  args+=(--library "$library")
fi
for module in ${OBELIZE_MODULES:-}; do
  [[ -n $library ]] || die "modules goes with library"
  [[ $module =~ ^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$ ]] ||
    die "modules takes module names such as yaml, got '$module'"
  args+=(--module "$module")
done
if [[ -n $library && -n ${OBELIZE_PACKS:-} ]]; then
  die "library lists a library that has no pack; packs names packs"
fi

for status in ${OBELIZE_FAIL_ON:-}; do
  case $status in
    eligible | needs_review | unsupported) args+=(--fail-on "$status") ;;
    *) die "fail-on takes eligible, needs_review or unsupported, got '$status'" ;;
  esac
done

sarif=${OBELIZE_SARIF_FILE:?the action sets the file the findings go to}
cd "${OBELIZE_WORKDIR:-.}" || die "working-directory '${OBELIZE_WORKDIR:-.}' is not a directory"

uvx "obelize==$version" "${args[@]}" >"$sarif"
code=$?
echo "exit-code=$code" >>"$GITHUB_OUTPUT"
echo "sarif-file=$sarif" >>"$GITHUB_OUTPUT"
exit 0
