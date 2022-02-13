#! /usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import json
import os

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from threading import Thread

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.debug = True

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"LogLevel = {self.logLevel}")

        self.slack_accounts = {}
        self.channels = {}
        self.triggers = {}

    def startup(self):
        self.logger.debug("Slack 2 startup")

        # Test here to see if Reflector webhook is available, get reflector name, etc.
        reflectorURL = indigo.server.getReflectorURL()
        if not reflectorURL:
            self.logger.warning("Unable to set up Slack webhooks - no reflector configured")
            return

        reflector_api_key = self.pluginPrefs.get("reflector_api_key", None)
        if not reflector_api_key:
            self.logger.warning("Unable to set up Slack webhooks - no reflector API key")
            return

        self.webhook_url = f"{reflectorURL}/message/{self.pluginId}/webhook?api_key={reflector_api_key}"
        self.logger.info(f"Reflector OK, this is your webhook URI for Slack dashboard: {self.webhook_url}")


    def shutdown(self):
        self.logger.debug("Slack 2 shutdown")

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"New logLevel = {self.logLevel}")

    def deviceStartComm(self, device):
        self.logger.debug(f"{device.name}: Starting Device")

        client = WebClient(token=device.pluginProps['bot_token'])
        auth_info = client.auth_test()
        self.slack_accounts[auth_info['team_id']] = device.id
        self.logger.info(f"{device.name}: Connected to Slack Workspace '{auth_info['team']}'")
        channels = {}

        self.channels[device.id] = [
            (channel["id"], channel["name"])
            for channel in client.conversations_list()['channels']
        ]
        self.logger.info("{}: Channel List Updated".format(device.name))
        self.logger.debug("{}: Channels: {}".format(device.name, self.channels[device.id]))

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict=None, typeId=None, devId=None):
        return valuesDict

    ########################################
    # Trigger (Event) handling
    ########################################

    def triggerStartProcessing(self, trigger):
        self.logger.debug(f"{trigger.name}: Adding Trigger")
        assert trigger.id not in self.triggers
        self.triggers.append(trigger.id)

    def triggerStopProcessing(self, trigger):
        self.logger.debug(f"{trigger.name}: Removing Trigger")
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]

    def deviceStopComm(self, device):
        self.logger.debug(f"{device.name}: Stopping Device")

    def reflector_handler(self, action, dev=None, callerWaitingForResult=None):
        request_body = json.loads(action.props['request_body'])
        self.logger.threaddebug(f"request_body: {json.dumps(request_body, indent=4, sort_keys=True)}")

        if request_body['type'] == 'url_verification':
            self.challenge_token = request_body['token']
            return json.dumps({'challenge': request_body['challenge']})

        elif request_body['type'] == 'event_callback':
            devId = self.slack_accounts[request_body["team_id"]]
            device = indigo.devices[devId]
            return self.handle_event(device, request_body['event'])

        else:
            self.logger.debug(f"{device.name}: Unimplemented message type: {request_body['type']}")
            return "200"

    def handle_event(self, device, event):

        user = event.get('user', None)
        if not user and (event.get('subtype', None) == "bot_message"):
            user = event.get('username', None)
        if not user:
            user = "--Unknown--"

        key_value_list = [
            {'key': 'last_event_type', 'value': event['type']},
            {'key': 'last_event_channel', 'value': event['channel']},
            {'key': 'last_event_channel_type', 'value': event['channel_type']},
            {'key': 'last_event_user', 'value': user},
            {'key': 'last_event_text', 'value': event['text']}
        ]
        device.updateStatesOnServer(key_value_list)

        # Now do any triggers
        for triggerId in self.triggers:
            trigger = indigo.triggers[triggerId]
            self.logger.debug("{}: Testing Event Trigger".format(trigger.name))
            if trigger.pluginProps["slackDevice"] == str(device.id):

                if trigger.pluginTypeId == "messageEvent":
                    if event['channel'] == trigger.pluginProps['slackChannel']:
                        indigo.trigger.execute(trigger)

                else:
                    self.logger.error(f"{trigger.name}: Unknown Trigger Type {trigger.pluginTypeId}")

        return "200"

    def get_channel_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug(f"get_channel_list, targetId={targetId}, typeId={typeId}, valuesDict = {valuesDict}")
        slackDevice = indigo.devices.get(int(valuesDict.get('slackDevice', 0)), None)
        if typeId == 'send':
            return self.channels[targetId]
        elif typeId == 'messageEvent' and slackDevice:
            return self.channels[slackDevice.id]
        else:
            return []

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):      # noqa
        return valuesDict


    ########################################
    # Trigger (Event) handling 
    ########################################

    def triggerStartProcessing(self, trigger):
        self.logger.debug(f"{trigger.name}: Adding Trigger")
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug(f"{trigger.name}: Removing Trigger")
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]

    # helper functions

    def prepareTextValue(self, strInput):
        if strInput:
            strInput = self.substitute(strInput.strip())
        return strInput

    # actions go here
    def sendMessage(self, pluginAction, slackDevice, callerWaitingForResult):
        
        msgText = self.prepareTextValue(pluginAction.props['msgBody'])
        channel = pluginAction.props['channel']

        client = WebClient(token=slackDevice.pluginProps['bot_token'])
        client.chat_postMessage(channel=channel, text=msgText)

        attach = pluginAction.props.get("attachments", "")
        if len(attach) > 0:
            files = indigo.activePlugin.substitute(attach)
            fileList = files.split(",")
            for file in fileList:
                path = os.path.expanduser(file)
                name = os.path.basename(path)
                client.files_upload(channels=channel, file=path, title=name)
