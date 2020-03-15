#!/usr/bin/env bash
cd /usr/local/lib/mqttcamera/
python3 shape_server --port 5566 &
python3 shape_server --port 4433 &
python3 mqtt-motion-video.py --system -c brono.json
