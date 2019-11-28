import cv2
import numpy as np
import paho.mqtt.client as mqtt
import sys
import json
import argparse
import warnings
from datetime import datetime 
import time,threading, sched

# may variable can be overridden by json config file
# and some can be modified via mqtt messages on the control topic
# 

mqtt_server = "192.168.1.7"   # From json
mqtt_port = 1883              # From json
mqtt_client_name = "office_detection_1"   # From json
mqtt_pub_topic = "cameras/office/webcam"  # From json
mqtt_ctl_topic = "cameras/office/webcam"  # From json
# in Linux /dev/video<n> matches opencv device (n) See '$ v4l2-ctl --all' ?
camera_number = -1        # From json
camera_width = 400 #320   # From json
camera_height = 400 #200  # From json
camera_fps = 15           # From json
camera_warmup = 2.5       # From json
luxlevel = 0.6            # From json & mqtt
curlux = 0
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
loglevel = 0          # From command line
show_windows = False;		# -d on the command line for true
luxcnt = 1
luxsum = 0.0
curlux = 0

def log(msg, level=2):
  global luxcnt, luxsum, curlux, loglevel
  (dt, micro) = datetime.now().strftime('%H:%M:%S.%f').split('.')
  dt = "%s.%03d" % (dt, int(micro) / 1000)
  #tstr = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
  print ("%-14.14s%-20.20s%3d %- 5.2f" % (dt, msg, curlux, luxsum/luxcnt))
  
# 
def one_sec_timer():
  state_machine(FIRED)    # async? is it thread safe? maybe?
  return
  
def lux_timer():
  global client, pub_topic, curlux, lux_thread, lux_secs
  msg = "lux=%d" %(curlux)
  client.publish(mqtt_pub_topic,msg)
  log(msg)
  lux_thread = threading.Timer(lux_secs, lux_timer)
  lux_thread.start()
  
  
def send_mqtt(str):
  global client, pub_topic, curlux
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
    global luxcnt, luxsum, luxlevel, curlux
    frmgray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    curlux = np.mean(frmgray)
    dropped = False
    # check for lights out situation
    if curlux  < ((luxsum / luxcnt) * luxlevel):
      log("lux step: %d" % curlux)
      luxsum = curlux
      luxcnt = 1
      dropped = True
    else:
      luxsum = luxsum + curlux
      luxcnt = luxcnt + 1
    return dropped

def find_movement(debug):
    global frame1, frame2, frame_skip, contour_limit, lights_out
    motion = NO_MOTION
    drop = lux_calc(frame1)
    # if the light went out, don't try to detect motion
    if not drop:
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
    time.sleep((1.0/30.0) * frame_skip)
    ret, frame2 = cap.read()
    return motion == MOTION
    
def on_message(client, userdata, message):
    global enable
    payload = str(message.payload.decode("utf-8"))
    #print("message received ", payload)
    if payload == "active" or payload == "inactive":
      # send to ourself, ignore
      return
    if payload == "enable":
      if not enable:
        enable = True
        # TODO - signal something to restart with two new frames from the camera
        # this message arrives async to the main loop
      return
    elif payload == "disable":
      if enable:
        enable = False
        # TODO - cancel timers
      return
    elif payload == "active" or payload == "inactive":
      # just us talking to ourself (topic_pub == topic_sub)
      retun
    # below here, we have variable=value messages
    flds = payload.split("=")
    if flds.len != 2:
      return
    if flds[0] == "luxlevel":
      luxi = int(flds[1])
      if luxi > 0 and luxi < 100:
        luxlevel = int(luxi / 100)
    elif flds[0] == "frame_skip":
      fs = int(flds[1])
      if fs < 0:
        fs = 0
      elif fs > 120:
        fs = 120
      frame_skip = fs
    elif flds[0] == "delay":
      d = int(flds[1])
      if d < 1:
        d = 1
      elif d > (15 * 60):
        d = 15 * 60
      inactive_secs = d
    elif flds[0] == "contour":
      d = int(flds[1])
      if d < 200:
        d = 200
      elif d > 1500:
        d = 1500
      contour_limit = d
      
    
def init_prog():
  global client, camera_number, camera_width, camera_width, camera_warmup,camera_fps
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
  global camera_number, camera_width, camera_width, camera_warmup,camera_fps
  global mqtt_client_name, mqtt_port, mqtt_server, mqtt_ctl_topic, luxlevel
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
  if conf["camera_width"]:
    camera_width = conf["camera_width"]
  if conf["camera_height"]:
    camera_height = conf["camera_height"]
  if conf["camera_fps"]:
    camera_fps = conf["camera_fps"]
  if conf["camera_warmup_time"]:
    camera_warmup = conf["camera_warmup_time"]
  if conf["camera_number"]:
    camera_number = conf["camera_number"]
  if conf["lux_level"]:
    luxlevel = conf["lux_level"]
  if conf["contour"]:
    contour_limit = conf["contour"]
  

# Start here
# construct the argument parser and parse the arguments
#ap = argparse.ArgumentParser()
#ap.add_argument("-c", "--conf", required=True,
#	help="path to the JSON configuration file")
#ap.add_argument("-d", 
#  help="show windows (requires X11)")
#args = vars(ap.parse_args())
# filter warnings, load the configuration and initialize
#warnings.filterwarnings("ignore")
#load_conf(args["conf"])
argl = len(sys.argv)
print('Argument(s) passed: {}'.format(str(sys.argv)))
if argl <= 1 or argl > 3:
  print("args are [-d] <conf.json>", argl)
  exit()
if sys.argv[1] == "-d":
  show_windows = True
  load_conf(sys.argv[2])
else:
  show_windows = False
  load_conf(sys.argv[1])
  
global frame1, frame2, cap
cap = cv2.VideoCapture(camera_number)
if not  cap.isOpened():
  print("FAILED to open camera")
  exit()
ret = cap.set(3, camera_width)
ret = cap.set(4, camera_height)
ret = cap.set(5, camera_fps)
init_prog()
ret, frame1 = cap.read()
ret, frame2 = cap.read()

while 1:
  if enable == True: 
    motion = find_movement(show_windows)
    if show_windows and cv2.waitKey(40) == 27:
      break

cleanup(show_windows)
