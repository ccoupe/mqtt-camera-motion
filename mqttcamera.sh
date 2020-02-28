#!/usr/bin/env bash
ip=`hostname -I`
#python3 -m http.server 7534 --bind ${ip} --directory /var/www &
/usr/local/lib/mqtt-camera/mqtt-motion-video.py --system -c /usr/local/etc/mqtt-camera/touchpi.json
