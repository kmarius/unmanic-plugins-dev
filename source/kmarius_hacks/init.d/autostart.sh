#!/bin/sh
delay=${1:-0}

chmod u+s /command/s6-svscanctl

(
sleep "$delay"
while ! curl -s --fail localhost:8888/unmanic/plugin_api/kmarius_hacks; do
  sleep 1
done
) >/dev/null 2>&1 &