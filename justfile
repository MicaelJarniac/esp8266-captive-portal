#!/usr/bin/env just --justfile

default:
  just --list

stubs:
  uv pip install -r pyproject.toml --extra stubs --target typings

wipe:
  mpremote fs rm -r :

deps:
  mpremote mip install github:josverl/micropython-stubs/mip/typing_mpy.json

copy:
  for file in src/captive-portal/*; do \
    mpremote fs cp "$file" :; \
  done

reset:
  mpremote reset

load: copy reset

fresh: wipe deps load

connect:
  mpremote connect auto
