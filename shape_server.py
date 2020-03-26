# PyRpc Server for ML shape detection on Tcp port 4433
# This will be started by systemd.
import cv2
import numpy as np
import imutils
import sys
import json
import argparse
import warnings
from datetime import datetime
import time,threading, sched
import rpyc
from lib.Algo import Algo

debug = False;

class Settings:

  def __init__(self, logw):
    self.log = logw
    self.use_ml = None


class MyService(rpyc.Service):  
  
  def on_connect(self, conn):
    self.client_ip, _ = conn._config['endpoints'][1]
   
  def exposed_detectors(self, name, debug, threshold, imagestr):
    global ml_dict
    # convert image arg to cv2/numpy image. it's jpeg
    nparr = np.fromstring(imagestr, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    mlobj = ml_dict.get(name, None)
    #print("request from", self.client_ip)
    stm = time.time()
    sptm = time.process_time()
    if mlobj:
      if name == 'Cnn_Face':
        result, n = mlobj.face_detect(frame, threshold, debug)
      elif name == 'Cnn_Shapes':
        result, n = mlobj.shapes_detect(frame, threshold, debug)
      elif name.startswith('Haar'):
        result, n = mlobj.haar_detect(frame, threshold, debug)
      elif name == 'Hog_People':
        result, n = mlobj.hog_detect(frame, threshold, debug)
      eptm = time.process_time()
      etm = time.time()
      pt = eptm - sptm
      ct = etm - stm
      elstr = "%3.2f%%" % ((pt / ct) * 100)
      print(self.client_ip, name, result, round(pt, 4), round(ct, 4), elstr)
      return (result, n)
    else:
      print("Call for unknown algo:", name)
      return (False, "unknown algo: " % name)

    
# process args - port number, 
ap = argparse.ArgumentParser()
ap.add_argument("-p", "--port", action='store', type=int, default='4433',
  nargs='?', help="server port number, 4433 is default")
args = vars(ap.parse_args())

# create a bunch of Objects for each.
settings = Settings(print)
ml_dict = {}
ml_dict['Cnn_Face'] = Algo('Cnn_Face', settings)
ml_dict['Cnn_Shapes'] = Algo('Cnn_Shapes', settings)
ml_dict['Haar_Face'] = Algo('Haar_Face', settings)
ml_dict['Haar_FullBody'] = Algo('Haar_FullBody', settings)
ml_dict['Haar_UpperBody'] = Algo('Haar_UpperBody', settings)
ml_dict['Hog_People'] = Algo('Hog_People', settings)

from rpyc.utils.server import ThreadedServer
t = ThreadedServer(MyService, port = args['port'])
t.start()
