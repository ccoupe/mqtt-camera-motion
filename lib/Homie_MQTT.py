#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import sys
import json

from datetime import datetime
import time,threading, sched

import time

class Homie_MQTT:

  def __init__(self, settings, getCb, setCb):
    self.settings = settings
    self.log = settings.log
    self.getCb = getCb
    self.setCb = setCb
  
    # init server connection
    self.client = mqtt.Client(settings.mqtt_client_name, False)
    self.client.max_queued_messages_set(3)
    hdevice = self.hdevice = self.settings.homie_device  # "device_name"
    hlname = self.hlname = self.settings.homie_name     # "Display Name"
    # beware async timing with on_connect
    self.client.on_connect = self.on_connect
    self.client.on_message = self.on_message
    self.client.on_disconnect = self.on_disconnect
    self.client.connect(settings.mqtt_server, settings.mqtt_port)
    self.client.loop_start()

    # short cuts to stuff we really care about
    self.hmotion_pub = "homie/"+hdevice+"/motionsensor/motion"
    self.hstatus_pub = "homie/"+hdevice+"/motionsensor/motion/status"  
    self.hactive_pub = "homie/"+hdevice+"/motionsensor/active_hold"
    self.hactive_sub = "homie/"+hdevice+"/motionsensor/active_hold/set"
    print("Homie_MQTT __init__")
    self.create_topics(hdevice, hlname)
    
  def create_topics(self, hdevice, hlname):
    print("Begin topic creation")
    mqos = 0
    # create topic structure at server - these are retained! 
    #self.client.publish("homie/"+hdevice+"/$homie", "3.0.1", mqos, retain=True)
    self.publish_structure("homie/"+hdevice+"/$homie", "3.0.1")
    self.client.publish("homie/"+hdevice+"/$name", hlname, mqos, retain=True)
    self.client.publish("homie/"+hdevice+"/$state", "ready", mqos, retain=True)
    self.client.publish("homie/"+hdevice+"/$mac", self.settings.macAddr, True)
    self.client.publish("homie/"+hdevice+"/$localip", self.settings.our_IP, mqos, True)
    # Could have two nodes a motionsensor and a lux sensor
    self.client.publish("homie/"+hdevice+"/$nodes", "motionsensor", mqos, True)
    
    # motionsensor node
    self.client.publish("homie/"+hdevice+"/motionsensor/$name", hlname, mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/$type", "sensor", mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/$properties","motion,active_hold", mqos, True)
    # Property of 'motion'
    self.client.publish("homie/"+hdevice+"/motionsensor/motion/$name", hlname, mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/motion/$datatype", "boolean", mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/motion/$settable", "false", mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/motion/$retained", "true", mqos, True)
    # Property 'active_hold'
    self.client.publish("homie/"+hdevice+"/motionsensor/active_hold/$name", hlname, mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/active_hold/$datatype", "integer", mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/active_hold/$settable", "true", mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/active_hold/$retained", "true", mqos, True)
    self.client.publish("homie/"+hdevice+"/motionsensor/active_hold/$format", "5:3600", mqos, True)
    # Done with structure. 

    print("homeie topics created")
    #Publish the active_hold value, don't retain)    
    self.client.publish(self.hactive_pub, self.settings.active_hold, mqos, False)
    
  def publish_structure(self, topic, payload):
    self.client.publish(topic, payload, qos=1, retain=True)
    
        
  def on_message(self, client, userdata, message):
    global settings
    topic = message.topic
    payload = str(message.payload.decode("utf-8"))
    #print("on_message ", topic, " ", payload)
    try:
      if (topic == self.hactive_sub):
        v = int(payload)
        if self.getCb() != v:
          self.setCb(v)
          self.client.publish(self.hactive_pub, str(self.getCb()))
        else:
          print("active_hold not changed")
      else:
        print("on_message() unknown command ", message)
    except:
      print("on_message error:", sys.exc_info()[0])

    
  def isConnected(self):
    return self.mqtt_connected
    
  def on_connect(self, client, userdata, flags, rc):
    if rc == 0:
      self.mqtt_connected = True
      print("Connected to %s" % self.hactive_sub)
      rc,_ = self.client.subscribe(self.hactive_sub)
      if rc != MQTT_ERR_SUCCESS:
        print("Subscribe failed: ", rc)
    else:
      print("Failed to connect:", rc)
       
  def on_disconnect(self, client, userdata, rc):
    self.mqtt_connected = False
    log("mqtt reconnecting")
    self.client.reconnect()
      
  
  def send_active(self, tf):
    global client, mqtt_pub_topic, curlux
    #lstr = ",lux=%d" % (curlux)
    #msg = str + lstr
    if tf:
      msg =  "active"
      self.client.publish(self.hmotion_pub, "true")
      self.client.publish(self.hstatus_pub, msg)
    else:
      msg = "inactive"
      self.client.publish(self.hmotion_pub, "false")
      self.client.publish(self.hstatus_pub, msg)
    # client.publish(mqtt_pub_topic,msg)
    self.log(msg, 1)
  
