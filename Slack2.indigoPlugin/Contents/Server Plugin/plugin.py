#! /usr/bin/env python
# -*- coding: utf-8 -*-

from slackclient import SlackClient
import logging
import json

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
        self.clients = {}

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

        self.logger.debug(u"%s: Starting Device" % device.name)

        if device.deviceTypeId == "slackAccount":
            slack_token = device.pluginProps.get(u'slack_token', None)
            sc = SlackClient(slack_token)
            self.clients[device.id] = sc
            
            result = sc.api_call("channels.list", exclude_archived=1)
            if result["ok"]:            
                self.logger.debug(u"{}: Connection OK, found {} channels.".format(device.name, len(result["channels"])))
            else:
                self.logger.error(u"{}: Slack connection error: {}".format(device.name, result["error"]))

        
    
    def deviceStopComm(self, device):
        self.logger.debug(u"%s: Stopping Device" % device.name)
            


    def get_channel_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        result = self.clients[targetId].api_call("channels.list", exclude_archived=1)
        return [ 
            (channel["id"], channel["name"]) 
            for channel in result["channels"] 
        ]

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict


    # helper functions

    def prepareTextValue(self, strInput):

        if strInput is None:
            return strInput
        else:
            strInput = strInput.strip()

            strInput = self.substitute(strInput)

            #fix issue with special characters
            strInput = strInput.encode('utf8')

            self.logger.debug("Stripped Text: {}".format(strInput))

            return strInput


    # actions go here
    def sendMessage(self, pluginAction, slackDevice, callerWaitingForResult):
        
        message = self.prepareTextValue(pluginAction.props['msgBody'])
        channel = pluginAction.props['channel']
        sc = self.clients[slackDevice.id]
        
        result = sc.api_call("chat.postMessage", channel=channel, text=message, reply_broadcast=True)
        if result["ok"]:            
            self.logger.info(u"{}: Message sent successfully".format(slackDevice.name))   
            slackDevice.updateStateOnServer(key="status", value="Success")
        else:
            self.logger.warning(u"{}: Message failed with error: {}".format(slackDevice.name, result["error"]))   
            slackDevice.updateStateOnServer(key="status", value="Error")

        
