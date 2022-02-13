#! /usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import json
import os
import requests
from urllib.parse import quote, quote_plus

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


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
        self.triggers = []
        self.webhook_url = None

    def startup(self):
        self.logger.debug("Slack 2 startup")

        # Test here to see if Reflector webhook is available, get reflector name, etc.
        reflectorURL = indigo.server.getReflectorURL()
        reflector_api_key = self.pluginPrefs.get("reflector_api_key", None)
        if not reflectorURL or not reflector_api_key:
            self.logger.warning("Unable to set up Slack webhook - Reflector not configured")
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
        token = device.pluginProps.get('bot_token', None)
        if not token:
            self.logger.debug(f"{device.name}: No token")
            return

        client = WebClient(token=device.pluginProps['bot_token'])
        auth_info = client.auth_test()
        self.slack_accounts[auth_info['team_id']] = device.id
        self.logger.info(f"{device.name}: Connected to Slack Workspace '{auth_info['team']}'")

        self.channels[device.id] = [
            (channel["id"], channel["name"])
            for channel in client.conversations_list()['channels']
        ]
        self.logger.debug("{}: Channels: {}".format(device.name, self.channels[device.id]))

    def deviceStopComm(self, device):
        self.logger.debug(f"{device.name}: Stopping Device")

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
        self.triggers.remove(trigger.id)

    ########################################
    # OAuth methods
    ########################################

    def closedDeviceConfigUi(self, valuesDict, userCancelled, typeId, devId):
        if userCancelled:
            return

        # If the user saves the Workspace device, then it needs to initiate the OAuth process

        reflectorURL = indigo.server.getReflectorURL()
        reflector_api_key = self.pluginPrefs.get("reflector_api_key", None)

        if not reflectorURL and not reflector_api_key:
            self.logger.warning("Unable to do Slack Authentication - no reflector configured")
            return

        oauth_url = "https://slack.com/oauth/v2/authorize"
        client_id = "3094061694373.3109586185505"
        scopes = "channels:history,channels:join,channels:read,chat:write,files:write,im:history"
        redirect_uri = f"{reflectorURL}/message/{self.pluginId}/oauth?api_key={reflector_api_key}"
        request_url = f'{oauth_url}?client_id={client_id}&scope={scopes}&state={devId}&redirect_uri={quote_plus(redirect_uri)}'
        self.logger.info(f"Starting OAuth with URL: {request_url}")
        self.browserOpen(request_url)

    def oauth_handler(self, action, dev=None, callerWaitingForResult=None):
        if action.props['incoming_request_method'] != "GET":
            self.logger.warning(f"oauth_handler: Unexpected request method: {action.props['incoming_request_method']}")
            self.logger.debug(f"oauth_handler action.props: {action.props}")
            return "200"

        query_args = action.props['url_query_args']
        self.logger.debug(f"oauth_handler code = {query_args['code']}, state = {query_args['state']}")

        reflectorURL = indigo.server.getReflectorURL()
        reflector_api_key = self.pluginPrefs.get("reflector_api_key", None)
        client_id = "3094061694373.3109586185505"
        client_secret = "922633579e0b5f9024e89fa1f25ee151"
        redirect_uri = f"{reflectorURL}/message/{self.pluginId}/oauth?api_key={reflector_api_key}"
        self.logger.debug(f"oauth_handler redirect_uri = {redirect_uri}")
        try:
            client = WebClient()
            oauth_response = client.oauth_v2_access(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, code=query_args['code'])
        except Exception as err:
            self.logger.debug(f"oauth_handler oauth_v2_access error = {err}")
            return

        #self.logger.threaddebug(f"oauth_response: {json.dumps(oauth_response, indent=4, sort_keys=True)}")
        self.logger.threaddebug(f"oauth_response: {oauth_response}")

        bot_token = oauth_response.get("access_token")
        self.logger.debug(f"bot_token = {bot_token}")
        if bot_token is None:
            self.logger.warning(f"missing bot_token")
            return

        try:
            auth_test = client.auth_test(token=bot_token)
        except Exception as err:
            self.logger.debug(f"oauth_handler auth_test error = {err}")
            return

        self.logger.threaddebug(f"auth_test: {auth_test}")
        #self.logger.threaddebug(f"auth_test response: {json.dumps(auth_test, indent=4, sort_keys=True)}")

        self.logger.debug(f"oauth_handler validating request for device {query_args['state']}")
        device = indigo.devices.get(int(query_args['state']), None)
        if not device:
            self.logger.warning(f"No device found for validation request: {query_args['state']}")
        device.pluginProps['bot_token'] = bot_token
        newProps = device.pluginProps
        newProps['bot_token'] = bot_token
        device.replacePluginPropsOnServer(newProps)
        self.logger.info(f"Completed OAuth validation for {device.name}")

        return "200"

    ########################################
    # Reflector handlers
    ########################################

    def webhook_handler(self, action, dev=None, callerWaitingForResult=None):
        if action.props['incoming_request_method'] != "POST":
            self.logger.warning(f"webhook_handler: Unexpected request method: {action.props['incoming_request_method']}")
            self.logger.debug(f"webhook_handler action.props: {action.props}")
            return "200"

        request_body = json.loads(action.props['request_body'])
        self.logger.threaddebug(f"webhook_handler request_body: {json.dumps(request_body, indent=4, sort_keys=True)}")

        if request_body['type'] == 'url_verification':
            return json.dumps({'challenge': request_body['challenge']})

        elif request_body['type'] == 'event_callback':
            devId = self.slack_accounts[request_body["team_id"]]
            device = indigo.devices[devId]
            return self.handle_event(device, request_body['event'])

        else:
            self.logger.debug(f"webhook_handler unimplemented message type: {request_body['type']}")
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
            self.logger.debug(f"{trigger.name}: Testing Event Trigger")
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
    def menuChanged(self, valuesDict=None, typeId=None, devId=None):  # noqa
        return valuesDict

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
