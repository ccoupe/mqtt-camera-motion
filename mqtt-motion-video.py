#!/usr/bin/env python3
import cv2
import numpy as np
import paho.mqtt.client as mqtt
import imutils
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
detect_flag = False   # signal complex detection/recog pass
#fc_frame_cnt = 60
g_confidence = 0.2

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
    logmsg = "%-14.14s%-40.40s%3d %- 5.2f" % (dt, msg, curlux, luxsum/luxcnt)
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
  global snapshot_thread, frame1, state, settings
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
  global settings, hmtqq, timer_thread, state, off_hack, detect_flag
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
    
def face_detect(image, debug):
  global dlnet, settings
  n = 0
  fc = 0
  #log("face check")
  while fc < settings.face_frames and n == 0:
    (h, w) = image.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(image, (300, 300)), 1.0,
      (300, 300), (104.0, 177.0, 123.0))
    # pass the blob through the network and obtain the detections and
    # predictions
    dlnet.setInput(blob)
    detections = dlnet.forward()
    n = 0
    for i in range(0, detections.shape[2]):
      confidence = detections[0, 0, i, 2]
      if confidence > 0.5:
        n = n + 1
    if n > 0:
      break   # one is enough
    image = read_cam(cap, dimcap)
    fc = fc + 1
		
  log('Faces: %d' % n);
  return n > 0

def shapes_detect(image, debug):
  global dlnet, settings, CLASSES, COLORS, cap, dimcap, g_confidence
  n = 0
  fc = 0
  log("shape check")
  while fc < settings.face_frames and n == 0:
    # grab the frame from the threaded video stream and resize it
    # to have a maximum width of 400 pixels
    frame = imutils.resize(image, width=400)
  
    # grab the frame dimensions and convert it to a blob
    (h, w) = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)),
      0.007843, (300, 300), 127.5)
  
    # pass the blob through the network and obtain the detections and
    # predictions
    dlnet.setInput(blob)
    detections = dlnet.forward()
  
    # loop over the detections
    for i in np.arange(0, detections.shape[2]):
      # extract the confidence (i.e., probability) associated with
      # the prediction
      confidence = detections[0, 0, i, 2]
  
      # filter out weak detections by ensuring the `confidence` is
      # greater than the minimum confidence
      if confidence > g_confidence:
        # extract the index of the class label from the
        # `detections`, then compute the (x, y)-coordinates of
        # the bounding box for the object
        idx = int(detections[0, 0, i, 1])
        if idx == 15:
          n += 1
          break
        if debug:
          box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
          (startX, startY, endX, endY) = box.astype("int")
    
          # draw the prediction on the frame
          label = "{}: {:.2f}%".format(CLASSES[idx],
            confidence * 100)
          cv2.rectangle(frame, (startX, startY), (endX, endY),
            COLORS[idx], 2)
          y = startY - 15 if startY - 15 > 15 else startY + 15
          cv2.putText(frame, label, (startX, y),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLORS[idx], 2)
  
    # show the output frame
    if debug:
      cv2.imshow("Frame", frame)
      key = cv2.waitKey(1) & 0xFF
      # if the `q` key was pressed, break from the loop
      if key == ord("q"):
        break
    if n > 0:
      break
    image = read_cam(cap, dimcap)
    fc = fc + 1
  return True if n > 0 else False
      
def find_movement(debug):
    global frame1, frame2, frattr1, frattr2
    global settings, dimcap, hmqtt
    # detection is requested asynchronously via mqtt message sent to us
    # watch out for loops - it's an expensive computation
    # TODO? - should be done in state_machine where we can cancel?
    if hmqtt.detect_flag:
      rslt = False
      if settings.algo == 'face':
        rslt = face_detect(frame1, debug)
      elif settings.algo == 'shapes':
        rslt = shapes_detect(frame1, debug)
      if rslt:
        st = MOTION
      else:
        st = NO_MOTION
      state_machine(st)
      hmqtt.detect_flag = False
      hmqtt.send_detect(rslt)
      return st
      
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

    frame2 = read_cam(cap, dimcap)
    frattr2 = lux_calc(frame2)   
    return motion == MOTION

def cleanup(do_windows):
  global client, cap, luxcnt, luxsum, timer_thread
  if show_windows:
    cv2.destroyAllWindows()
  cap.release()
  hmqtt.client.loop_stop()
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
  # what to do if ret is not good? 
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
ap.add_argument("-a", "--algorithm", required=False, type=str, default=None,
  help="detection algorithm override")
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
if args['algorithm']:
  settings.algo = args['algorithm']
  print("cmd line selects algo", settings.algo)
  
hmqtt = Homie_MQTT(settings, 
                  settings.get_active_hold,
                  settings.set_active_hold)
settings.print()
if settings.algo == 'face':
  dlnet = cv2.dnn.readNetFromCaffe("face/deploy.prototxt.txt", "face/res10_300x300_ssd_iter_140000.caffemodel")
elif settings.algo == 'shapes':
  # initialize the list of class labels MobileNet SSD was trained to
  # detect, then generate a set of bounding box colors for each class
  CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
    "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
    "sofa", "train", "tvmonitor"]
  COLORS = np.random.uniform(0, 255, size=(len(CLASSES), 3))
  dlnet = cv2.dnn.readNetFromCaffe("shapes/MobileNetSSD_deploy.prototxt.txt",
    "shapes/MobileNetSSD_deploy.caffemodel")
    
g_confidence = settings.confidence
# Done with setup. 

if settings.rtsp_uri:
  cap = cv2.VideoCapture(settings.rtsp_uri)
else:
  cap = cv2.VideoCapture(settings.camera_number)
  
if not  cap.isOpened():
  print("FAILED to open camera")
  exit()

init_timers(settings)
dimcap = (settings.camera_width, settings.camera_height)
frame1 = read_cam(cap, dimcap)
frattr1 = lux_calc(frame1)
frame2 = read_cam(cap, dimcap)
frattr2 = lux_calc(frame2)

while 1:
  motion = find_movement(show_windows)
  if show_windows and cv2.waitKey(40) == 27:
    break
cleanup(show_windows)
  
