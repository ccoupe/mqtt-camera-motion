#!/bin/bash 
systemctl stop mqttcamera
mkdir -p /usr/local/lib/mqttcamera/lib
cp /home/pi/Projects/iot/camera/mqtt-motion-video.py /usr/local/lib/mqttcamera
cp /home/pi/Projects/iot/camera/lib/Constants.py /usr/local/lib/mqttcamera/lib
cp /home/pi/Projects/iot/camera/lib/Settings.py /usr/local/lib/mqttcamera/lib
cp /home/pi/Projects/iot/camera/lib/Homie_MQTT.py /usr/local/lib/mqttcamera/lib
cp /home/pi/Projects/iot/camera/lib/Algo.py /usr/local/lib/mqttcamera/lib
