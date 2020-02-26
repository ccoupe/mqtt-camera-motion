#!/usr/bin/env python3
import json
import socket
from uuid import getnode as get_mac
import os 

class Settings:

  def __init__(self, etcf, varf, log, ovr=True):
    self.etcfname = etcf
    self.varfname = varf
    self.log = log
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
    
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.connect(('<broadcast>', 0))
    self.our_IP =  s.getsockname()[0]
    self.image_url = "http://%s:7534/camera/snapshot.png" % self.our_IP
    # from stackoverflow (of course):
    self.macAddr = ':'.join(("%012x" % get_mac())[i:i+2] for i in range(0, 12, 2))
   
    
    # load oldest first, newest last
    # create self.varfname (often need to be root)
    if ovr:
      try:
        path = os.path.dirname(self.varfname)
        os.makedirs(path, 0o777, True)
      except:
          print("write conf error:", sys.exc_info()[0])
          os.exit()
      self.load_settings(self.etcfname)
      if os.path.exists(self.varfname):
        self.load_settings(self.varfname)
        print("Settings overridden with", self.varfname)
      else:
        print("Settings from", self.etcfname)
    else:
      self.load_settings(self.etcfname)
    
  def getHwAddr(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    info = fcntl.ioctl(s.fileno(), 0x8927,  struct.pack('256s', bytes(ifname, 'utf-8')[:15]))
    return ':'.join('%02x' % b for b in info[18:24])

  def load_settings(self, fn):
    conf = json.load(open(fn))
    if conf["server_ip"]:
      self.mqtt_server = conf["server_ip"]
    if conf["port"]:
      self.mqtt_port = conf["port"]
    if conf["client_name"]:
      self.mqtt_client_name = conf["client_name"]
    if conf["topic_publish"]:
      self.mqtt_pub_topic = conf["topic_publish"]
    if conf["topic_control"]:
      self.mqtt_ctl_topic = conf["topic_control"]
    if conf['camera_number']:
      self.camera_number = conf["camera_number"]
    if conf["camera_width"]:
      self.camera_width = conf["camera_width"]
    if conf["camera_height"]:
      self.camera_height = conf["camera_height"]
    if conf["frame_skip"]:
      self.frame_skip = conf["frame_skip"]
    if conf["camera_warmup"]:
      self.camera_warmup = conf["camera_warmup"]
    if conf["lux_level"]:
      self.lux_level = conf["lux_level"]
    if conf["contour_limit"]:
      self.contour_limit = conf["contour_limit"]
    if conf["tick_len"]:
      self.tick_len = conf["tick_len"]
    if conf["active_hold"]:
      self.active_hold = conf["active_hold"]
    if conf['lux_secs']:
      self.lux_secs = conf['lux_secs']
    # TODO:  - Homie, options for Lux device
    if conf['homie_device']:
      self.homie_device = conf['homie_device']
    if conf['homie_name']:
      self.homie_name = conf['homie_name']
    self.rtsp_uri = conf.get('rtsp_uri', None)


  def print(self):
    print("==== Settings ====")
    print(self.settings_serialize())
  
  def settings_serialize(self):
    st = {}
    st['server_ip'] = self.mqtt_server
    st['port'] = self.mqtt_port
    st['client_name'] = self.mqtt_client_name
    st['topic_publish'] = self.mqtt_pub_topic
    st['topic_control'] = self.mqtt_ctl_topic
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
    #print("set_active_hold", v)
    if v < 5:
      v = 5
    if v > 3600:
      v = 3600
    self.active_hold = v
    f = open(self.varfname,"w+")
    f.write(self.settings_serialize())
    f.close()
    print("leaving set_active_hold")

