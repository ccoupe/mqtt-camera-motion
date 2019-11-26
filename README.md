## Video motion detection for Linux and MQTT. 
  Uses python, USB webcams or Raspberry pi cameras.

### Summary
This program reads from a USB wecam or Raspberry's camera and when it detects
movement it will send 'active' or 'inactive' to a MQTT topic.  There
is a matching Hubitat driver.

### Why
I was playing around with motion sensors like the Samsung SmartThings and the
Phillips Hue sensor. They work fine if you want to turn on the light when you
move into a room and then the lights turn off after some delay from the sensor and 
from Hubitat settings. If you move around in the room then the lights stay on.

What happens if you plant yourself in front of a computer or comfy chair and barely move? 
Correct, the lights go out after a while because you aren't moving enough.

This a problem for me. Granted, it's not a world hunger sized problem but maybe 
I could fix this one, for me First, I bought some components and build my own PIR 
sensor (AM312) and an ESP32. That wasn't any better. I tried a microwave sensor
(RCWL-0516) which is funny device. Pretty sensitive to small movements, most times.
It also sees movement through walls which defeats the point of having a sensor
in a room, for that room. Then I built a combo device, when the PIR sees movement
it sends an 'active' to MQTT and any RCWL triggers extend the time until my device
sends and 'inactive'.  This works pretty well and I learned about ESP32 and Arduino and 
PlatformIO and refreshed my opinion of C++ (I'm not a fan). I also learned enough groovy
to modify some Hubitat drivers to talk to MQTT, my way.

I looked at a few other things until I ran across some YouTube videos showing ESP32 cameras
doing facial recognition. Of course I found videos of systems doing object detection and
tracking (althogh not with puny ESP32). So I ordered a couple of ESP32 camera's. I
broke one right of the bat and the other one gets a software error in the driver, for
no reason that make sense to me.  Then I thought, MotionEye claims to do motion detection
so I got a camera for my raspberry pi3 (it's also my MQTT server) and after some fun I did 
get a video motion detector working for Hubitat. But, it too has limitations. Accuracy depends
on the camera distance, lens and frame size and it gets chatty - it's not been a load on Hubitat with
all that traffic from the mqtt server but it is inefficient and it consumes half the raspberry cpu and 
that bugs me. I know my economics are backwards, but it's a hobby!

Still, I bought a Pi Zero Wireless and a camera chip for it, installed motioneye (NOT MotionEyeOS) and
that works pretty well in my office. A pi zero doesn't have the processing power to do decent frame rates
if you wanted a fancy motioneye security camera. For this application however, I could call it quits
and be happy.

Of course, quitting is not an real option until I try to do even better. I also have
a USB Webcam (Logitech 615) on my 'big' ubuntu box. Lot's of processing power for development.
All the cool kids use Python (I'm Rubyist). More importantly all the sample good in python is very
close to what I need. 
