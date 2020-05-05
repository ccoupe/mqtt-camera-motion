#!/usr/bin/env python3
import json
import socket
from uuid import getnode as get_mac
import os 
import sys
import logging

class Settings:

  def __init__(self, etcf, varf, log, st_machine):
    self.etcfname = etcf
    self.varfname = varf
    self.log = log
    self.state_machine = st_machine
    self.mqtt_server = "192.168.1.7"   # From json
    self.mqtt_port = 1883              # From json
    self.mqtt_client_name = "detection_1"   # From json
    self.mqtt_pub_topic = "cameras/family/webcam"  # From json
    self.mqtt_ctl_topic = "cameras/family/webcam_control"  # From json
    self.homie_device = None
    self.homie_name = None
    # in Linux /dev/video<n> matches opencv device (n) See '$ v4l2-ctl --all' ?
    self.camera_number = -1      # From json -1 works best for usb webcam on ubuntu
    self.camera_width = 320      # From json
    self.camera_height = 200     # From json
    #camera_fps = 15        # From json
    self.camera_warmup = 2       # From json
    self.lux_level = 0.6           # From json & mqtt
    self.lux_secs = 60*2           # TODO: From json & mqtt
    enable = True             # From mqtt
    self.contour_limit = 900       # From json & mqtt
    self.frame_skip = 10       # number of frames between checks. From json & mqtt
    self.active_hold = 10      # number of ticks to hold 'active' state. From json & mqtt
    self.tick_len = 5          # number of seconds per tick. From json & mqtt
    
    # IP and MacAddr are not important (should not be important).
    if sys.platform.startswith('linux'):
      s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
      s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
      s.connect(('<broadcast>', 0))
      self.our_IP =  s.getsockname()[0]
      # from stackoverflow (of course):
      self.macAddr = ':'.join(("%012x" % get_mac())[i:i+2] for i in range(0, 12, 2))
    elif sys.platform.startswith('darwin'):
      host_name = socket.gethostname() 
      self.our_IP = socket.gethostbyname(host_name) 
      self.macAddr = ':'.join(("%012x" % get_mac())[i:i+2] for i in range(0, 12, 2))
    else:
      # TODO somebody else can deal with Windows
      self.our_IP = "192.168.1.255"
      self.macAddr = "de:ad:be:ef"
    
    # load etc settings first
    self.load_settings(self.etcfname)
    # Use self.varfname (need to be root for this to work:
    if self.settings_rw:
      try:
        path = os.path.dirname(self.varfname)
        os.makedirs(path, 0o777, True)
      except:
          print("write conf error:", sys.exc_info()[0])
          os.exit()
      if os.path.exists(self.varfname):
        self.load_settings(self.varfname)
        print("Settings overridden with", self.varfname)
    else:
      self.log.info("Settings from %s", self.etcfname)
      

  def load_settings(self, fn):
    self.log.debug("loading settings from %s",fn)
    conf = json.load(open(fn))
    self.mqtt_server = conf.get("mqtt_server_ip", None)
    self.mqtt_port = conf.get("mqtt_port", 1883)
    self.mqtt_client_name = conf.get("mqtt_client_name", "Bad Client")
    self.mqtt_pub_topic = conf.get("topic_publish", None)
    self.mqtt_ctl_topic = conf.get("topic_control", None)
    self.homie_device = conf.get('homie_device', "unknown")
    self.homie_name = conf.get('homie_name', "Unknown Device")
    self.camera_number = conf.get("camera_number", -1)
    self.camera_width = conf.get("camera_width", 640)
    self.camera_height = conf.get("camera_height", 480)
    self.frame_skip = conf.get("frame_skip", 10)
    self.camera_warmup = conf.get("camera_warmup", 1.0)
    self.lux_level = conf.get("lux_level", 0.60)
    self.contour_limit = conf.get("contour_limit", 900)
    self.tick_len = conf.get("tick_len", 5)
    self.active_hold = conf.get("active_hold", 10)
    self.lux_secs = conf.get('lux_secs', 60)
    self.settings_rw = conf.get('settings_rw', False)
    # TODO? - Homie options for Lux device
    self.rtsp_uri = conf.get('rtsp_uri', None)
    self.snapshot = conf.get('snapshot', False)
    self.face_frames = conf.get('face_frames', 60)
    self.ml_algo = conf.get('ml_algo', None)
    self.confidence = conf.get('confidence', 0.4)
    self.ml_server_ip = conf.get('ml_server_ip', None)
    self.ml_port = conf.get("ml_port", None)
    self.image_url = "http://%s:7534/camera/snapshot.png" % self.our_IP
    self.mv_algo = conf.get('mv_algo', 'adrian_1')
    self.mv_threshold = conf.get('mv_threshold', 10)
    self.use_ml = conf.get('use_ml', None)
    self.log_events = conf.get('log_events', False)


  def display(self):
    self.log.info("==== Settings ====")
    self.log.info("%s", self.settings_serialize())
  
  def settings_serialize(self):
    st = {}
    st['mqtt_server_ip'] = self.mqtt_server
    st['mqtt_port'] = self.mqtt_port
    st['mqtt_client_name'] = self.mqtt_client_name
    st['homie_device'] = self.homie_device 
    st['homie_name'] = self.homie_name
    st['camera_number'] = self.camera_number
    st['camera_height'] = self.camera_height
    st['camera_width'] = self.camera_width
    st['camera_warmup'] = self.camera_warmup
    st['frame_skip'] = self.frame_skip
    st['lux_level'] = self.lux_level
    st['contour_limit'] = self.contour_limit
    st['tick_len'] = self.tick_len
    st['active_hold'] = self.active_hold
    st['lux_secs'] = self.lux_secs
    st['image_url'] = self.image_url
    st['rtsp_uri'] = self.rtsp_uri
    st['settings_rw'] = self.settings_rw
    st['snapshot'] = self.snapshot
    st['ml_algo'] = self.ml_algo
    st['face_frames'] = self.face_frames
    st['confidence'] = self.confidence
    st['ml_server_ip'] = self.ml_server_ip
    st['ml_port'] = self.ml_port
    st['mv_algo'] = self.mv_algo
    st['mv_threshold'] =self.mv_threshold
    st['use_ml'] = self.use_ml
    st['log_events'] = self.log_events
    str = json.dumps(st)
    return str

  def settings_deserialize(self, jsonstr):
    st = json.loads(jsonstr)
    if st['frame_skip']:
      fs = st['frame_skip']
      if fs < 0:
        fs = 0
      elif fs > 120:
        fs = 120
      self.frame_skip = fs
    if st['lux_level']:
      d = st['lux_level']
      if d < 0.01:
        d = 0.01
      elif d > 0.99:
        d = 0.99
      self.lux_level = d
    if st['contour_limit']:
      d = st['contour_limit']
      if d < 400:
        d = 400
      elif d > 1800:
        d = 1800
      self.contour_limit = d
    if st['tick_len']:
      d = st['tick_len']
      if d < 1:
        d = 1
      elif d > 30:
        d = 30
      self.tick_len = d
    if st['active_hold']:
      d = st['active_hold']
      if d < 1:
        d = 1
      elif d > 500:
        d = 500
      self.active_hold = d
    if st['lux_secs']:
      d = st['lux_secs']
      if d < 60:
        d = 60
      elif d > 3600:
        d = 3600
      self.lux_secs = d  

  def get_active_hold(self):
    #print("get active_hold")
    return self.active_hold
    
  def set_active_hold(self, v):
    global applog
    #print("set_active_hold", v)
    if v < 5:
      v = 5
    if v > 3600:
      v = 3600
    self.active_hold = v
    if self.settings_rw:
      f = open(self.varfname,"w+")
      f.write(self.settings_serialize())
      f.close()
    self.log.debug("leaving set_active_hold")

