# Video motion detection for Linux and MQTT. 
  Uses python, USB webcams or Raspberry pi cameras.

## Purpose
This program reads from a USB wecam or Raspberry's camera and when it detects
movement it will send 'active' or 'inactive' to a MQTT topic.  There
is a matching Hubitat driver you'll want to use.

It also reports a 'lux' level to MQTT. Do not confuse this with other 'lux's. Generally
speaking a low number means less light. This program attempt to detect step changes
in lux so that turning the lights off in the room with the camera does NOT cause and
'active' message to be sent. Attempts to do that. You may have to do that in the Hubitat rule.

There are a large number of setting you can tweak. Some are from the configuation
file and some via the Hubitat driver and MQTT. Most of these are for performance improvment

## License
There isn't one for my code. 

## Support
The best way to contact me about problems, suggestions, wishes and fixes
is to file an [https://github.com/ccoupe/mqtt-camera-motion/issues](issue at the github repo.)
Membership is free. If it crashed, a backtrace dump is
really, really useful as are error messages from the Hubitat log if that
is where the problem shows up.

To contribute fixes, a git hub pull request is the best method for anything longer 
that three lines of code.

## Installation

```
git clone https://github.com/ccoupe/mqtt-camera-motion.git
cd mqtt-camera-motion
```

Note: You can not share the camera with this program. When it's running you
can't use MotionEye (moditiond) or Cheese or Skype, for example. You might be
might be able to use the microphone on a USb Webcam. Maybe.

### Find your Video device
```
ls -ld /dev/vidoe*
```
For more detail
```
v4l2-ctl --all
```
#### python3 installation
With any luck at all, you'll have python3 installed - check by
`python --version` or `python3 --version`

You need some python packages.
```
sudo pip install numpy
sudo pip install paho-mqtt
```
#### opencv installation
Opencv provides the libraries for image manipulation. I use version 4.1.2 which
is a real pain to install from source, especially on a Raspberry. 

For Raspberry Pi's (https://solarianprogrammer.com/2019/09/17/install-opencv-raspberry-pi-raspbian-cpp-python-development/)[(follow these instructions]

Ubutu linux has opencv 3 in its repo but we want 4 (4.1.2+) so it's build from source.

INSERT configuration here

### Manual Configuration.
Try it manually to see how well it works for you and to get your configuation
workable before doing a system install. Create a json file. For example:

INSERT pi.json

We get to the parameters later but the important one at this point is the
camera_number. Enter 0 to use /dev/video0, 1 for /dev/video1, etc. 
Sometimes, -1 works better than 0. Sometimes.

### System Install

We use the systemd facility. 

Create a directory for the configuration file. I'll use /usr/local/etc/mqtt-camera
Copy your working json file.
```
sudo mkdir -p /usr/local/etc/mqtt-camera
sudo cp pi.json /usr/local/etc/mqtt-camera
```

Create a directory for the python code. I'll use /usr/local/bin

```
sudo cp mqtt-vision.py /usr/local/lib/mqtt-camera.py
```
You need to modify mqttcamera.service so systemd can manage the camera for booting and
other system events. For example:

```
[Unit]
Description=MQTT Camera

[Service]
ExecStart=python3 /usr/local/lib/mqtt-vision.py -c /usr/local/etc/mqtt-camera/pi.conf
Restart=on-abort

[Install]
WantedBy=multi-user.target
```
Then you copy the service file to systemd's location and start the server.
```
sudo cp mqttcamera.service /etc/system/systemd
sudo systemctl enable mqttcamera
sudo systemctl start mqttcamera
```
That should get it running now and for every reboot. If you want to disable it
to fix it or use the camera for another application `sudo systemctl disable mqttcamera`
mqttcamera will log to /var/log/mqttcamera. The word `backtrace` in the log would indicate
a failure that needs fixing, ASAP. 

### Install an MQTT server.
If you don't have one, `mosquitto` is easy to install.  It's almost mandatory to assign
a fixed IP address for the system running your MQTT server using your router configuration
software.

You really want a fixed IP address and you want a machine that will reboot on powerfail. A pi3 is
enough to run MQTT and the camera if you want.

TODO: Instuctions here.

### Hubitat driver install

TODO:

### Algorithm Performance

### Computer Performance

## Backstory
I was playing around with motion sensors like the Samsung SmartThings and the
Phillips Hue sensor. They work fine if you want to turn on the light when you
move into a room and then the lights turn off after some delay from the sensor and 
from Hubitat settings. If you move around in the room then the lights stay on.

What happens if you plant yourself in front of a computer or comfy chair and barely move? 
Correct, the lights go out after a while because you aren't moving enough.

This a problem for me. Granted, it's not a solve world hunger problem but maybe 
I could fix this one, for me. First, I bought some components and build my own PIR 
sensor (AM312) and an ESP32. That wasn't any better. I tried a microwave sensor
(RCWL-0516) which is a funny device. Pretty sensitive to small movements, most times.
It also sees movement through walls which defeats the point of having a sensor
in a room for that room. Then I built a combo device, when the PIR sees movement
it sends an 'active' to MQTT and any RCWL triggersignals  extend the time until my device
sends an 'inactive'.  This works pretty well and I learned about ESP32 and Arduino and 
PlatformIO and refreshed my opinion of C++ (I'm not a fan). I also learned enough groovy
to modify some Hubitat drivers to talk to MQTT.

I looked at a few other things until I ran across some YouTube videos showing ESP32 cameras
doing facial recognition. Of course I found videos of systems doing object detection and
tracking (althogh not with a puny ESP32). So I ordered a couple of ESP32 camera's. I
broke one right of the bat (fat findered the connector) and the other one gets a software error
in the driver, for
no reason that make sense to me.  Then I thought, MotionEye claims to do motion detection
so I got a camera for my raspberry pi3 (it's also my MQTT server) and after some fun I did 
get a video motion detector working for Hubitat. But, it too has limitations. Accuracy depends
on the camera distance, lens and frame size and it gets chatty - it's not been a load on Hubitat with
all that traffic from the mqtt server but it is inefficient and it consumes half the raspberry cpu and 
that bugs me. I know my economics are backwards, but it's a hobby!

Still, I bought a Pi Zero Wireless and a camera chip for it, installed motioneye (NOT MotionEyeOS) and
that works pretty well in my office. A pi zero doesn't have the processing power to do decent frame rates
if you wanted a fancy motioneye security camera. For this application, higher frame rates are not needed and 
small frame sizes like 640 x 480 are what I needed.
I could call it quits and be happy.

Of course, quitting is not an real option until I try to do even better. I also have
a USB Webcam (Logitech 615) on my 'big' ubuntu box. Lot's of processing power for development.
All the cool kids use Python (I'm Rubyist). More importantly all the opencv samples are in python and very
close to what I need. 

However examples do not make 'App's and in particular they do not make fancy weird device drivers. 
That's what this project does.

