#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import sys
import json
from datetime import datetime
import time, threading, sched
from lib.Constants import State, Event
import logging

class Homie_MQTT:

  def __init__(self, settings, getCb, setCb):
    self.settings = settings
    self.log = settings.log
    self.getCb = getCb
    self.setCb = setCb
    self.detect_flag = False
    # init server connection
    self.client = mqtt.Client(settings.mqtt_client_name, False)
    #self.client.max_queued_messages_set(3)
    hdevice = self.hdevice = self.settings.homie_device  # "device_name"
    hlname = self.hlname = self.settings.homie_name     # "Display Name"
    # beware async timing with on_connect
    self.client.on_connect = self.on_connect
    self.client.on_subscribe = self.on_subscribe
    self.client.on_message = self.on_message
    self.client.on_disconnect = self.on_disconnect
    rc = self.client.connect(settings.mqtt_server, settings.mqtt_port)
    if rc != mqtt.MQTT_ERR_SUCCESS:
        self.log.warn("network missing?")
        exit()
    self.client.loop_start()

    # short cuts to stuff we really care about
    self.hmotion_pub = "homie/"+hdevice+"/motionsensor/motion"
    self.hstatus_pub = "homie/"+hdevice+"/motionsensor/motion/status"  
    self.hactive_pub = "homie/"+hdevice+"/motionsensor/active_hold"
    self.hactive_sub = "homie/"+hdevice+"/motionsensor/active_hold/set"
    self.hcontrol_pub = "homie/"+hdevice+"/motionsensor/control"
    self.hcontrol_sub = "homie/"+hdevice+"/motionsensor/control/set"
    #print("Homie_MQTT __init__")
    self.create_topics(hdevice, hlname)
    
    rc,_ = self.client.subscribe(self.hactive_sub)
    if rc != mqtt.MQTT_ERR_SUCCESS:
      print("Subscribe failed: ", rc)
    else:
      self.log.info("Init() Subscribed to %s" % self.hactive_sub)
      
    rc,_ = self.client.subscribe(self.hcontrol_sub)
    if rc != mqtt.MQTT_ERR_SUCCESS:
      print("Subscribe failed: ", rc)
    else:
      self.log.info("Init() Subscribed to %s" % self.hcontrol_sub)
    
  def create_topics(self, hdevice, hlname):
    self.log.info("Begin topic creation")
    # create topic structure at server - these are retained! 
    #self.client.publish("homie/"+hdevice+"/$homie", "3.0.1", mqos, retain=True)
    self.publish_structure("homie/"+hdevice+"/$homie", "3.0.1")
    self.publish_structure("homie/"+hdevice+"/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/$state", "ready")
    self.publish_structure("homie/"+hdevice+"/$mac", self.settings.macAddr)
    self.publish_structure("homie/"+hdevice+"/$localip", self.settings.our_IP)
    # Could have two nodes a motionsensor and a lux sensor
    self.publish_structure("homie/"+hdevice+"/$nodes", "motionsensor")
    
    # motionsensor node
    self.publish_structure("homie/"+hdevice+"/motionsensor/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/motionsensor/$type", "sensor")
    self.publish_structure("homie/"+hdevice+"/motionsensor/$properties","motion,active_hold,control")
    # Property of 'motion'
    self.publish_structure("homie/"+hdevice+"/motionsensor/motion/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/motionsensor/motion/$datatype", "boolean")
    self.publish_structure("homie/"+hdevice+"/motionsensor/motion/$settable", "false")
    self.publish_structure("homie/"+hdevice+"/motionsensor/motion/$retained", "true")
    # Property 'active_hold'
    self.publish_structure("homie/"+hdevice+"/motionsensor/active_hold/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/motionsensor/active_hold/$datatype", "integer")
    self.publish_structure("homie/"+hdevice+"/motionsensor/active_hold/$settable", "true")
    self.publish_structure("homie/"+hdevice+"/motionsensor/active_hold/$retained", "true")
    self.publish_structure("homie/"+hdevice+"/motionsensor/active_hold/$format", "5:3600")
    # Property 'control'
    self.publish_structure("homie/"+hdevice+"/motionsensor/control/$name", hlname)
    self.publish_structure("homie/"+hdevice+"/motionsensor/control/$datatype", "boolean")
    self.publish_structure("homie/"+hdevice+"/motionsensor/control/$settable", "true")
    self.publish_structure("homie/"+hdevice+"/motionsensor/control/$retained", "true")
    # Done with structure. 

    self.log.info("homeie topics created")
    #Publish the active_hold value, don't retain)    
    self.client.publish(self.hactive_pub, self.settings.active_hold, 0, False)
    
  def publish_structure(self, topic, payload):
    self.client.publish(topic, payload, qos=1, retain=True)
    
  # publish with attempts for error recovery
  def publish_msg(self, topic, payload):
    rc = mqtt.MQTT_ERR_NO_CONN
    while rc != mqtt.MQTT_ERR_SUCCESS:
      rc,_ = self.client.publish(topic, payload, qos=1, retain=False)
      if rc == mqtt.MQTT_ERR_NO_CONN:
        # on_disconnect() Should be called to reconnect, so we wait.
        if not self.isConnected():
          self.log.warn("Publish_msg() Waiting for connection")
          time.sleep(60)
      elif rc == mqtt.MQTT_ERR_QUEUE_SIZE:
        self.log.warn("Publish_msg() waiting to queue")
        time.sleep(15)
      elif rc != mqtt.MQTT_ERR_SUCCESS:
        self.log.warn("Publish_msg() unknown rc: %d", rc)

  def on_subscribe(self, client, userdata, mid, granted_qos):
    self.log.warn("on_subscribe() %s %d %d", str(userdata), int(mid), int(granted_qos))
        
  def on_message(self, client, userdata, message):
    global off_hack
    topic = message.topic
    payload = str(message.payload.decode("utf-8"))
    self.log.info("/control is: %s", payload)
    try:
      if (topic == self.hactive_sub):
        v = int(payload)
        if self.getCb() != v:
          self.setCb(v)
          self.publish_msg(self.hactive_pub, str(self.getCb()))
        else:
          self.log.info("active_hold not changed")
      elif (topic == self.hcontrol_sub):
        if (payload == 'off'):
          self.settings.state_machine(Event.lights_out)
        elif (payload == 'on'):
          pass
        elif payload.startswith('detect'):
          ls = payload.split('-')
          if len(ls) > 1:
            self.log.debug("switching detector to %s", ls[1])
            self.settings.ml_algo = ls[1]
          self.settings.state_machine(Event.check)
        elif payload == 'enable':
          self.settings.state_machine(Event.start)
        elif payload == 'disable':
          self.settings.state_machine(Event.stop)
        else:
          self.log.warn("control payload unknown: %s", payload)
      else:
        self.log.warn("on_message() unknown command: %s", message)
    except:
      self.log.warn("on_message error: %s", sys.exc_info()[0])

    
  def isConnected(self):
    return self.mqtt_connected
         
  def on_connect(self, client, userdata, flags, rc):
    if rc != mqtt.MQTT_ERR_SUCCESS:
      self.log.warn("Connection failed")
      self.mqtt_connected = False
      time.sleep(60)
      self.client.reconnect()
    else:
      self.mqtt_connected = True
    
  def on_disconnect(self, client, userdata, rc):
    self.mqtt_connected = False
    self.log.info("Disconnected")
    while not self.mqtt_connected:
      time.sleep(60)
      self.log.info("mqtt reconnecting")
      self.client.reconnect()
      
  
  def send_active(self, tf):
    global detect_flag
    if tf:
      msg =  "active"
      self.publish_msg(self.hmotion_pub, "true")
      self.publish_msg(self.hstatus_pub, msg)
    else:
      msg = "inactive"
      self.publish_msg(self.hmotion_pub, "false")
      self.publish_msg(self.hstatus_pub, msg)
    self.log.info(msg)

  def send_detect(self, tf):
    if tf:
      self.publish_msg(self.hcontrol_pub, "true")
      self.log.info("mqtt_publish detect is true")
    else:
      self.publish_msg(self.hcontrol_pub, "false")
      self.log.info("mqtt_publish detect is false")
