#! /usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import json
import os

from subprocess import Popen, PIPE
from threading import Thread

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.debug = True

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"New logLevel = {}".format(self.logLevel))

    def __del__(self):
        indigo.PluginBase.__del__(self)

    def startup(self):
        self.logger.debug(u"Slack 2 startup")
        self.wrappers = {}
        self.read_threads = {}
        self.channels = {}
        self.triggers = {}


    def shutdown(self):
        self.logger.debug(u"Slack 2 shutdown")

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
    
        self.logger.debug(u"New logLevel = {}".format(self.logLevel))


    def deviceStartComm(self, device):

        self.logger.debug(u"{}: Starting Device".format(device.name))

        if device.deviceTypeId == "slackAccount":

            # Start up the wrapper task            
#            wrapper = Popen(['/usr/bin/python3', './wrapper.py', device.pluginProps['app_token'], device.pluginProps['bot_token']], 
            wrapper = Popen(['./venv/bin/python3', './wrapper.py', device.pluginProps['app_token'], device.pluginProps['bot_token']], 
                                stdin=PIPE, stdout=PIPE, close_fds=True, bufsize=1, universal_newlines=True)
            self.wrappers[device.id] = wrapper

            # create the reader thread        
            read_thread = Thread(target=self.wrapper_read, args=(device.id,))            
            read_thread.daemon = True
            read_thread.start()
            self.read_threads[device.id] = read_thread

            # request a conversations (channels) list
            msg = {'cmd': 'conversations_list'} 
            self.wrapper_write(device, msg)
                                
    
    def deviceStopComm(self, device):
        self.logger.debug(u"{}: Stopping Device".format(device.name))
        self.wrappers[device.id].terminate()
        # reader thread will end when wrapper closes connection            


    def get_channel_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug(u"get_channel_list, targetId={}, typeId={}, valuesDict = {}".format(targetId, typeId, valuesDict))
        if typeId == 'send':
            return self.channels[targetId]
        elif typeId == 'messageEvent':
            return self.channels[int(valuesDict['slackDevice'])]
        else:
            return []

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict

    ########################################
    # Trigger (Event) handling 
    ########################################

    def triggerStartProcessing(self, trigger):
        self.logger.debug("{}: Adding Trigger".format(trigger.name))
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug("{}: Removing Trigger".format(trigger.name))
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]


    def wrapper_write(self, device, msg):
        jsonMsg = json.dumps(msg)
        self.logger.threaddebug(u"Send wrapper message: {}".format(jsonMsg))
        self.wrappers[device.id].stdin.write(u"{}\n".format(jsonMsg))


    def wrapper_read(self, devID):
        device = indigo.devices[devID]
        wrapper = self.wrappers[device.id]
        while True:
            msg = wrapper.stdout.readline()
            self.logger.threaddebug(u"{}: Received wrapper message: {}".format(device.name, msg.rstrip()))
            
            data = json.loads(msg)
            if data['msg'] == 'echo':
                self.logger.threaddebug("{}: Echo: {}".format(device.name, data['request']))
                
            elif data['msg'] == 'status':
                self.logger.info("{}: {}".format(device.name, data['status']))
                device.updateStateOnServer(key="status", value=data['status'])
                device.updateStateImageOnServer(indigo.kStateImageSel.None)
                
            elif data['msg'] == 'error':
                self.logger.error("{}: {}".format(device.name, data['error']))

            elif data['msg'] == 'channels':
                self.logger.debug("{}: Channels: {}".format(device.name, data['channels']))
                self.channels[devID] = [ 
                    (channel["id"], channel["name"]) 
                    for channel in data["channels"] 
                ]

            elif data['msg'] == 'received':
                self.logger.debug("{}: Received {} ({})".format(device.name, data['type'], data['envelope_id']))
                self.logger.threaddebug(json.dumps(data['payload'], sort_keys=True, indent=4, separators=(',', ': ')))  
                event = data['payload']['event']          
                key_value_list = [
                    {'key':'last_event_type',           'value':event['type']},
                    {'key':'last_event_channel',        'value':event['channel']},
                    {'key':'last_event_channel_type',   'value':event['channel_type']},
                    {'key':'last_event_user',           'value':event['user']},
                    {'key':'last_event_text',           'value':event['text']}
                ]
                device.updateStatesOnServer(key_value_list)  

                # Now do any triggers
                for trigger in self.triggers.values():
                    self.logger.debug("{}: Testing Event Trigger".format(trigger.name))
                    if trigger.pluginProps["slackDevice"] == str(device.id):
            
                        if trigger.pluginTypeId == "messageEvent":
                            if event['channel'] == trigger.pluginProps['slackChannel']:
                                indigo.trigger.execute(trigger)
                                                    
                        else:
                            self.logger.error("{}: Unknown Trigger Type {}".format(trigger.name, trigger.pluginTypeId))
    
            
            else:
                self.logger.error("{}: Unknown Message type '{}'".format(device.name, data['msg']))
            
                    
    # helper functions

    def prepareTextValue(self, strInput):

        if strInput is None:
            return strInput
        else:
            strInput = self.substitute(strInput.strip()).encode('utf8')

            self.logger.debug("Stripped Text: {}".format(strInput))
            return strInput


    # actions go here
    def sendMessage(self, pluginAction, slackDevice, callerWaitingForResult):
        
        msgText = self.prepareTextValue(pluginAction.props['msgBody'])
        channel = pluginAction.props['channel']

        msg = {'cmd': 'chat_postMessage', 'channel': channel, 'text': msgText} 
        self.wrapper_write(slackDevice, msg)
 
        attach = pluginAction.props.get("attachments", "")
        if len(attach) > 0:

            files = indigo.activePlugin.substitute(attach)
            fileList = files.split(",")
            for file in fileList:
                path = os.path.expanduser(file)
                name = os.path.basename(path)
                msg = {'cmd': 'files_upload', 'channel': channel, 'filepath': path, 'title': name} 
                self.wrapper_write(slackDevice, msg)

