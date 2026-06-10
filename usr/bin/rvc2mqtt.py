#!/usr/bin/env python3
import can

import argparse,array,json,os,queue,re,signal,threading,time
import ruamel.yaml as yaml

# Get the directory where the script is located for relative paths
script_dir = os.path.dirname(os.path.abspath(__file__))

# Global MQTT connection status
mqtt_connected = False


def signal_handler(signal, frame):
    global t
    print('')
    print('You pressed Ctrl+C!  Exiting...')
    print('')
    t.kill_received = True
    exit(0)

signal.signal(signal.SIGINT, signal_handler)

def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    if debug_level:
        print("MQTT Connected with code "+str(rc))
    if rc == 0:
        mqtt_connected = True
        client.subscribe([
            (mqttTopic + "/transmit/#", 0)
            ])
    else:
        mqtt_connected = False
        print(f"MQTT Connection failed with code {rc}")

def on_mqtt_disconnect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    mqtt_connected = False
    if debug_level:
        print(f"MQTT Disconnected with code {rc}")

def on_mqtt_subscribe(client, userdata, mid, reason_code_list, properties=None):
    if debug_level:
        print("MQTT Sub: "+str(mid))

def on_mqtt_message(client, userdata, msg):
    topic=msg.topic[13:]
    if debug_level:
        print("Send CAN ID: "+topic+" Data: "+msg.payload.decode('ascii'))
    #can_tx(devIds[dev],[ commands[msg.payload.decode('ascii')] ])

def mqtt_publish_with_retry(client, topic, payload, retain=False, max_retries=3):
    """Publish MQTT message, tolerating brief connection drops.

    Reconnection itself is left entirely to paho's network loop thread
    (started via loop_start(), with reconnect_delay_set() configuring its
    backoff). We must NOT call client.disconnect()/client.reconnect() from
    here: disconnect() marks the drop as intentional, which tells the loop
    thread to stop trying to reconnect, and racing a manual reconnect()
    against that thread can wedge the client in a permanently-disconnected
    state (observed after a broker restart -- required killing the container
    to recover). So if we're not connected, we just wait for mqtt_connected
    to flip back to True via the on_connect callback.
    """
    global mqtt_connected

    for attempt in range(max_retries):
        if mqtt_connected:
            try:
                result = client.publish(topic, payload, retain=retain)
                if result.rc == 0:
                    return True
                print(f"MQTT publish failed with code {result.rc}, attempt {attempt + 1}")
            except (BrokenPipeError, ConnectionResetError, OSError, TimeoutError) as e:
                print(f"MQTT publish error: {e}, attempt {attempt + 1}")
            except Exception as e:
                print(f"Unexpected MQTT error: {e}, attempt {attempt + 1}")
        else:
            print(f"MQTT not connected, attempt {attempt + 1} (waiting for automatic reconnect)")

        if attempt < max_retries - 1:
            time.sleep(1)  # give the loop thread a chance to (re)connect

    print(f"Failed to publish after {max_retries} attempts")
    return False

# can_tx(canid, canmsg)
#    canid = numeric CAN ID, not string
#    canmsg = Array of numeric values to transmit
#           - Alternately, a string of two position hex values can be accepted
#
# Examples:
#   can_tx( 0x19FEDB99, [0x02, 0xFF, 0xC8, 0x03, 0xFF, 0x00, 0xFF, 0xFF] )
#   can_tx( 0x19FEDB99, '02FFC803FF00FFFF' )
#
def can_tx(canid,canmsg):
    if isinstance(canmsg, str):
        tmp = canmsg
        canmsg = [int(tmp[x:x+2],16) for x in range( 0, len(tmp), 2 )]
    msg = can.Message(arbitration_id=canid, data=canmsg, extended_id=True)
    try:
        bus.send(msg)
        if debug_level>0:
            print("Message sent on {}".format(bus.channel_info))
    except can.CanError:
        print("CAN Send Failed")

class CANWatcher(threading.Thread):
    def __init__(self):
      threading.Thread.__init__(self)
      # A flag to notify the thread that it should finish up and exit
      self.kill_received = False
      self.last_message_time = time.time()
      self.total_messages_received = 0

    def run(self):
        print("CAN Watcher thread started")
        while not self.kill_received:
            try:
                # Add timeout to prevent hanging indefinitely
                message = bus.recv(timeout=5.0)  # 5 second timeout
                if message is not None:
                    self.total_messages_received += 1
                    self.last_message_time = time.time()
                    if debug_level > 0:
                        print(f"CAN Watcher: Received message #{self.total_messages_received}")
                    q.put(message)  # Put message into queue
                else:
                    if debug_level > 0:
                        print("CAN Watcher: No message received (timeout)")
            except Exception as e:
                print(f"CAN Watcher error: {e}")
                time.sleep(1)

def rvc_decode(mydgn, mydata):
    result = { 'dgn':mydgn, 'data':mydata, 'name':"UNKNOWN-"+mydgn }
    if mydgn not in spec:
        return result

    decoder = spec[mydgn]
    result['name'] = decoder['name']
    params = []
    try:
        params.extend(spec[decoder['alias']]['parameters'])
    except:
        pass

    try:
        params.extend(decoder['parameters'])
    except:
        pass

    param_count = 0
    for param in params:
        if parameterized_strings:
            param['name'] = parameterize_string(param['name'])

        try:
            mybytes = get_bytes(mydata,param['byte'])
            myvalue = int(mybytes,16) # Get the decimal value of the hex bytes
        except:
            # If you get here, it's because the params had more bytes than the data packet.
            # Thus, skip the rest of the processing
            continue

        try:
            myvalue = get_bits(myvalue,param['bit'])
            if param['type'][:4] == 'uint':
                myvalue = int(myvalue,2)
        except:
            pass

        try:
            myvalue = convert_unit(myvalue,param['unit'],param['type'])
        except:
            pass

        result[param['name']] = myvalue

        try:
            if param['unit'].lower() == 'deg c':
                if parameterized_strings:
                    result[param['name'] + '_f'] = tempC2F(myvalue)
                else:
                    result[param['name'] + ' F'] = tempC2F(myvalue)
        except:
            pass

        try:
            mydef = 'undefined'
            mydef = param['values'][int(myvalue)]
            # int(myvalue) is a hack because the spec yaml interprets binary bits
            # as integers instead of binary strings.
            if parameterized_strings:
                result[param['name'] + "_definition"] = mydef
            else:
                result[param['name'] + " definition"] = mydef
        except:
            pass

        param_count += 1

    if param_count == 0:
        result['DECODER PENDING'] = 1

    return result

def get_bytes(mybytes,byterange):
    try:
        bset=byterange.split('-')
        sub_bytes = "".join(mybytes[i:i+2] for i in range(int(bset[1])*2, (int(bset[0])-1)*2, -2))
    except:
        sub_bytes = mybytes[ byterange * 2 : ( byterange + 1 ) * 2 ]

    return sub_bytes

def get_bits(mydata,bitrange):
    mybits="{0:08b}".format(mydata)
    try:
        bset=bitrange.split('-')
        sub_bits = mybits[ 7 - int(bset[1]) : 8 - int(bset[0]) ]
    except:
        sub_bits = mybits[ 7 - bitrange : 8 - bitrange ]

    return sub_bits

# Convert a string to something easier to use as a JSON parameter by
# converting spaces and slashes to underscores, and removing parentheses.
# e.g.: "Manufacturer Code (LSB) in/out" => "manufacturer_code_lsb_in_out"
def parameterize_string(string):
    return string.translate(string.maketrans(' /', '__', '()')).lower()

def tempC2F(degc):
    return round( ( degc * 9 / 5 ) + 32, 1 )

def convert_unit(myvalue,myunit,mytype):
    new_value = myvalue
    mu = myunit.lower()
    if mu == 'pct':
        if myvalue != 255:
            new_value = myvalue / 2

    elif mu == 'deg c':
        new_value = 'n/a'
        if mytype == 'uint8' and myvalue != ( 1 << 8 ) - 1:
            new_value = myvalue - 40
        elif mytype == 'uint16' and myvalue != ( 1 << 16 ) - 1:
            new_value = round( ( myvalue * 0.03125 ) - 273, 2 )

    elif mu == 'v':
        new_value = 'n/a'
        if mytype == 'uint8' and myvalue != ( 1 << 8 ) - 1:
            new_value = myvalue
        elif mytype == 'uint16' and myvalue != ( 1 << 16 ) - 1:
            new_value = round( myvalue * 0.05, 2 )

    elif mu == 'a':
        new_value = 'n/a'
        if mytype == 'uint8':
            new_value = myvalue
        elif mytype == 'uint16' and myvalue != ( 1 << 16 ) - 1:
            new_value = round( ( myvalue * 0.05 ) - 1600 , 2)
        elif mytype == 'uint32' and myvalue != ( 1 << 32 ) - 1:
            new_value = round( ( myvalue * 0.001 ) - 2000000 , 3)

    elif mu == 'hz':
        if mytype == 'uint16' and myvalue != ( 1 << 16 ) - 1:
            new_value = round( myvalue / 128 , 2)

    elif mu == 'sec':
        if mytype == 'uint8' and myvalue > 240 and myvalue < 251:
            new_value = ( ( myvalue - 240 ) + 4 ) * 60
        elif mytype == 'uint16':
            new_value = myvalue * 2

    elif mu == 'bitmap':
        new_value = "{0:08b}".format(myvalue)

    return new_value

def main():
    global lasttime
    retain=False
    lasttime = 0
    if(mqttOut==2):
        retain=True
    
    if debug_level == 5:
        # Write to /dev/shm (tmpfs) to avoid wearing the SD card; data is lost on container restart.
        datafile = open("/dev/shm/rvc2mqtt_debug.txt", "w")
    elif debug_level == 4:
        try:
            datafile = open("datafile.txt", "r")
        except:
            print("Can't open datafile.txt")
            exit()

    def getLine():
        global lasttime
        if debug_level == 4:
            #all input comes just from a file
            line = datafile.readline()
            if not line:
                #hit eof now replay datafile for ever
                print('Seeking to beginning..............................................')
                print('...............................................................................................................................')
                datafile.seek(0,0)
                line = datafile.readline()
                lasttime = 0
            try:
                myresult = json.loads(line)
                curtime = float(myresult['timestamp'])
            except:
                datafile.close()
                print('Error in datafile format. Stopping')
                exit()
            if lasttime== 0:
                lasttime = curtime
            time.sleep(curtime - lasttime)
            lasttime = curtime
            if screenOut>0:
                print(json.dumps(myresult))

            if mqttOut:
                topic = mqttTopic + "/" + myresult['name']
                try:
                    topic += "/" + str(myresult['instance'])
                except:
                    pass
                mqtt_publish_with_retry(mqttc, topic, json.dumps(myresult), retain)
            return True
        
        if q.empty():  # Check if there is a message in queue
            return False

        message = q.get()
        if debug_level>0:
            print("Raw  msg ** {0}".format(message),flush=True)
            print("***{0:f} {1:X} ({2:X}) ***".format(message.timestamp, message.arbitration_id, message.dlc),end='',flush=True)

                

        try:
            canID = "{0:b}".format(message.arbitration_id)
            prio  = int(canID[0:3],2)
            dgn   = "{0:05X}".format(int(canID[4:21],2))
            srcAD = "{0:02X}".format(int(canID[24:],2))
        except Exception as e:
            if debug_level>0:
                print(f"Failed to parse {message}: {e}")
        else:
            if debug_level>0:
                print("DGN: {0:s}, Prio: {1:d}, srcAD: {2:s}, Data: {3:s}".format(
                    dgn,prio,srcAD,", ".join("{0:02X}".format(x) for x in message.data)))

            myresult=rvc_decode(dgn,"".join("{0:02X}".format(x) for x in message.data))
            myresult.update({"timestamp": str(message.timestamp)})
            if debug_level == 5:
                datafile.write(json.dumps(myresult))
                datafile.write("\n")

            if mqttOut:
                topic = mqttTopic + "/" + myresult['name']
                try:
                    topic += "/" + str(myresult['instance'])
                except:
                    pass
                mqtt_publish_with_retry(mqttc, topic, json.dumps(myresult), retain)

            if screenOut>0:
                print(topic, "-", json.dumps(myresult, indent=4))
        return True

    def mainLoop():
        if mqttOut:
            mqttc.loop_start()

        last_status_time = time.time()
        last_mqtt_check = time.time()

        try:
            while True:
                result = getLine()
                time.sleep(0.001)
                current_time = time.time()
                
                # Report MQTT connection status every 30 seconds (informational
                # only -- the loop thread started below handles reconnection
                # automatically, see mqtt_publish_with_retry for why we don't
                # drive it manually here)
                if mqttOut and (current_time - last_mqtt_check) >= 30:
                    if not mqtt_connected:
                        print("MQTT still disconnected; waiting for automatic reconnect...")
                    last_mqtt_check = current_time
                
                # Check if CAN traffic has been received recently (last 10 seconds)
                # Only show "no traffic" message if no CAN messages have been received by the watcher
                if (current_time - last_status_time) >= 10:
                    time_since_last_message = current_time - t.last_message_time
                    if time_since_last_message >= 10:
                        print(f"No CAN traffic detected in last {int(time_since_last_message)} seconds")
                    last_status_time = current_time
                    
        except KeyboardInterrupt:
            print("Received interrupt signal, shutting down...")
            if mqttOut:
                mqttc.loop_stop()
            if debug_level>3:
                datafile.close()
                print("datafile closed")
            raise SystemExit 
    mainLoop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--broker", default = "localhost", help="MQTT Broker Host")
    parser.add_argument("-d", "--debug", default = 0, type=int, choices=[0, 1, 2, 3, 4, 5], \
        help="debug data level \n\
            0=No debug\n\
            1=Print CAN messages\n\
            2=Print CAN messages and dump to datafile.txt\n\
            3=Print CAN messages and dump to datafile.txt and print parsed data\n\
            4=Read from datafile.txt and print parsed data\n\
            5=Write all transactions to to datafile.txt")
    parser.add_argument("-i", "--interface", default = "can0", help="CAN interface to use")
    parser.add_argument("-m", "--mqtt", default = 1, type=int, choices=[0, 1, 2], help="MQTT: 0=Don't publish, 1=Publish to MQTT, 2=Publish and Retain")
    parser.add_argument("-o", "--output", default = 0, type=int, choices=[0, 1], help="Dump parsed data to stdout")
    parser.add_argument("-s", "--specfile", default = os.path.join(script_dir, "rvc-spec.yml"), help="RVC Spec file")
    parser.add_argument("-t", "--topic", default = "RVC", help="MQTT topic prefix")
    parser.add_argument("-p", "--pstrings", action='store_true', help="Send parameterized strings to mqtt")
    args = parser.parse_args()

    # ENV DEBUG_LEVEL (set in Dockerfile/compose) takes precedence so the container
    # default pins debug off without requiring a CMD change.
    debug_level = int(os.environ.get('DEBUG_LEVEL', args.debug))
    mqttOut = args.mqtt
    screenOut = args.output
    mqttTopic = args.topic
    parameterized_strings = args.pstrings
    
    if mqttOut:
        import paho.mqtt.client as mqtt
        broker_address=args.broker
        mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2) #create new instance with updated API
        mqttc.on_connect = on_mqtt_connect
        mqttc.on_disconnect = on_mqtt_disconnect
        mqttc.on_subscribe = on_mqtt_subscribe
        mqttc.on_message = on_mqtt_message

        # Configure automatic reconnection
        mqttc.reconnect_delay_set(min_delay=1, max_delay=60)
        
        try:
            print("Connecting to MQTT: {0:s}".format(broker_address))
            mqttc.connect(broker_address, port=1883) #connect to broker
        except Exception as e:
            print(f"MQTT Broker Connection Failed: {e}")
            mqtt_connected = False

    print("Loading RVC Spec file {}.".format(args.specfile))
    with open(args.specfile,'r') as specfile:
        try:
            yaml_loader = yaml.YAML()
            spec = yaml_loader.load(specfile)
        except yaml.YAMLError as err:
            print(err)
            exit(1)

    if debug_level != 4:
        try:
            print("Connecting to CAN-Bus interface: {0:s}".format(args.interface))
            bus = can.interface.Bus(channel=args.interface, interface='socketcan')
        except OSError:
            print('Cannot find interface.')
            exit()

        q = queue.Queue()
        t = CANWatcher()	# Start CAN receive thread
        t.start()

    print("Processing started")

    main()
