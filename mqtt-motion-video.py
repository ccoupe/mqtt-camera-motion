#!/usr/bin/env python3
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

from lib.Constants import State, Event
from lib.Settings import Settings
from lib.Homie_MQTT import Homie_MQTT
from lib.Algo import Algo
    
import rpyc

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
  sm_lock.acquire()
  lc = cur_state
  next_st = None
  if nevent == Event.motion:
    if cur_state == State.disabled:
      next_st = State.disabled                # stay
    elif cur_state == State.motion_wait:
      hmqtt.send_active(True)
      motion_cnt = settings.active_hold      
      next_st = State.motion_hold              # trans_proc2
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
        hmqtt.send_active(False)
        next_st = State.motion_wait
        motion_cnt = settings.active_hold
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
'''  
# TODO: won't need this after everything is using python logging.
def log(msg, level=2):
  global luxcnt, luxsum, curlux, debug_level, use_syslog, logwriter, applog
  if applog:
    applog.info("%-40.40s%3d %- 5.2f", msg, curlux, luxsum/luxcnt)
    if logwriter:
      (dt, micro) = datetime.now().strftime('%H:%M:%S.%f').split('.')
      dt = "%s.%03d" % (dt, int(micro) / 1000)
      logwriter.writerow([dt, round(curlux,2), round(luxsum/luxcnt,2), msg])
  else:
    if level > debug_level:
      return
    if use_syslog:
      logmsg = "%-20.20s%3d %- 5.2f" % (msg, curlux, luxsum/luxcnt)
    else:
      (dt, micro) = datetime.now().strftime('%H:%M:%S.%f').split('.')
      dt = "%s.%03d" % (dt, int(micro) / 1000)
      logmsg = "%-14.14s%-40.40s%3d %- 5.2f" % (dt, msg, curlux, luxsum/luxcnt)
    if logwriter:
      (dt, micro) = datetime.now().strftime('%H:%M:%S.%f').split('.')
      dt = "%s.%03d" % (dt, int(micro) / 1000)
      logwriter.writerow([dt, round(curlux,2), round(luxsum/luxcnt,2), msg])
    print(logmsg, flush=True)
''' 
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
    status = cv2.imwrite('/var/www/camera/snapshot.jpg',nimg) 
  else:
    gray = cv2.cvtColor(nimg, cv2.COLOR_BGR2GRAY)
    status = cv2.imwrite('/var/www/camera/snapshot.jpg',gray) 
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

# we grab a frame and pass it to the correct algo. Which may be an rpyc proxy
# these are not called continously - only after movement is detected and
# then if a deeper check is requested. Then call the state machine to
# deal with the result. 
def detector_general():
  global settings, ml_dict, frame1, show_windows
  result = False
  time.sleep(1)       # one second delay, get a new frame
  read_local_resize()
  mlobj = ml_dict[settings.ml_algo]
  if settings.use_ml == 'remote':
    result, n = mlobj.proxy.root.detectors(settings.ml_algo, False, settings.confidence, image_serialize(frame1))
  else:
    result, n = mlobj.proxy(settings.ml_algo, show_windows, settings.confidence, frame1)
  if result:
    next_state(Event.det_true)
  else:
    next_state(Event.det_false)

def image_serialize(image):
  _, jpg = cv2.imencode('.jpg',image)
  bfr = jpg.tostring()
  #log("jpg_toString: %d" % len(bfr))
  return bfr
  
# --------- adrian_1 movement detection ----------
# Adrian @ pyimagesearch.com wrote/publicized most of this. 
def adrian_1_init():
  global frame1, frame2, frattr1, frattr2, cur_state, dimcap
  frame1 = read_cam(dimcap)
  frattr1 = lux_calc(frame1)
  frame2 = read_cam(dimcap)
  frattr2 = lux_calc(frame2)
  cur_state = State.motion_wait

def adrian_1_movement(debug):
    global frame1, frame2, frattr1, frattr2
    global settings, dimcap, hmqtt, shape_proxy, cur_state
      
    motion = Event.no_motion
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
          motion = Event.motion
          next_state(motion)
          if debug:
            cv2.rectangle(frame1, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(frame1, "Status: {}".format('Movement'), (10, 20), cv2.FONT_HERSHEY_SIMPLEX,
                        1, (0, 0, 255), 3)
  
      if debug:
        cv2.drawContours(frame1, contours, -1, (0, 255, 0), 2)
        cv2.imshow("Adrian_1", frame1)
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


def read_cam(dim):
  global video_dev
  ret, frame = video_dev.read()
  # what to do if ret is not good? 
  frame_n = cv2.resize(frame, dim)
  return frame_n
 
def read_local_resize():
  global video_dev, dimcap
  return read_cam(dimcap)
  
def remote_cam(width):
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
def camera_spin(sec):
  global video_dev, applog
  applog.debug("begin spin")
  for n in range(sec * 30):
    video_dev.read()
  applog.debug("end spin")
  
def build_ml_dict(settings):
  ml_dict['Cnn_Face'] = Algo('Cnn_Face', settings)
  ml_dict['Cnn_Shapes'] = Algo('Cnn_Shapes', settings)
  ml_dict['Haar_Face'] = Algo('Haar_Face', settings)
  ml_dict['Haar_FullBody'] = Algo('Haar_FullBody', settings)
  ml_dict['Haar_UpperBody'] = Algo('Haar_UpperBody', settings)
  ml_dict['Hog_People'] = Algo('Hog_People', settings)
  return ml_dict
  
logwriter = None
csvfile = None
ml_dict = {}
video_dev = None

def main(args=None):
  global logwriter, csvfile, ml_dict, applog, cur_state, dimcap, video_dev
  global settings, hmqtt, show_windows
  # process cmdline arguments
  ap = argparse.ArgumentParser()
  loglevels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
  ap.add_argument("-c", "--conf", required=True, type=str,
    help="path and name of the json configuration file")
  ap.add_argument("-d", "--debug", action='store', type=int, default='3',
    nargs='?', help="debug level, default is 3")
  ap.add_argument("-s", "--system", action = 'store', nargs='?',
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
  args = vars(ap.parse_args())
  
  # logging setup
  logging.basicConfig(level=logging.DEBUG,format='%(asctime)s %(message)s')
  applog = logging.getLogger('mqttcamera')
  applog.setLevel(args['log'])
  # fix up debug levels
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
  if args['port']:
    settings.ml_port = args['port']
    
  hmqtt = Homie_MQTT(settings, 
                    settings.get_active_hold,
                    settings.set_active_hold)
  settings.print()
  settings.log = applog
  if logwriter:
    logwriter.writerow([settings.settings_serialize])
    
  # setup ml_dict
  ml_dict = build_ml_dict(settings)
  
  cur_state = State.motion_wait
  dimcap = (settings.camera_width, settings.camera_height)
  # Almost Done with setup. Maybe.
  
  if settings.rtsp_uri:
    video_dev = cv2.VideoCapture(settings.rtsp_uri)
  else:
    if settings.camera_number < 0:
      #video_dev = VideoStream(usePiCamera=True, resolution = dimcap).start()
      video_dev = cv2.VideoCapture(settings.camera_number)
    else:
      #video_dev = VideoStream(src=settings.camera_number, resolution = dimcap).start()
      video_dev = cv2.VideoCapture(settings.camera_number)
  
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

   
