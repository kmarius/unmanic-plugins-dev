#!/bin/sh
#
# Force Unmanic to load all plugins after startup by calling a plugin API endpoint.

delay=${1:-0}

(
sleep "$delay"
while ! curl -s --fail localhost:8888/unmanic/plugin_api/kmarius_hacks; do
  sleep 1
done
) >/dev/null 2>&1 &