#!/bin/sh

(
while ! curl -s --fail localhost:8888/unmanic/plugin_api/kmarius_hacks; do
  sleep 1;
done
) & >/dev/null 2>&1