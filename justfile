#!/usr/bin/env just --justfile

default:
  just --list

stubs:
  uv pip install -r pyproject.toml --extra stubs --target typings

wipe:
  mpremote fs rm -r :

deps:
  mpremote mip install github:josverl/micropython-stubs/mip/typing_mpy.json

cross:
  rm -rf build
  mkdir -p build
  for file in src/captive-portal/*; do \
    base=$(basename "$file"); \
    if [[ "$base" == "main.py" || "$base" == "boot.py" ]]; then \
      cp "$file" build/; \
    elif [[ "$file" == *.py ]]; then \
      mpy-cross "$file" -o "build/$(basename "$file" .py).mpy"; \
    else \
      cp "$file" build/; \
    fi \
  done

copy:
  for file in build/*; do \
    mpremote fs cp "$file" :; \
  done

reset:
  mpremote reset

load: cross copy reset

fresh: wipe deps load

connect:
  mpremote connect auto
