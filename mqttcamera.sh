#!/usr/bin/env bash
ip=`hostname -I`
#python3 -m http.server 7534 --bind ${ip} --directory /var/www &
cd /usr/local/lib/mqttcamera/
python3 mqtt-camera/mqtt-motion-video.py --system -c bronco.json
