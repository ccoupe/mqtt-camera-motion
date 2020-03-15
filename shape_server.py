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

debug = False;

class MyService(rpyc.Service):
  def exposed_shapes_detect(self, max_frames, g_confidence, remote_cam):
    global dlnet, CLASSES, COLORS, debug
    n = 0
    fc = 0
    print("shape check")
    while fc < max_frames and n == 0:
      # grab the frame using the network callback - it returns a jpg.
      enfr = remote_cam(300)
      nparr = np.fromstring(enfr, np.uint8)
      frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
      
      (h, w) = frame.shape[:2]
      blob = cv2.dnn.blobFromImage(frame, 0.007843, (300, 300), 127.5)
    
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
      fc = fc + 1
    return True if n > 0 else False
    
# process args - port number, 
ap = argparse.ArgumentParser()
ap.add_argument("-p", "--port", action='store', type=int, default='4433',
  nargs='?', help="server port number, 4433 is default")
args = vars(ap.parse_args())


# initialize the list of class labels MobileNet SSD was trained to
# detect, then generate a set of bounding box colors for each class
CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat",
  "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
  "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
  "sofa", "train", "tvmonitor"]
COLORS = np.random.uniform(0, 255, size=(len(CLASSES), 3))
dlnet = cv2.dnn.readNetFromCaffe("shapes/MobileNetSSD_deploy.prototxt.txt",
  "shapes/MobileNetSSD_deploy.caffemodel")

from rpyc.utils.server import ThreadedServer
t = ThreadedServer(MyService, port = args['port'])
t.start()
