#!/usr/bin/env just --justfile

default:
  just --list

wipe:
  mpremote fs rm -r :

copy:
  for file in src/captive-portal/*; do \
    mpremote fs cp "$file" :; \
  done

reset:
  mpremote reset

fresh: wipe copy reset
