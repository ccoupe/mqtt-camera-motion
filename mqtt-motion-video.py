#!/usr/bin/env python3
import os
import cv2
import numpy as np
import paho.mqtt.client as mqtt
from imutils.video import VideoStream
import imutils
import sys
import json
import argparse
import warnings
from datetime import datetime
import time,threading, sched
from threading import Lock
import socket
import csv
import atexit
import logging
import logging.handlers

from lib.Constants import State, Event
from lib.Settings import Settings
from lib.Homie_MQTT import Homie_MQTT
from lib.Algo import Algo
import ctypes
    
import rpyc
import websocket  # websocket-client
import base64

class LuxLogFilter(logging.Filter):
  def filter(self, record):
    global curlux, luxsum, luxcnt
    record.lux = "%3d" % curlux
    record.sum = "%5.3f" % (luxsum/luxcnt)
    return True
  


# globals - yes it is a ton of globals
settings = None
hmqtt = None
video_dev = None
detector_thread = None
sm_lock = Lock()             # state machine lock - only one thread at a time
motion_cnt = 0
no_motion_cnt = 0
timer_thread = None
snapshot_thread = None
active_ticks = 0
frattr1 = False
frattr2 = False
#off_hack = False
detect_flag = False   # signal complex detection/recog pass
shape_proxy = None

# some debugging and stats variables
debug_level = 0          # From command line
show_windows = False		# -d on the command line for True
luxcnt = 1
luxsum = 0.0
curlux = 0
use_syslog = False
have_cuda = False
use_three_arg = False

def create_cap_dir():
  global cap_prefix
  dp = os.path.join(cap_prefix,
              datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))
  try: 
    os.makedirs(dp)
  except OSError as e:
    if e.errno != errno.EEXIST:
      raise  # This was NOT a "directory exist" error..
  return dp
      
# State machines deal with events causing a movement to another state
# the movement or transition may invoke a procedure. Most of the ending
# state of a transition is predeteremined. A few have to calculate to
# return the next state. 


# The table method is difficult to program. Unrolled, it's large. Sigh!
# Both are difficult to debug
# We need to lock other threads out while the current thread proceeds
# to the end of the function
def next_state(nevent):
  global cur_state, hmqtt, settings, motion_cnt, timer_thread, logwriter
  global detector_thread, sm_lock, applog
  global cap_frames, cap_dir, cap_prefix
  sm_lock.acquire()
  lc = cur_state
  next_st = None
  if nevent == Event.motion:
    if cur_state == State.disabled:
      next_st = State.disabled                # stay
    elif cur_state == State.motion_wait:
      if cap_prefix != None:
        # new dir, signal read_cap()
        cap_dir = create_cap_dir()
        cap_frames = 1
      if settings.two_step:
        hmqtt.send_active(True)
        motion_cnt = settings.active_hold      
        next_st = State.motion_hold              # trans_proc2
      else:
        tf = check_presence()
        if tf:
          hmqtt.send_active(True)
          motion_cnt = settings.active_hold      
          next_st = State.motion_hold
        else:
          # nothing there, keep waiting
          next_st = State.motion_wait
    elif cur_state == State.motion_hold:
      next_st = State.motion_hold
      motion_cnt = settings.active_hold     # trans_proc3
    elif cur_state == State.check_wait:
      next_st = State.check_wait            # stay
    elif cur_state == State.restart:
      next_st = cur_state                   # stay
    else:
      raise Exception('State Machine', "bad state %d for event %d " % (cur_state, nevent))
  elif nevent == Event.no_motion:
    if cur_state == State.disabled:
      next_st = State.disabled                 # stay
    elif cur_state == State.motion_wait:
      next_st = State.motion_wait               # stay. inactive with no_motion_events
    elif cur_state == State.motion_hold:
      next_st = State.motion_hold           # stay. inactive: timer will send inactive
    elif cur_state == State.check_wait:
      next_st = State.check_wait            # stay
    elif cur_state == State.restart:
      next_st = cur_state                   # stay
    else:
      raise Exception('State Machine', ("bad state %d for event %d " % cur_state, nevent))
  elif nevent == Event.tick:
    if cur_state == State.disabled:
      next_st = State.disabled                  # stay
    elif cur_state == State.motion_wait:
      next_st = State.motion_wait               # stay
    elif cur_state == State.motion_hold:
      # Much to do                           # trans_proc4
      motion_cnt -= 1
      if motion_cnt <= 0:
        # time to go inactive 
        if cap_prefix != None:
          cap_frames = 0
        if settings.two_step:
          hmqtt.send_active(False)
          next_st = State.motion_wait
          motion_cnt = settings.active_hold
        else:
          tf = check_presence()
          if not tf:
            hmqtt.send_active(False)
            next_st = State.motion_wait
            motion_cnt = settings.active_hold      
          else:
            # still someone there, keep holding
            next_st = State.motion_hold
      else:
        next_st = State.motion_hold
    elif cur_state == State.check_wait:
      next_st = State.check_wait              # stay, for now. TODO:
    elif cur_state == State.restart:
      next_st = cur_state
    else:
      raise Exception('State Machine', ("bad state %d for event %d " % cur_state, nevent))
    # alway restart the timer, it's expired.
    timer_thread = threading.Timer(settings.tick_len, one_sec_event)
    timer_thread.start()
  elif nevent == Event.check:
    if cur_state == State.disabled:
      next_st = State.disabled
    else:
      next_st = State.check_wait
      # there is a chance for a network call, or it takes a while to run
      # locally so it's done in a new thread. Beware of the locking or
      # race condition 
      detector_thread = threading.Thread(target=detector_general, args=())
      ##detector_thread.daemon = True
      detector_thread.start()
  elif nevent == Event.det_true:
    if cur_state == State.disabled:
      next_st = State.disabled
    else:
      motion_cnt = settings.active_hold
      hmqtt.send_detect(True)
      next_st = State.motion_hold
  elif nevent == Event.det_false:
    if cur_state == State.disabled:
      next_st = State.disabled
    else:
      hmqtt.send_detect(False)
      motion_cnt = settings.active_hold
      next_st = State.motion_wait
  elif nevent == Event.start:
    if cur_state == State.disabled:
      next_st = State.disabled
    elif cur_state == State.motion_wait:
      next_st = cur_state
    elif cur_state == State.motion_hold:
      next_st = cur_state
    elif cur_state == State.check_wait:
      next_st = cur_state
    elif cur_state == State.restart:
      next_st = cur_state                   
    else:
      raise Exception('State Machine', ("bad state %d for event %d " % cur_state, nevent))
    # TODO - recursive call may not be unwound. Could crash in a week or two
    # of hubitat driver button pushes. Only used for testing so It's OK.
    cur_state = State.motion_wait
    next_state(Event.lights_out)
    next_st = State.motion_wait
  elif nevent == Event.stop:
    if cur_state == State.disabled:
      next_st = State.disabled
    elif cur_state == State.motion_wait:
      next_st = cur_state
    elif cur_state == State.motion_hold:
      next_st = cur_state
    elif cur_state == State.check_wait:
      next_st = cur_state
    elif cur_state == State.restart:
      next_st = cur_state                   
    else:
      raise Exception('State Machine', ("bad state %d for event %d " % cur_state, nevent))
    hmqtt.send_active(False)
    next_st = State.disabled
  elif nevent == Event.lights_out:
    # Happens when external process (like hubitat - turns of the switch
    # associated with our motion sensor. Done in Motion Lighting App.
    applog.debug(str(Event.lights_out))
    if cur_state == State.disabled:
      next_st = State.disabled
    elif cur_state == State.motion_wait:
      camera_spin(5)                     
      next_st = State.restart
    elif cur_state == State.motion_hold: 
      # TODO: sending the inactive could trigger a check coming back to us
      # it's probably a futile thing to do in lights out, but ....
      hmqtt.send_active(False)
      camera_spin(5)
      next_st = State.restart         
    elif cur_state == State.check_wait:
      next_st = State.restart
    elif cur_state == State.restart:
      next_st = State.restart                   # stay
    else:
      raise Exception('State Machine', ("bad state %d for event %d " % cur_state, nevent))
  else:
    raise Exception('State Machine', 'unknown event')
  
  if next_st != cur_state and logwriter:
    (dt, micro) = datetime.now().strftime('%H:%M:%S.%f').split('.')
    dt = "%s.%03d" % (dt, int(micro) / 1000)
    logwriter.writerow([dt, round(curlux), round(luxsum/luxcnt), nevent, lc, next_st])
  
  # Finally ;-)
  cur_state = next_st
  if cur_state == None:
    applog.error("event %s old %s next %s", str(nevent), str(lc), str(cur_state))
    exit()
  sm_lock.release()
  return cur_state
    
def one_sec_event():
  next_state(Event.tick)   
  return

# ---------  Timer functions -----------  

def reset_timer():
  global timer_thread
  timer_thread = threading.Timer(settings.tick_len, one_sec_event)
  timer_thread.start()
  
def lux_timer():
  global settings, curlux, lux_thread
  #settings.client.publish(settings.mqtt_pub_topic, msg)
  applog.info("lux=%d", curlux)
  lux_thread = threading.Timer(settings.lux_secs, lux_timer)
  lux_thread.start()
  
def snapshot_timer():
  global snapshot_thread, frame1, cur_state, settings
  #log("Snapshot taken")
  nimg = frame1 
  if cur_state == State.motion_hold:
    status = cv2.imwrite(f'/var/www/camera/{settings.homie_device}.jpg',nimg) 
  else:
    gray = cv2.cvtColor(nimg, cv2.COLOR_BGR2GRAY)
    status = cv2.imwrite(f'/var/www/camera/{settings.homie_device}.jpg',gray) 
  snapshot_thread = threading.Timer(60, snapshot_timer)
  snapshot_thread.start()
      
def lux_calc(frame):
    global luxcnt, luxsum, settings, curlux
    frmgray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    curlux = np.mean(frmgray)
    ok = True
    # check for lights out situation
    if curlux  < ((luxsum / luxcnt) * settings.lux_level):
      applog.info("LUX STEP: %d", curlux)
      luxsum = curlux
      luxcnt = 1
      ok = False
    else:
      luxsum = luxsum + curlux
      luxcnt = luxcnt + 1
    return ok

def detector_general():
  result = check_presence()
  if result:
    next_state(Event.det_true)
  else:
    next_state(Event.det_false)

def image_serialize(image):
  _, jpg = cv2.imencode('.jpg',image)
  bfr = jpg.tostring()
  #log("jpg_toString: %d" % len(bfr))
  return bfr
  

# we grab a frame and pass it to the correct algo. Which may be an rpyc proxy
# these are not called continously - only after movement is detected and
# then if a deeper check is requested. Then let the state machine deal with the result. 
# we check for the proxy state (!= None)

def ws_check_presence(algo, frame):
  # this one uses a websocket to the server, gets a json return
  # Returns T/F
  global settings, applog
  ws = websocket.WebSocket()
  for ip in settings.ml_server_ip:
    try:
      uri = f'ws://{ip}:{settings.ml_port}/Cnn_Shapes'
      print('connecting', uri)
      ws.connect(uri)
      _, jpg = cv2.imencode('.jpg',frame)
      bfr = base64.b64encode(jpg)
      ws.send(bfr)
      reply = ws.recv()
      ws.close()
      js = json.loads(reply)
      return js['value']
    except ConnectionRefusedError:
      applog.warning(f'Trying backup ip for {ip}:{settings.ml_port}')
      applog.warning(f'{ip} is {socket.gethostbyname(ip)}')
      continue
  # here if all servers are unresponsive
  return False
  
def check_presence():
  global settings, ml_dict, frame1, show_windows, backup_ml, applog, have_cuda
  result = False
  time.sleep(0.25)       # one quarter second delay, get a new frame
  read_local_resize()
  mlobj = None
  st = datetime.now()
  if settings.use_ml == 'websocket':
    result = ws_check_presence(settings.ml_algo, frame1)
  else:
    try:
      mlobj = ml_dict.get(settings.ml_algo, None)
      if mlobj is None:
        applog.info(f'Setting up rpc for {settings.ml_server_ip[0]}:{settings.ml_port} {settings.ml_algo}')
        mlobj = Algo(settings.ml_algo, 
              settings.use_ml == 'remote', 
              settings.ml_server_ip[0], 
              settings.ml_port, 
              settings.log,
              have_cuda)
        ml_dict[settings.ml_algo] = mlobj
      if settings.use_ml == 'remote':
        result, n = mlobj.proxy.root.detectors(settings.ml_algo, False, settings.confidence, image_serialize(frame1))
      else:
        result, n = mlobj.proxy(settings.ml_algo, show_windows, settings.confidence, frame1)
    except (ConnectionRefusedError, EOFError):
      applog.warning('Failing over to backup')
      mlobj = backup_ml.get(settings.ml_algo, None)
      if mlobj is None:
        applog.info(f'Setting up rpc for {settings.ml_server_ip[1]}:{settings.ml_port} {settings.ml_algo}')
        mlobj = Algo(settings.ml_algo,
                  True, 
                  settings.ml_server_ip[1], 
                  settings.ml_port, 
                  settings.log,
                  have_cuda)
        backup_ml[settings.ml_algo] = mlobj
      result, n = mlobj.proxy.root.detectors(settings.ml_algo, False, settings.confidence, image_serialize(frame1))
  et = datetime.now()
  el = et - st
  applog.info(f'elapsed: {el.total_seconds()}')
  return result
  
# --------- adrian_1 movement detection ----------
# Adrian @ pyimagesearch.com wrote/publicized most of this. 
def adrian_1_init():
  global frame1, frame2, frattr1, frattr2, cur_state, dimcap, read_cam
  frame1 = read_cam(dimcap)
  frattr1 = lux_calc(frame1)
  frame2 = read_cam(dimcap)
  frattr2 = lux_calc(frame2)
  cur_state = State.motion_wait

def adrian_1_movement(debug):
    global frame1, frame2, frattr1, frattr2, use_three_arg
    global settings, dimcap, hmqtt, shape_proxy, cur_state, read_cam
    #global applog
    #applog.info(f'movement?')
    motion = Event.no_motion
    if frattr1 and frattr2:
      diff = cv2.absdiff(frame1, frame2)
      gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
      blur = cv2.GaussianBlur(gray, (5,5), 0)
      _, thresh = cv2.threshold(blur, 20, 255, cv2.THRESH_BINARY)
      dilated = cv2.dilate(thresh, None, iterations=3)
      if use_three_arg:
        _,contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
      else:
        contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
      
      for contour in contours:
          #(x, y, w, h) = cv2.boundingRect(contour)
          
          if cv2.contourArea(contour) < settings.contour_limit:
              continue
          motion = Event.motion
          next_state(motion)
          if debug:
            cv2.rectangle(frame1, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(frame1, "Status: {}".format('Movement'), (10, 20), cv2.FONT_HERSHEY_SIMPLEX,
                        1, (0, 0, 255), 3)
      '''
      if debug:
        cv2.drawContours(frame1, contours, -1, (0, 255, 0), 2)
        cv2.imshow("Adrian_1", frame1)
      '''
      if motion == Event.no_motion:
        next_state(Event.no_motion)
    frame1 = frame2
    frattr1 = frattr2
    time.sleep((1.0/30.0) * settings.frame_skip)

    frame2 = read_cam(dimcap)
    frattr2 = lux_calc(frame2)   
    return motion == Event.motion

# ----- intel's movement algo
def intel_init():
    applog.debug("intel_init")
    
def distMap(frame1, frame2):
    """outputs pythagorean distance between two frames"""
    frame1_32 = np.float32(frame1)
    frame2_32 = np.float32(frame2)
    diff32 = frame1_32 - frame2_32
    norm32 = np.sqrt(diff32[:,:,0]**2 + diff32[:,:,1]**2 + diff32[:,:,2]**2)/np.sqrt(255**2 + 255**2 + 255**2)
    dist = np.uint8(norm32*255)
    return dist

def intel_movement(debug, read_cam):
  global settings, frame1, frame2, cur_state
  if debug:
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.namedWindow('frame')
    cv2.namedWindow('dist')
    
  frame1 = read_cam()
  lux_calc(frame1)
  frame2 = read_cam()
  lux_calc(frame2)
  
  while(True):
    if cur_state == State.restart:
      return True
    frame3 = read_cam()
    lux_calc(frame3)
    rows, cols, _ = np.shape(frame3)    
    if debug:
      cv2.imshow('dist', frame3)
    dist = distMap(frame1, frame3)

    frame1 = frame2
    frame2 = frame3

    # apply Gaussian smoothing
    mod = cv2.GaussianBlur(dist, (9,9), 0)

    # apply thresholding
    _, thresh = cv2.threshold(mod, 100, 255, 0)

    # calculate st dev test
    _, stDev = cv2.meanStdDev(mod)
    if debug:
      cv2.imshow('dist', mod)
      cv2.putText(frame2, "Standard Deviation - {}".format(round(stDev[0][0],0)), (70, 70), font, 1, (255, 0, 255), 1, cv2.LINE_AA)

    if stDev > settings.mv_threshold:
      if cur_state != State.motion_hold:
        next_state(Event.motion)
    else:
      if cur_state != State.motion_wait:
        next_state(Event.no_motion)
      
    if debug:
      cv2.imshow('frame', frame2)
      if cv2.waitKey(1) & 0xFF == 27:
          break
    time.sleep((1.0/30.0) * settings.frame_skip)
  return False
  

def cleanup():
  global client, video_dev, luxcnt, luxsum, timer_thread, show_windows
  if logwriter:
    csvfile.close()
  if show_windows:
    cv2.destroyAllWindows()
  hmqtt.client.loop_stop()
  applog.info("average of lux mean ", luxsum/luxcnt)
  timer_thread.cancel()
  return

def init_timers(settings):
  # For Linux: /dev/video0 is device 0 (pi builtin eg: or first usb webcam)
  time.sleep(settings.camera_warmup)
  timer_thread = threading.Timer(settings.tick_len, one_sec_event)
  timer_thread.start()
  lux_thread = threading.Timer(settings.lux_secs, lux_timer)
  lux_thread.start()
  snapshot_thread = threading.Timer(60, snapshot_timer)
  snapshot_thread.start()

# ----------- Capture Camera functions ----

def capture_read_cam(dim):
  global video_dev, settings
  global cap_frames, cap_dir, cap_prefix
  global applog
  cnt = 0
  ret = False
  frame = None
  frame_n = None
  while cnt < 120:
    ret, frame = video_dev.read()
    if ret == True and np.shape(frame) != ():
      frame_n = cv2.resize(frame, dim)
      break
    elif ret == False:
      print('restart stream')
      video_dev.release()
      video_dev = cv2.VideoCapture(settings.camera_number)
      cnt = 0
    cnt += 1
  if cnt >= 120:
    print("Crashing soon")
  return frame_n
  
  
def capture_read_local_resize():
  global video_dev, dimcap
  return capture_read_cam(dimcap)
  
def capture_remote_cam(width):
  global video_dev
  #log("remote_cam callback called width: %d" % width)
  ret, fr = video_dev.read()
  fr = cv2.resize(fr, (width, width))
  _, jpg = cv2.imencode('.jpg',fr)
  bfr = jpg.tostring()
  #print(type(fr), type(jpg), len(jpg), len(bfr))
  return bfr
  
# read frames and discard for 'sec' seconds
# note: even the pi0 can do 30fps if we don't process them
def capture_camera_spin(sec):
  global video_dev, applog
  applog.debug("begin spin")
  for n in range(sec * 30):
    video_dev.read()
  applog.debug("end spin")

# Capture camera frame and write to a file, notify requester
# Since we are (probably) run as root, we can write anywhere.
def capture_camera_capture_to_file(jsonstr):
  global video_dev, applog, hmqtt
  args = json.loads(jsonstr)
  #applog.debug("begin capture on demand")
  ret, fr = video_dev.read()
  # TODO what to do if ret is not good? 
  cv2.imwrite(args['path'], fr)
  hmqtt.send_capture(args['reply'])
  applog.debug("Capture to %s reply %s" % (args['path'], args['reply']))
  
# ----------- Streaming Camera functions ----
def stream_read_cam(dim):
  global video_dev
  global cap_frames, cap_dir, cap_prefix
  ret, frame = video_dev.read()
  if ret == True and np.shape(frame) != ():
    frame_n = cv2.resize(frame, dim)
  else:
    applog.info('no frame read, crash ahead')
  frame_n = cv2.resize(frame, dim)
  return frame_n
  
def stream_read_local_resize():
  global video_dev, dimcap
  return stream_read_cam(dimcap)
  
def stream_remote_cam(width):
  global video_dev
  #log("remote_cam callback called width: %d" % width)
  ret, fr = video_dev.read()
  fr = cv2.resize(fr, (width, width))
  _, jpg = cv2.imencode('.jpg',fr)
  bfr = jpg.tostring()
  #print(type(fr), type(jpg), len(jpg), len(bfr))
  return bfr
  
# read frames and discard for 'sec' seconds
# note: even the pi0 can do 30fps if we don't process them
def stream_camera_spin(sec):
  global video_dev, applog
  applog.debug("begin spin")
  for n in range(sec * 30):
    video_dev.read()
  applog.debug("end spin")

# Capture camera frame and write to a file, notify requester
# Since we are (probably) running as root, we can write anywhere.
def stream_camera_capture_to_file(jsonstr):
  global video_dev, applog, hmqtt
  args = json.loads(jsonstr)
  #applog.debug("begin capture on demand")
  ret, fr = video_dev.read()
  cv2.imwrite(args['path'], fr)
  hmqtt.send_capture(args['reply'])
  applog.debug("Capture to %s reply %s" % (args['path'], args['reply']))
  
#
# imstream is adrian's multithreaded capure in imutils
#
def imstream_read_cam(dim):
  global video_dev
  global cap_frames, cap_dir, cap_prefix
  frame = video_dev.read()
  if frame is None:
    applog.info('no frame read, crash ahead')
  frame_n = cv2.resize(frame, dim)
  return frame_n

def imstream_read_local_resize():
  global video_dev, dimcap
  return imstream_read_cam(dimcap)
  
def imstream_remote_cam(width):
  global video_dev
  #log("remote_cam callback called width: %d" % width)
  fr = video_dev.read()
  fr = cv2.resize(fr, (width, width))
  _, jpg = cv2.imencode('.jpg',fr)
  bfr = jpg.tostring()
  #print(type(fr), type(jpg), len(jpg), len(bfr))
  return bfr
  
# read frames and discard for 'sec' seconds
# note: even the pi0 can do 30fps if we don't process them
def imstream_camera_spin(sec):
  global video_dev, applog
  applog.debug("begin spin")
  for n in range(sec * 30):
    video_dev.read()
  applog.debug("end spin")

# Capture camera frame and write to a file, notify requester
# Since we are (probably) running as root, we can write anywhere.
def imstream_camera_capture_to_file(jsonstr):
  global video_dev, applog, hmqtt
  args = json.loads(jsonstr)
  #applog.debug("begin capture on demand")
  ret, fr = video_dev.read()
  cv2.imwrite(args['path'], fr)
  hmqtt.send_capture(args['reply'])
  applog.debug("Capture to %s reply %s" % (args['path'], args['reply']))

def build_ml_dict(rmt, ip, port, log):
  global have_cuda
  t_dict = {}
  t_dict['Cnn_Face'] = Algo('Cnn_Face', rmt, ip, port, log, have_cuda)
  t_dict['Cnn_Shapes'] = Algo('Cnn_Shapes', rmt, ip, port, log, have_cuda)
  t_dict['Haar_Face'] = Algo('Haar_Face', rmt, ip, port, log, have_cuda)
  t_dict['Haar_FullBody'] = Algo('Haar_FullBody', rmt, ip, port, log, have_cuda)
  t_dict['Haar_UpperBody'] = Algo('Haar_UpperBody', rmt, ip, port, log, have_cuda)
  t_dict['Hog_People'] = Algo('Hog_People', rmt, ip, port, log, have_cuda)
  return t_dict
  
logwriter = None
csvfile = None
ml_dict = {}
backup_ml = {}
video_dev = None
cap_prefix = None
cap_frames = 0

def nvidia_cam_rtsp(uri, width, height, latency):
    gst_str = ("rtspsrc location={} latency={} ! rtph264depay ! h264parse ! omxh264dec ! "
               "nvvidconv ! video/x-raw, width=(int){}, height=(int){}, format=(string)BGRx ! "
               "videoconvert ! appsink").format(uri, latency, width, height)
    return cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)
      
'''
# CJC - I haven't tested these but they are a decent starting place
# note that nvvidconv is nvidia only so beware.
def open_cam_usb(dev, width, height):
    # We want to set width and height here, otherwise we could just do:
    #     return cv2.VideoCapture(dev)
    gst_str = ("v4l2src device=/dev/video{} ! "
               "video/x-raw, width=(int){}, height=(int){}, format=(string)RGB ! "
               "videoconvert ! appsink").format(dev, width, height)
    return cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)

def open_cam_onboard(width, height):
    # On versions of L4T previous to L4T 28.1, flip-method=2
    # Use Jetson onboard camera
    gst_str = ("nvcamerasrc ! "
               "video/x-raw(memory:NVMM), width=(int)2592, height=(int)1458, format=(string)I420, framerate=(fraction)30/1 ! "
               "nvvidconv ! video/x-raw, width=(int){}, height=(int){}, format=(string)BGRx ! "
               "videoconvert ! appsink").format(width, height)
    return cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)
'''
# following cuda check does not work (Mint 19.1, GeForce 1030)
def is_cuda_cv(): 
    global have_cuda
    try:
        count = cv2.cuda.getCudaEnabledDeviceCount()
        if count > 0:
            have_cuda = True
        else:
            have_cuda = False
    except:
        have_cuda = False
    return have_cuda

def check_cuda():
  CUDA_SUCCESS = 0
  libnames = ('libcuda.so', 'libcuda.dylib', 'cuda.dll')
  for libname in libnames:
    try:
      cuda = ctypes.CDLL(libname)
    except OSError:
      continue
    else:
      break
  else:
    return False
    
  nGpus = ctypes.c_int()
  name = b' ' * 100
  cc_major = ctypes.c_int()
  cc_minor = ctypes.c_int()
  cores = ctypes.c_int()
  threads_per_core = ctypes.c_int()
  clockrate = ctypes.c_int()
  freeMem = ctypes.c_size_t()
  totalMem = ctypes.c_size_t()

  result = ctypes.c_int()
  device = ctypes.c_int()
  context = ctypes.c_void_p()
  error_str = ctypes.c_char_p()
  result = cuda.cuInit(0)
  if result != CUDA_SUCCESS:
      cuda.cuGetErrorString(result, ctypes.byref(error_str))
      print("cuInit failed with error code %d: %s" % (result, error_str.value.decode()))
      return False
  result = cuda.cuDeviceGetCount(ctypes.byref(nGpus))
  if result != CUDA_SUCCESS:
      cuda.cuGetErrorString(result, ctypes.byref(error_str))
      print("cuDeviceGetCount failed with error code %d: %s" % (result, error_str.value.decode()))
      return False
  print("Found %d device(s)." % nGpus.value)
  
  return nGpus.value > 0

def main(args=None):
  global logwriter, csvfile, ml_dict, applog, cur_state, dimcap, video_dev
  global settings, hmqtt, show_windows, read_cam, read_local_resize, remote_cam
  global camera_spin, camera_capture_to_file
  global cap_prefix, backup_ml, have_cuda,  use_three_arg
  # process cmdline arguments
  ap = argparse.ArgumentParser()
  loglevels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
  ap.add_argument("-c", "--conf", required=True, type=str,
    help="path and name of the json configuration file")
  ap.add_argument("-d", "--debug", action='store', type=bool, default=False,
    nargs='?', help="show rectangles - no remote ml")
  ap.add_argument("-s", "--syslog", action = 'store_true',
    default=False, help="use syslog")
  ap.add_argument("-a", "--algorithm", required=False, type=str, default=None,
    help="detection algorithm override")
  ap.add_argument("-m", "--movement", required=False, type=str,
    help="movement algorithm override")
  ap.add_argument("-e", "--events", required=False, action = "store_true", default=False,
    help="log events to events.csv file")
  ap.add_argument("-r", "--remote", required=False, action = "store_true", default=False,
    help="log events to file")
  ap.add_argument("-p", "--port", action='store', type=int, default='4466',
    nargs='?', help="server port number, 4466 is default")
  ap.add_argument('-l', '--log', default='DEBUG', choices=loglevels)
  #ap.add_argument("-f", "--capture", required=False, type=str,
  #  help="path and name for image captures")
  ap.add_argument('-3', "--three_arg", action = 'store_true',
    default=False, help="findContours has 3 return values")
  
  args = vars(ap.parse_args())
  
  # frame capture setup
  #if args['capture']:
  #  cap_prefix = args['capture']
  #else:
  #  cap_prefix = None
  
  # logging setup
  applog = logging.getLogger('mqttcamera')
  #applog.setLevel(args['log'])
  if args['syslog']:
    applog.setLevel(logging.DEBUG)
    handler = logging.handlers.SysLogHandler(address = '/dev/log')
    # formatter for syslog (no date/time or appname. Just  msg, lux, luxavg
    formatter = logging.Formatter('%(name)s-%(levelname)-5s: %(message)-30s %(lux)s %(sum)s')
    handler.setFormatter(formatter)
    f = LuxLogFilter()
    applog.addFilter(f)
    applog.addHandler(handler)
  else:
    logging.basicConfig(level=logging.DEBUG,datefmt="%H:%M:%S",format='%(asctime)s %(message)-40s %(lux)s %(sum)s')
    f = LuxLogFilter()
    applog.addFilter(f)
    
  show_windows = False;
  
  # state_machine log file
  logwriter = None
  csvfile = None
  if args['events']:
    csvfile = open('events.csv', 'w', newline='')
    logwriter = csv.writer(csvfile, delimiter=',', quotechar='|')
    print("logging...")
  
  # Lets spin it up.  
  settings = Settings(args["conf"], 
                      "/var/local/etc/mqtt-camera.json",
                      applog,
                      next_state)
  
  # cmd line args override settings file.
  if args['algorithm']:
    settings.ml_algo = args['algorithm']
    applog.debug("cmd line algo override: %s", settings.ml_algo)
  if args['movement']:
    settings.mv_algo = args['movement']
    applog.debug("cmd line movement override: %s", settings.mv_algo)
  if args['remote']:
    settings.use_ml = 'remote'
  '''
  if args['port']:
    print('override port')
    settings.ml_port = args['port']
  '''
  if args['debug']:
    show_windows = True
    settings.use_ml = 'local'
  if args['three_arg']:
    # yet another damn global for a bug
    use_three_arg = True
    
  hmqtt = Homie_MQTT(settings, 
                    settings.get_active_hold,
                    settings.set_active_hold)
  settings.display()
  settings.log = applog
  if logwriter:
    logwriter.writerow([settings.settings_serialize])
    
    
  # setup ml_dict. Dealing with the backup is a bit hackish.
  # Rpc proxy's are setup the first time they are needed. 
  have_cuda = is_cuda_cv()
  applog.info(f"Have CUDA: {check_cuda()}")
  if settings.use_ml == 'local':
   applog.info(f"Will use CUDA: {have_cuda}")
   ml_dict = build_ml_dict(False, None, None, applog)
   
  cur_state = State.motion_wait
  dimcap = (settings.camera_width, settings.camera_height)
  # Almost Done with setup. Maybe.
  
  if settings.camera_type == 'capture':
    video_dev = cv2.VideoCapture(settings.camera_number)
    read_cam = capture_read_cam
    read_local_resize = capture_read_local_resize
    remote_cam = capture_remote_cam
    camera_spin = capture_camera_spin
    camera_capture_to_file = capture_camera_capture_to_file
  elif settings.camera_type == 'nvidia-rtsp':
    video_dev = nvidia_cam_rtsp(settings.camera_number, settings.camera_width,
			settings.camera_height, 0)
    read_cam = stream_read_cam
    read_local_resize = stream_read_local_resize
    remote_cam = stream_remote_cam
    camera_spin = stream_camera_spin
    camera_capture_to_file = stream_camera_capture_to_file
  elif settings.camera_type == 'ffmpeg-rtsp':
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transpo rt;udp"
    video_dev = cv2.VideoCapture(settings.camera_number,cv2.CAP_FFMPEG)
    read_cam = stream_read_cam
    read_local_resize = stream_read_local_resize
    remote_cam = stream_remote_cam
    camera_spin = stream_camera_spin
    camera_capture_to_file = stream_camera_capture_to_file
  elif settings.camera_type == 'gst':
    video_dev = cv2.VideoCapture(settings.camera_prep,cv2.CAP_GSTREAMER)
    read_cam = stream_read_cam
    read_local_resize = stream_read_local_resize
    remote_cam = stream_remote_cam
    camera_spin = stream_camera_spin
    camera_capture_to_file = stream_camera_capture_to_file
  elif settings.camera_type == 'stream':
    video_dev = VideoStream(src=settings.camera_number, resolution = dimcap).start()
    read_cam = imstream_read_cam
    read_local_resize = imstream_read_local_resize
    remote_cam = imstream_remote_cam
    camera_spin = imstream_camera_spin
    camera_capture_to_file = imstream_camera_capture_to_file
  else:
    log('bad camera_type in settings file')
    exit()

  # a cross coupling hack? 
  hmqtt.capture = camera_capture_to_file

  init_timers(settings)
  atexit.register(cleanup)
  # now we pick between movement detectors and start the choosen one
  if settings.mv_algo == 'adrian_1':
    while True:
      adrian_1_init()
      while True:
        adrian_1_movement(show_windows)
        if cur_state == State.restart:
          #log("restarting adrian_1 loop")
          break
      if show_windows and cv2.waitKey(40) == 27:
        break
  elif settings.mv_algo == 'intel':
    while True:
      intel_init()
      while True:
        intel_movement(show_windows, read_local_resize)
        if cur_state == State.restart:
          log("restarting intel loop")
          breakl
  else:
    print("No Movement Algorithm chosen")
  cleanup()

if __name__ == '__main__':
  sys.exit(main())

   
