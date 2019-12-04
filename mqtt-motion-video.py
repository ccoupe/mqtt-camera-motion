import cv2
import numpy as np
import paho.mqtt.client as mqtt
import sys
import json
import argparse
import warnings
from datetime import datetime 
import time,threading, sched

# many variables must be overridden by json config file
# and some can be modified via mqtt messages on the control topic
# 

mqtt_server = "192.168.1.7"   # From json
mqtt_port = 1883              # From json
mqtt_client_name = "detection_1"   # From json
mqtt_pub_topic = "cameras/family/webcam"  # From json
mqtt_ctl_topic = "cameras/family/webcam+control"  # From json
# in Linux /dev/video<n> matches opencv device (n) See '$ v4l2-ctl --all' ?
camera_number = -1      # From json -1 works best for usb webcam on ubuntu
camera_width = 320      # From json
camera_height = 200     # From json
#camera_fps = 15        # From json
camera_warmup = 2       # From json
lux_level = 0.6           # From json & mqtt
lux_secs = 60             # From json & mqtt
enable = True             # From mqtt
contour_limit = 900       # From json & mqtt
frame_skip = 10       # number of frames between checks. From json & mqtt
active_hold = 10      # number of ticks to hold 'active' state. From json & mqtt
tick_len = 5          # number of seconds per tick. From json & mqtt

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
active_ticks = 0

# some debugging and stats variables
debug_level = 0          # From command line
show_windows = False		# -d on the command line for True
luxcnt = 1
luxsum = 0.0
curlux = 0

def print_settings():
  global camera_number, camera_width, camera_height, camera_warmup
  global frame_skip, lux_level, contour_limit, tick_len, active_hold
  global mqtt_pub_topic, mqtt_ctl_topic,mqtt_client_name
  print("==== Settings ====")
  print("mqtt_client_name ", mqtt_client_name)
  print("mqtt_pub_topic: ", mqtt_pub_topic)
  print("mqtt_ctl_topic: ", mqtt_ctl_topic)
  print("camera_number: ", camera_number)
  print("camera_height: ", camera_height)
  print("camera_width: ", camera_width)
  print("camera_warmup: ", camera_warmup)
  print(settings_serialize())

def settings_serialize():
  global frame_skip, lux_level, contour_limit, tick_len, active_hold
  st = {}
  st['frame_skip'] = frame_skip
  st['lux_level'] = lux_level
  st['contour_limit'] = contour_limit
  st['tick_len'] = tick_len
  st['active_hold'] = active_hold
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

def log(msg, level=2):
  global luxcnt, luxsum, curlux, debug_level
  (dt, micro) = datetime.now().strftime('%H:%M:%S.%f').split('.')
  dt = "%s.%03d" % (dt, int(micro) / 1000)
  logmsg = "%-14.14s%-20.20s%3d %- 5.2f" % (dt, msg, curlux, luxsum/luxcnt)
  if level <= debug_level:
    print(logmsg)
      
def one_sec_timer():
  state_machine(FIRED)    # async? is it thread safe? maybe?
  return
  
def lux_timer():
  global client, mqtt_pub_topic, curlux, lux_thread, lux_secs
  msg = "lux=%d" %(curlux)
  client.publish(mqtt_pub_topic,msg)
  log(msg)
  lux_thread = threading.Timer(lux_secs, lux_timer)
  lux_thread.start()
  
  
def send_mqtt(str):
  global client, mqtt_pub_topic, curlux
  lstr = ",lux=%d" % (curlux)
  msg = str + lstr
  client.publish(mqtt_pub_topic,msg)
  log(msg)

def state_machine(signal):
  global motion_cnt, no_motion_cnt, active_ticks, active_hold, tick_len
  global timer_thread, state
  if state == WAITING:
    if signal == MOTION:
      motion_cnt = no_motion_cnt = 0
      active_ticks = active_hold
      send_mqtt("active")
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
        if (motion_cnt / (motion_cnt + no_motion_cnt)) > 0.10:   
          active_ticks = active_hold
          state = ACTIVE_ACC
          log("retrigger %02.2f" % (motion_cnt / (motion_cnt + no_motion_cnt)))
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
    dropped = False
    # check for lights out situation
    if curlux  < ((luxsum / luxcnt) * lux_level):
      log("lux step: %d" % curlux)
      luxsum = curlux
      luxcnt = 1
      dropped = True
    else:
      luxsum = luxsum + curlux
      luxcnt = luxcnt + 1
    return dropped

def find_movement(debug):
    global frame1, frame2, frame_skip, contour_limit
    motion = NO_MOTION
    drop1 = lux_calc(frame1)
    # if the light went out, don't try to detect motion
    if not drop1:
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
    if drop1 and motion == MOTION:
      print("drop1 found in MOTION")
    time.sleep((1.0/30.0) * frame_skip)
    ret, frame2 = cap.read()
    drop2 = lux_calc(frame2)
    if drop2 and motion == MOTION:
      print("drop2 found in MOTION")
    
    return motion == MOTION
    
def on_message(client, userdata, message):
    global enable,mqtt_pub_topic
    payload = str(message.payload.decode("utf-8"))
    #print("message received ", payload)
    if payload == "active" or payload == "inactive":
      # sent to ourself, ignore
      return
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
      js = payload[5:-1]
      setting_deserialize(js)
      return
    elif payload == 'conf':
      #  asked for our configuration
      global mqtt_pub_topic
      msg = "conf="+settings_serialize()
      client.publish(mqtt_pub_topic,msg)
      log("conf sent")
      return
    
def init_prog():
  global client, camera_warmup
  global mqtt_client_name, mqtt_port, mqtt_server, mqtt_ctl_topic
  global timer_thread, tick_len, lux_thread, lux_secs
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
  global frame_skip, lux_level, contour_limit, tick_len, active_hold
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
# filter warnings, load the configuration and initialize
#warnings.filterwarnings("ignore")

load_conf(args["conf"])
print_settings()

# fix debug levels
if args['debug'] == None:
  debug_level = 3
else:
  debug_level = args['debug']
if args['system'] == None:
  use_syslog = True
  if debug_level > 2:
    debug_level = 2
    show_windows = False;
    # setup syslog ?
elif debug_level == 3:
  show_windows = True
print("debug_level: ", debug_level)
#
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
ret, frame2 = cap.read()

while 1:
  if enable == True: 
    motion = find_movement(show_windows)
    if show_windows and cv2.waitKey(40) == 27:
      break
  else:
    time.sleep(15)
cleanup(show_windows)
