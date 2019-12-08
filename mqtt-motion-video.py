#!/usr/bin/env python3
import cv2
import numpy as np
import paho.mqtt.client as mqtt
import sys
import json
import argparse
import warnings
from datetime import datetime
import time,threading, sched
import socket
from subprocess import call

# many variables must be overridden by json config file
# and some can be modified via mqtt messages on the control topic
# 

mqtt_server = "192.168.1.7"   # From json
mqtt_port = 1883              # From json
mqtt_client_name = "detection_1"   # From json
mqtt_pub_topic = "cameras/family/webcam"  # From json
mqtt_ctl_topic = "cameras/family/webcam_control"  # From json
# in Linux /dev/video<n> matches opencv device (n) See '$ v4l2-ctl --all' ?
camera_number = -1      # From json -1 works best for usb webcam on ubuntu
camera_width = 320      # From json
camera_height = 200     # From json
#camera_fps = 15        # From json
camera_warmup = 2       # From json
lux_level = 0.6           # From json & mqtt
lux_secs = 60*2           # TODO: From json & mqtt
enable = True             # From mqtt
contour_limit = 900       # From json & mqtt
frame_skip = 10       # number of frames between checks. From json & mqtt
active_hold = 10      # number of ticks to hold 'active' state. From json & mqtt
tick_len = 5          # number of seconds per tick. From json & mqtt
our_ip = None
image_url = None
# state machine enums (cheap enums)
# signals:
MOTION = 1
NO_MOTION = 0
FIRED = 2
# states
WAITING = 0
ACTIVE_ACC = 1
INACT_ACC = 2

# start machine internal variables
state = WAITING
motion_cnt = 0
no_motion_cnt = 0
timer_thread = None
snapshot_thread = None
active_ticks = 0
frattr1 = False
frattr2 = False
off_hack = False

# some debugging and stats variables
debug_level = 0          # From command line
show_windows = False		# -d on the command line for True
luxcnt = 1
luxsum = 0.0
curlux = 0
use_syslog = False

def print_settings():
  global camera_number, camera_width, camera_height, camera_warmup
  global frame_skip, lux_level, contour_limit, tick_len, active_hold
  global mqtt_pub_topic, mqtt_ctl_topic,mqtt_client_name
  print("==== Settings ====", flush=True)
  print("mqtt_client_name ", mqtt_client_name, flush=True)
  print("mqtt_pub_topic: ", mqtt_pub_topic, flush=True)
  print("mqtt_ctl_topic: ", mqtt_ctl_topic, flush=True)
  print("camera_number: ", camera_number, flush=True)
  print("camera_height: ", camera_height, flush=True)
  print("camera_width: ", camera_width, flush=True)
  print("camera_warmup: ", camera_warmup, flush=True)
  print(settings_serialize())

def settings_serialize():
  global frame_skip, lux_level, contour_limit, tick_len, active_hold, lux_secs
  global image_url
  st = {}
  st['frame_skip'] = frame_skip
  st['lux_level'] = lux_level
  st['contour_limit'] = contour_limit
  st['tick_len'] = tick_len
  st['active_hold'] = active_hold
  st['lux_secs'] = lux_secs
  st['image_url'] = image_url
  str = json.dumps(st)
  return str

def settings_deserialize(jsonstr):
  global frame_skip, lux_level, contour_limit, tick_len, active_hold
  st = json.loads(jsonstr)
  if st['frame_skip']:
    fs = st['frame_skip']
    if fs < 0:
      fs = 0
    elif fs > 120:
      fs = 120
    frame_skip = fs
  if st['lux_level']:
    d = st['lux_level']
    if d < 0.01:
      d = 0.01
    elif d > 0.99:
      d = 0.99
    lux_level = d
  if st['contour_limit']:
    d = st['contour_limit']
    if d < 400:
      d = 400
    elif d > 1800:
      d = 1800
    contour_limit = d
  if st['tick_len']:
    d = st['tick_len']
    if d < 1:
      d = 1
    elif d > 30:
      d = 30
    tick_len = d
  if st['active_hold']:
    d = st['active_hold']
    if d < 1:
      d = 1
    elif d > 500:
      d = 500
    active_hold = d
  if st['lux_secs']:
    d = st['lux_secs']
    if d < 60:
      d = 60
    elif d > 3600:
      d = 3600
    lux_secs = d

def log(msg, level=2):
  global luxcnt, luxsum, curlux, debug_level, use_syslog
  if level > debug_level:
    return
  if use_syslog:
    logmsg = "%-20.20s%3d %- 5.2f" % (msg, curlux, luxsum/luxcnt)
  else:
    (dt, micro) = datetime.now().strftime('%H:%M:%S.%f').split('.')
    dt = "%s.%03d" % (dt, int(micro) / 1000)
    logmsg = "%-14.14s%-20.20s%3d %- 5.2f" % (dt, msg, curlux, luxsum/luxcnt)
  print(logmsg, flush=True)
      
def one_sec_timer():
  global off_hack
  if off_hack:
    off_hack = False;     # clear hack for lights off
  state_machine(FIRED)    # async? is it thread safe? maybe?
  return
  
def lux_timer():
  global client, mqtt_pub_topic, curlux, lux_thread, lux_secs
  msg = "lux=%d" %(curlux)
  client.publish(mqtt_pub_topic,msg)
  log(msg, 2)
  lux_thread = threading.Timer(lux_secs, lux_timer)
  lux_thread.start()
  
def snapshot_timer():
  global snapshot_thread, frame1, state
  dim = (320, 240)
  nimg = cv2.resize(frame1, dim, interpolation = cv2.INTER_AREA) 
  if state == ACTIVE_ACC:
    status = cv2.imwrite('/var/www/camera/snapshot.png',nimg) 
  else:
    gray = cv2.cvtColor(nimg, cv2.COLOR_BGR2GRAY)
    status = cv2.imwrite('/var/www/camera/snapshot.png',gray) 
  snapshot_thread = threading.Timer(60, snapshot_timer)
  snapshot_thread.start()
  
  
def send_mqtt(str):
  global client, mqtt_pub_topic, curlux
  lstr = ",lux=%d" % (curlux)
  msg = str + lstr
  client.publish(mqtt_pub_topic,msg)
  log(msg, 1)

def state_machine(signal):
  global motion_cnt, no_motion_cnt, active_ticks, active_hold, tick_len, lux_cnt
  global timer_thread, state, off_hack
  if state == WAITING:
    if signal == MOTION:
      # hack ahead. Don't send active if lux_sum & cnt have been reset
      # attempt to ignore false positives when lights go out
      if not off_hack:
        send_mqtt("active")
        state = ACTIVE_ACC
      else:
        state = ACTIVE_ACC
    elif signal == NO_MOTION:
      state = WAITING
    elif signal == FIRED:
      timer_thread = threading.Timer(tick_len, one_sec_timer)
      timer_thread.start()
      state = WAITING
      
  elif state == ACTIVE_ACC:
    if signal == MOTION:
      motion_cnt += 1
      state = ACTIVE_ACC
    elif signal == NO_MOTION:
      no_motion_cnt += 1
      state = ACTIVE_ACC
    elif signal == FIRED:
      active_ticks -= 1
      if active_ticks <= 0:
        # Timed out
        msum = motion_cnt + no_motion_cnt
        if msum > 0 and (motion_cnt / msum) > 0.10:   
          active_ticks = active_hold
          state = ACTIVE_ACC
          log("retrigger %02.2f" % (motion_cnt / (motion_cnt + no_motion_cnt)),2)
          motion_cnt = no_motion_cnt = 0
          state = ACTIVE_ACC
        else:
          send_mqtt("inactive")
          state = WAITING
      timer_thread = threading.Timer(tick_len, one_sec_timer)
      timer_thread.start()
    else:
      print("Unknown signal in state ACTIVE_ACC")
  else:
    print("Unknow State")
    

def lux_calc(frame):
    global luxcnt, luxsum, lux_level, curlux
    frmgray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    curlux = np.mean(frmgray)
    ok = True
    # check for lights out situation
    if curlux  < ((luxsum / luxcnt) * lux_level):
      log("LUX STEP: %d" % curlux, 2)
      luxsum = curlux
      luxcnt = 1
      ok = False
    else:
      luxsum = luxsum + curlux
      luxcnt = luxcnt + 1
    return ok

def find_movement(debug):
    global frame1, frame2, frame_skip, contour_limit, frattr1, frattr2
    motion = NO_MOTION
    # if the light went out, don't try to detect motion
    if frattr1 and frattr2:
      diff = cv2.absdiff(frame1, frame2)
      gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
      blur = cv2.GaussianBlur(gray, (5,5), 0)
      _, thresh = cv2.threshold(blur, 20, 255, cv2.THRESH_BINARY)
      dilated = cv2.dilate(thresh, None, iterations=3)
      contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
      for contour in contours:
          (x, y, w, h) = cv2.boundingRect(contour)
          
          if cv2.contourArea(contour) < contour_limit:
              continue
          motion = MOTION
          state_machine(motion)
          if debug:
            cv2.rectangle(frame1, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(frame1, "Status: {}".format('Movement'), (10, 20), cv2.FONT_HERSHEY_SIMPLEX,
                        1, (0, 0, 255), 3)
  
      if debug:
        cv2.drawContours(frame1, contours, -1, (0, 255, 0), 2)
        cv2.imshow("feed", frame1)
      if motion == NO_MOTION:
        state_machine(NO_MOTION)
    frame1 = frame2
    frattr1 = frattr2
    time.sleep((1.0/30.0) * frame_skip)
    ret, frame2 = cap.read() 
    frattr2 = lux_calc(frame2)   
    return motion == MOTION
    
def on_message(client, userdata, message):
    global enable,mqtt_pub_topic, off_hack
    payload = str(message.payload.decode("utf-8"))
    if payload == "active" or payload == "inactive":
      # sent to ourself, ignore
      return
    if payload == 'off':
      # switch went off - trigger hack to not send motion
      log("Switch went off",1)
      off_hack = True
    if payload == "enable":
      if not enable:
        enable = True
        # TODO - signal something to restart with two new frames from the camera
        # this message arrives async to the main loop
        # start timers.
      return
    elif payload == "disable":
      if enable:
        enable = False
        # TODO - cancel timers.
      return
    elif payload.startswith('conf='):
      # json ahead. We change out settings.
      js = payload[5:]
      settings_deserialize(js)
      print_settings()
      return
    elif payload == 'conf':
      #  asked for our configuration
      global mqtt_pub_topic
      msg = "conf="+settings_serialize()
      client.publish(mqtt_pub_topic,msg)
      log("conf sent", 2)
      return
    else:
      print("unknown command ", payload)
    
def init_prog():
  global client, camera_warmup
  global mqtt_client_name, mqtt_port, mqtt_server, mqtt_ctl_topic
  global timer_thread, tick_len, lux_thread, lux_secs, snapshot_thread
  # For Linux: /dev/video0 is device 0 (pi builtin eg: or first usb webcam)
  time.sleep(camera_warmup)
  client = mqtt.Client(mqtt_client_name, mqtt_port)
  client.connect(mqtt_server)
  client.subscribe(mqtt_ctl_topic)
  client.on_message = on_message
  client.loop_start()
  timer_thread = threading.Timer(tick_len, one_sec_timer)
  timer_thread.start()
  lux_thread = threading.Timer(lux_secs, lux_timer)
  lux_thread.start()
  snapshot_thread = threading.Timer(60, snapshot_timer)
  snapshot_thread.start()
  return cap


def cleanup(do_windows):
  global client, cap, luxcnt, luxsum, timer_thread
  if show_windows:
    cv2.destroyAllWindows()
  cap.release()
  client.loop_stop()
  if show_windows:
    print("average of lux mean ", luxsum/luxcnt)
  timer_thread.cancel()
  return

def load_conf(fn):
  global mqtt_client_name, mqtt_port, mqtt_server, mqtt_ctl_topic,mqtt_pub_topic
  global camera_number, camera_width, camera_height, camera_warmup
  global frame_skip, lux_level, contour_limit, tick_len, active_hold, lux_secs
  conf = json.load(open(fn))
  if conf["server_ip"]:
    mqtt_server = conf["server_ip"]
  if conf["port"]:
    mqtt_port = conf["port"]
  if conf["client_name"]:
    mqtt_client_name = conf["client_name"]
  if conf["topic_publish"]:
    mqtt_pub_topic = conf["topic_publish"]
  if conf["topic_control"]:
    mqtt_ctl_topic = conf["topic_control"]
  if conf['camera_number']:
    camera_number = conf["camera_number"]
  if conf["camera_width"]:
    camera_width = conf["camera_width"]
  if conf["camera_height"]:
    camera_height = conf["camera_height"]
  if conf["frame_skip"]:
    frame_skip = conf["frame_skip"]
  if conf["camera_warmup"]:
    camera_warmup = conf["camera_warmup"]
  if conf["lux_level"]:
    lux_level = conf["lux_level"]
  if conf["contour_limit"]:
    contour_limit = conf["contour_limit"]
  if conf["tick_len"]:
    tick_len = conf["tick_len"]
  if conf["active_hold"]:
    active_hold = conf["active_hold"]
  if conf['lux_secs']:
    lux_secs = conf['lux_secs']
    
def getNetworkIp():
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
  s.connect(('<broadcast>', 0))
  return s.getsockname()[0]


# Start here
# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-c", "--conf", required=True, type=str,
	help="path and name of the json configuration file")
ap.add_argument("-d", "--debug", action='store', type=int, default='3',
  nargs='?', help="debug level, default is 3")
ap.add_argument("-s", "--system", action = 'store', nargs='?',
  default=False, help="use syslog")
args = vars(ap.parse_args())

load_conf(args["conf"])
our_ip = getNetworkIp()
image_url = "http://%s:7534/camera/snapshot.png" % our_ip
print_settings()
#call(["python3", "-m", "http.server", "--bind", our_ip, 
#  "--directory", "/var/www", "7534"])

# fix debug levels
if args['debug'] == None:
  debug_level = 3
else:
  debug_level = args['debug']
if args['system'] == None:
  use_syslog = True
  debug_level =1
  show_windows = False;
  # setup syslog ?
elif debug_level == 3:
  show_windows = True

# Done with setup. 
cap = cv2.VideoCapture(camera_number)
if not  cap.isOpened():
  print("FAILED to open camera")
  exit()
ret = cap.set(3, camera_width)
ret = cap.set(4, camera_height)
#ret = cap.set(5, camera_fps)
init_prog()
ret, frame1 = cap.read()
frattr1 = lux_calc(frame1)
ret, frame2 = cap.read()
frattr2 = lux_calc(frame2)

while 1:
  if enable == True: 
    motion = find_movement(show_windows)
    if show_windows and cv2.waitKey(40) == 27:
      break
  else:
    time.sleep(15)
cleanup(show_windows)
