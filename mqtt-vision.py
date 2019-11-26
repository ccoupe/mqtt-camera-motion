import cv2
import numpy as np
import paho.mqtt.client as mqtt
import sys
import json
import argparse
import warnings
import datetime,time,threading

# Defaults = can/should be overridden by json config file
# and some can be modified via mqtt messages on control topic
global client
global camera_number, camera_width, camera_width, camera_warmup,camera_fps
global mqtt_client_name, mqtt_port, mqtt_server, mqtt_ctl_topic
mqtt_server = "192.168.1.7"
mqtt_port = 1883
mqtt_client_name = "office_detection_1"
mqtt_pub_topic = "cameras/office/webcam"
mqtt_ctl_topic = "cameras/office/webcam"
camera_number = -1     # Linux: /dev/video0 is our number 0. See '$ v4l2-ctl --all'
camera_width = 400 #320
camera_height = 400 #200
camera_fps = 15
camera_warmup = 2.5
luxlevel = 0.6

enable = True
# below are settable parameters from mqtt messages to us
contour_limit = 900
last_out = False        # False => inactive
frame_skip = 5      # number of frames between checks. depends on source hw
inactive_secs = 2  # number of seconds to delay until inactive sent
timer_active = False
timer_thread = None
active_warmup = 0

# some debugging and stats variables
show_windows = True;		# -d on the command line
global luxcnt, luxsum
luxcnt = 1
luxsum = 0.0

def print_lux(msg):
  global luxcnt, luxsum
  tstr = datetime.datetime.now().strftime("%H:%M:%S")
  print (tstr, msg, luxsum/luxcnt)
  
def inactive_timer():
  global client, mqtt_pub_topic, last_out
  last_out = False
  client.publish(mqtt_pub_topic,"inactive")
  print_lux("inactive")
  return

def send_state(state):
  global last_out, inactive_secs, client, pub_topic, active_warmup
  global timer_active, timer_thread
  if state == True:
    if last_out:
      return
    else:
      # we may want several "frames" of "action" before we send the active
      active_warmup += 1
      if active_warmup > 3:
        client.publish(mqtt_pub_topic,"active")
        print_lux("active  ")
        last_out = True
        active_warmup = 0
  else:
    if not last_out:
      return
    else:
      # was active, going inactive in inactive_secs
      if timer_active:
        # new activity before timer fires, cancel it.
        timer_thread.cancel() 
        time.sleep(0.01)
      # start timer
      timer_thread = threading.Timer(inactive_secs, inactive_timer)
      timer_active = True
      timer_thread.start()

def lux_calc(frame):
    global luxcnt, luxsum, luxlevel
    frmgray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lux = np.mean(frmgray)
    dropped = False
    # check for lights out situation, low lux => less light
    if lux  < ((luxsum / luxcnt) * luxlevel):
      tstr = datetime.datetime.now().strftime("%H:%M:%S")
      print(tstr, lux, "trigging lights out, resetting from", luxsum / luxcnt)
      luxsum = lux
      luxcnt = 1
      dropped = True
    else:
      luxsum = luxsum + lux
      luxcnt = luxcnt + 1
    return dropped

def find_movement(debug):
    global frame1, frame2, frame_skip, contour_limit, lights_out
    drop = lux_calc(frame1)
    # if the light went out, don't try to detect motion
    if not drop:
      diff = cv2.absdiff(frame1, frame2)
      gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
      blur = cv2.GaussianBlur(gray, (5,5), 0)
      _, thresh = cv2.threshold(blur, 20, 255, cv2.THRESH_BINARY)
      dilated = cv2.dilate(thresh, None, iterations=3)
      contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
      motion = False
      for contour in contours:
          (x, y, w, h) = cv2.boundingRect(contour)
          
          if cv2.contourArea(contour) < contour_limit:
              continue
          motion = True
          send_state(motion)
          if debug:
            cv2.rectangle(frame1, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(frame1, "Status: {}".format('Movement'), (10, 20), cv2.FONT_HERSHEY_SIMPLEX,
                        1, (0, 0, 255), 3)
  
      if debug:
        cv2.drawContours(frame1, contours, -1, (0, 255, 0), 2)
        cv2.imshow("feed", frame1)
      if not motion:
        send_state(False)
    frame1 = frame2
    time.sleep((1.0/30.0) * frame_skip)
    ret, frame2 = cap.read()
    return motion
    
def on_message(client, userdata, message):
    global enable
    payload = str(message.payload.decode("utf-8"))
    print("message received ", payload)
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
  # For Linux: /dev/video0 is device 0 (pi builtin eg: or first usb webcam)
  time.sleep(camera_warmup)
  client = mqtt.Client(mqtt_client_name, mqtt_port)
  client.connect(mqtt_server)
  client.subscribe(mqtt_ctl_topic)
  client.on_message = on_message
  client.loop_start()
  return cap


def cleanup(do_windows):
  global client, cap, luxcnt, luxsum
  if show_windows:
    cv2.destroyAllWindows()
  cap.release()
  client.loop_stop()
  if show_windows:
    print("average of lux mean ", luxsum/luxcnt)
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
