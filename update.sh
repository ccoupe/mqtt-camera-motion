#!/bin/bash 
systemctl stop mqttcamera
mkdir -p /usr/local/lib/mqttcamera/lib
cp $HOME/Projects/iot/camera/mqtt-motion-video.py /usr/local/lib/mqttcamera
cp $HOME/Projects/iot/camera/lib/Constants.py /usr/local/lib/mqttcamera/lib
cp $HOME/Projects/iot/camera/lib/Settings.py /usr/local/lib/mqttcamera/lib
cp $HOME/Projects/iot/camera/lib/Homie_MQTT.py /usr/local/lib/mqttcamera/lib
cp $HOME/Projects/iot/camera/lib/Algo.py /usr/local/lib/mqttcamera/lib
