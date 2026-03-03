#!/bin/bash
sqlite3_debug=/config/.unmanic/plugins/kmarius_hacks/lib/sqlite3_debug.py
service=/opt/venv/lib/python3.12/site-packages/unmanic/service.py
config=/config/.unmanic/userdata/kmarius_hacks/settings.json

if [[ $(jq '.enable_sqlite3_debug' <"$config") = true ]]; then
  cp "$sqlite3_debug" "$(dirname "$service")"
  {
    echo 'from . import sqlite3_debug'
    cat "$service"
  } > "$service"_
  mv "$service"_ "$service"
else
  sed -i 's/from \. import sqlite3_debug//' "$service"
fi