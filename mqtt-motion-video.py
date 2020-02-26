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

from lib.Settings import Settings
from lib.Homie_MQTT import Homie_MQTT
    

# globals
settings = None
hmqtt = None
# state machine enums (cheap enums)
# signals:
MOTION = 1
NO_MOTION = 0
FIRED = 2
# states
WAITING = 0
ACTIVE_ACC = 1
INACT_ACC = 2

# state machine internal variables
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
 
# ---------  Timer functions -----------
def one_sec_timer():
  global off_hack
  if off_hack:
    off_hack = False;     # clear hack for lights off
  state_machine(FIRED)    # async? is it thread safe? maybe?
  return
  
def lux_timer():
  global settings, curlux, lux_thread
  msg = "lux=%d" %(curlux)
  #settings.client.publish(settings.mqtt_pub_topic, msg)
  log(msg, 2)
  lux_thread = threading.Timer(settings.lux_secs, lux_timer)
  lux_thread.start()
  
def snapshot_timer():
  global snapshot_thread, frame1, state
  #dim = (320, 240)
  #nimg = cv2.resize(frame1, dim, interpolation = cv2.INTER_AREA)
  nimg = frame1 
  if state == ACTIVE_ACC:
    status = cv2.imwrite('/var/www/camera/snapshot.png',nimg) 
  else:
    gray = cv2.cvtColor(nimg, cv2.COLOR_BGR2GRAY)
    status = cv2.imwrite('/var/www/camera/snapshot.png',gray) 
  snapshot_thread = threading.Timer(60, snapshot_timer)
  snapshot_thread.start()
  
# --------- state machine -------------
def state_machine(signal):
  global motion_cnt, no_motion_cnt, active_ticks, lux_cnt
  global settings, hmtqq, timer_thread, state, off_hack
  if state == WAITING:
    if signal == MOTION:
      # hack ahead. Don't send active if lux_sum & cnt have been reset
      # attempt to ignore false positives when lights go out
      if not off_hack:
        #settings.send_mqtt("active")
        hmqtt.send_active(True)
        state = ACTIVE_ACC
      else:
        state = ACTIVE_ACC
    elif signal == NO_MOTION:
      state = WAITING
    elif signal == FIRED:
      timer_thread = threading.Timer(settings.tick_len, one_sec_timer)
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
          active_ticks = settings.active_hold
          state = ACTIVE_ACC
          log("retrigger %02.2f" % (motion_cnt / (motion_cnt + no_motion_cnt)),2)
          motion_cnt = no_motion_cnt = 0
          state = ACTIVE_ACC
        else:
          #send_mqtt("inactive")
          hmqtt.send_active(False)
          state = WAITING
      timer_thread = threading.Timer(settings.tick_len, one_sec_timer)
      timer_thread.start()
    else:
      print("Unknown signal in state ACTIVE_ACC")
  else:
    print("Unknow State")
    
def lux_calc(frame):
    global luxcnt, luxsum, settings, curlux
    frmgray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    curlux = np.mean(frmgray)
    ok = True
    # check for lights out situation
    if curlux  < ((luxsum / luxcnt) * settings.lux_level):
      log("LUX STEP: %d" % curlux, 2)
      luxsum = curlux
      luxcnt = 1
      ok = False
    else:
      luxsum = luxsum + curlux
      luxcnt = luxcnt + 1
    return ok

def find_movement(debug):
    global frame1, frame2, frattr1, frattr2
    global settings, dimcap
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
          
          if cv2.contourArea(contour) < settings.contour_limit:
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
    time.sleep((1.0/30.0) * settings.frame_skip)
    #ret, frame2 = cap.read()
    frame2 = read_cam(cap, dimcap)
    frattr2 = lux_calc(frame2)   
    return motion == MOTION

def cleanup(do_windows):
  global client, cap, luxcnt, luxsum, timer_thread
  if show_windows:
    cv2.destroyAllWindows()
  cap.release()
  settings.client.loop_stop()
  if show_windows:
    print("average of lux mean ", luxsum/luxcnt)
  timer_thread.cancel()
  return

def init_timers(settings):
  # For Linux: /dev/video0 is device 0 (pi builtin eg: or first usb webcam)
  time.sleep(settings.camera_warmup)
  timer_thread = threading.Timer(settings.tick_len, one_sec_timer)
  timer_thread.start()
  lux_thread = threading.Timer(settings.lux_secs, lux_timer)
  lux_thread.start()
  snapshot_thread = threading.Timer(60, snapshot_timer)
  snapshot_thread.start()


def read_cam(dev,dim):
  ret, frame = dev.read()
  frame_n = cv2.resize(frame, dim)
  return frame_n
  
# process cmdline arguments
ap = argparse.ArgumentParser()
ap.add_argument("-c", "--conf", required=True, type=str,
	help="path and name of the json configuration file")
ap.add_argument("-d", "--debug", action='store', type=int, default='3',
  nargs='?', help="debug level, default is 3")
ap.add_argument("-s", "--system", action = 'store', nargs='?',
  default=False, help="use syslog")
args = vars(ap.parse_args())
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

# Lets spin it up.  
settings = Settings(args["conf"], 
                    "/var/local/etc/mqtt-camera.json",
                    log)
hmqtt = Homie_MQTT(settings, 
                  settings.get_active_hold,
                  settings.set_active_hold)
settings.print()

# Done with setup. 

if settings.rtsp_uri:
  cap = cv2.VideoCapture(settings.rtsp_uri)
else:
  cap = cv2.VideoCapture(settings.camera_number)
  
if not  cap.isOpened():
  print("FAILED to open camera")
  exit()
#ret = cap.set(3, settings.camera_width)
#ret = cap.set(4, settings.camera_height)
#ret = cap.set(5, camera_fps)
init_timers(settings)
dimcap = (settings.camera_width, settings.camera_height)
#ret, frame1 = cap.read()
frame1 = read_cam(cap, dimcap)
frattr1 = lux_calc(frame1)
#ret, frame2 = cap.read()
frame2 = read_cam(cap, dimcap)
frattr2 = lux_calc(frame2)

while 1:
  motion = find_movement(show_windows)
  #cv2.imshow("feed", frame1)
  if show_windows and cv2.waitKey(40) == 27:
    break
  #frame1 = read_cam(cap, dimcap)
cleanup(show_windows)
  
