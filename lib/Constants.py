import enum 

class State(enum.Enum): 
  disabled = 0
  motion_wait = 1
  motion_hold = 2
  check_wait = 3
  restart = 4

class Event(enum.Enum):
  motion = 0
  no_motion = 1
  tick = 2
  check = 3
  det_true = 4
  det_false = 5
  start = 6
  stop = 7
  lights_out = 8

'''
# Table driven state machine enums - must be indices.
# States:
DISABLED_ST = 0
MOTION_WAIT_ST = 1
MOTION_HOLD_ST = 2
CHECK_WAIT_ST = 3
# Events
MOTION_EV = 0
NO_MOTION_EV = 1
TICK_EV = 2
CHECK_EV = 3
DET_TRUE_EV = 4
DET_FALSE_EV = 5
START_EV = 6
STOP_EV = 7
LIGHTS_OUT_EV = 8

# Transition procs/functions - arguments may not be used or useful. 
# in a Real multiple process system there might be a mutex for the
# global cur_state
  
def trans_proc1(cur_st, new_st):
  global  hmqtt, motion_cnt, settings
  # mqtt send 'inactive', 
  hmqtt.send_active(False)
  motion_cnt = settings.active_hold
  
def trans_proc2(cur_st, new_st):
  global  hmqtt, settings, motion_cnt
  # mqtt send 'active'
  hmqtt.send_active(True)
  # set motion_cnt
  motion_cnt = settings.active_hold
  
  
def trans_proc3(cur_st, new_st):
  global motion_cnt, settings
  # reset mot_hold_counter
  motion_cnt = settings.active_hold

# this is a function! 
def trans_proc4(cur_st, new_st):
  global  hmqtt, settings, motion_cnt
  # decrement motion_hold counter
  motion_cnt -= 1
 # if <=0 then send inactive,  return MOTION_WAIT_ST
  if motion_cnt <= 0:
    hmqtt.send_active(False)
    motion_cnt = settings.active_hold
    return MOTION_WAIT_ST
  # else return MOTION_HOLD_ST (stay in calling state)
  else:
    return MOTION_HOLD_ST

# may have nothing to do.
def trans_proc5(cur_st, new_st):
  # start synchronous [remote] ML/AI detector
  # ticks may arrive while waiting
  raise Exception('State Machine', 'trans_proc5')
  
# Tick event in Check Wait - this is a function
def trans_proc6(cur_st, new_st):
  # if timeout, move to MOTION_WAIT_ST
  raise Exception('State Machine', 'trans_proc6')
  
def trans_proc7(cur_st, new_st):
  # mqtt send 'present'
  global hmqtt
  hmqtt.send_detect(True)
  
def trans_proc8(cur_st, new_st):
  # mqtt send 'notpresent'
  global hmqtt
  hmqtt.send_detect(False)
  
def trans_proc9(cur_st, new_st):
  # delay 1 sec. Do not process camera frames while waiting
  time.sleep(1)
  
def trans_proc10(cur_st, new_st):
  # delay 1 sec. Do not process camera frames while waiting
  # mqtt send 'inactive'
  global hmqtt
  time.sleep(1)
  hmqtt_send_active(False)
  
def trans_proc11(cur_st, new_st):
  reset_timer()

# Alloc space for state table
st_table = [ [0] * 4 for i in range(9) ]

# row per event . The column value is a [2 element list]
# columns are cur_state = [DISABLED_ST, MOTION_WAIT_ST, MOTION_HOLD_ST, CHECK_WAIT_ST]
st_table[MOTION_EV] = [
    [DISABLED_ST, None],
    [MOTION_HOLD_ST, trans_proc2],
    [MOTION_HOLD_ST, trans_proc3],
    [CHECK_WAIT_ST, None]
  ]
  
st_table[NO_MOTION_EV] = [
    [DISABLED_ST, None],
    [MOTION_WAIT_ST, None],
    [MOTION_HOLD_ST, trans_proc1],
    [CHECK_WAIT_ST, None]
  ]
  
st_table[TICK_EV] = [
    [DISABLED_ST, None],
    [MOTION_WAIT_ST, None],
    [None, trans_proc4],
    [None, trans_proc6],
  ]
  
st_table[CHECK_EV] = [
    [DISABLED_ST, None],
    [CHECK_WAIT_ST, trans_proc5],
    [CHECK_WAIT_ST, trans_proc5],
    [CHECK_WAIT_ST, None]
  ]

st_table[DET_TRUE_EV] = [
    [DISABLED_ST, None],
    [MOTION_HOLD_ST, trans_proc7],
    [MOTION_HOLD_ST, trans_proc7],
    [MOTION_HOLD_ST, trans_proc7]
  ]
  
st_table[DET_FALSE_EV] = [
    [DISABLED_ST, None],
    [MOTION_WAIT_ST, trans_proc8],
    [MOTION_WAIT_ST, trans_proc8],
    [MOTION_WAIT_ST, trans_proc8]
  ]

st_table[START_EV] = [
    [MOTION_WAIT_ST, trans_proc1],
    [MOTION_WAIT_ST, trans_proc1],
    [MOTION_WAIT_ST, trans_proc1],
    [MOTION_WAIT_ST, trans_proc1]
  ]
  
st_table[STOP_EV] = [
    [DISABLED_ST, None],
    [DISABLED_ST, trans_proc1],
    [DISABLED_ST, trans_proc1],
    [DISABLED_ST, trans_proc8]
  ]
  
st_table[LIGHTS_OUT_EV] = [
    [DISABLED_ST, None],
    [MOTION_WAIT_ST, trans_proc9],
    [MOTION_WAIT_ST, trans_proc10],
    [MOTION_WAIT_ST, trans_proc8]
  ]

cur_state = MOTION_WAIT_ST

def old_next_state(nevent):
  global cur_state
  lc = cur_state
  row = st_table[nevent]
  cell = row[cur_state]
  ns = cell[0]
  proc = cell[1]
  if ns == None and proc == None:
    raise Exception('State Machine', 'no state and no proc')
  if ns == None:
    cur_state = proc(cur_state, ns)
  else:
    if proc:
      proc(cur_state, ns)
    cur_state = ns
  #print("event", nevent, "old", lc, "next", cur_state)

'''

'''
## old state machine 
MOTION = 1
NO_MOTION = 0
FIRED = 2
# states
WAITING = 0
ACTIVE_ACC = 1
INACT_ACC = 2

# state machine internal variables
state = WAITING
# --------- state machine -------------
def old_state_machine(signal):
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
          hmqtt.send_active(False)
          state = WAITING
      timer_thread = threading.Timer(settings.tick_len, one_sec_timer)
      timer_thread.start()
    else:
      print("Unknown signal in state ACTIVE_ACC")
  else:
    print("Unknow State")
'''
