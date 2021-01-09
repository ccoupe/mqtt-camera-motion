#!/usr/bin/env bash
mosquitto_pub -h 192.168.1.7 -t network/restart -m `hostname`
