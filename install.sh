#!/bin/bash 
systemctl stop mqttcamera
mkdir -p /usr/local/lib/mqttcamera/lib
cp ~/Projects/mqtt-vision/mqtt-motion-video.py /usr/local/lib/mqttcamera
cp ~/Projects/mqtt-vision/lib/Constants.py /usr/local/lib/mqttcamera/lib
cp ~/Projects/mqtt-vision/lib/Settings.py /usr/local/lib/mqttcamera/lib
cp ~/Projects/mqtt-vision/lib/Homie_MQTT.py /usr/local/lib/mqttcamera/lib
cp ~/Projects/mqtt-vision/lib/Algo.py /usr/local/lib/mqttcamera/lib
