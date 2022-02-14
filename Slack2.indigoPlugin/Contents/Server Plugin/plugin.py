#! /usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import json
import os
import requests
import threading
from urllib.parse import quote, quote_plus

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

OAUTH_URL = "https://slack.com/oauth/v2/authorize"
CLIENT_ID = "3094061694373.3109586185505"
CLIENT_KEY = "922633579e0b5f9024e89fa1f25ee151"
SCOPES = "channels:history,channels:join,channels:read,chat:write,files:write,im:history"
REFRESH_INTERVAL = 6.0 * 60.0 * 60.0    # 6 hours

def make_html_reply(status, title, text):
    return {'status': status,
            "headers": {"Content-Type": "text/html; charset=UTF-8", },
            "content": f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{title}</title></head><body>{text}</body></html>'
            }

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"LogLevel = {self.logLevel}")

        self.slack_accounts = {}
        self.channels = {}
        self.triggers = []

        # Test here to see if Reflector is available, get reflector name, etc.
        self.reflectorURL = indigo.server.getReflectorURL()
        self.reflector_api_key = self.pluginPrefs.get("reflector_api_key", None)
        if not self.reflectorURL or not self.reflector_api_key:
            self.reflector_ok = False
            self.logger.warning("Reflector and API Key required!")
        else:
            self.reflector_ok = True

        self.refresh_tokens()

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"New logLevel = {self.logLevel}")

    def deviceStartComm(self, device):
        self.logger.debug(f"{device.name}: Starting Device")

        access_token = device.pluginProps.get('bot_token', None)
        if not access_token:
            self.logger.debug(f"{device.name}: No access token")
            return

        client = WebClient(token=access_token)
        auth_info = client.auth_test()
        self.slack_accounts[auth_info['team_id']] = device.id
        self.logger.info(f"{device.name}: Connected to Slack Workspace '{auth_info['team']}'")

        self.channels[device.id] = [
            (channel["id"], channel["name"])
            for channel in client.conversations_list()['channels']
        ]
        self.logger.debug(f"{device.name}: Channels: {self.channels[device.id]}")

    def didDeviceCommPropertyChange(self, origDev, newDev): # noqa
        return False

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

        if not self.reflector_ok:
            self.logger.warning("Reflector and API Key required!")
            return

        redirect_uri = f"{self.reflectorURL}/message/{self.pluginId}/oauth?api_key={self.reflector_api_key}"
        request_url = f'{OAUTH_URL}?client_id={CLIENT_ID}&scope={SCOPES}&state={devId}&redirect_uri={quote_plus(redirect_uri)}'
        self.logger.debug(f"Starting OAuth for {devId} with URL:\n{request_url}")
        self.browserOpen(request_url)

    def oauth_handler(self, action, dev=None, callerWaitingForResult=None):

        if action.props['incoming_request_method'] != "GET":
            self.logger.warning(f"oauth_handler: Unexpected request method: {action.props['incoming_request_method']}")
            self.logger.debug(f"oauth_handler action.props: {action.props}")
            return make_html_reply(400, "Unexpected request method", f"Unexpected request method: {action.props['incoming_request_method']}")

        query_args = action.props['url_query_args']
        self.logger.debug(f"oauth_handler: OAuth validation query, code = {query_args['code']}, state = {query_args['state']}")

        redirect_uri = f"{self.reflectorURL}/message/{self.pluginId}/oauth?api_key={self.reflector_api_key}"
        self.logger.debug(f"oauth_handler redirect_uri = {redirect_uri}")
        try:
            client = WebClient()
            oauth_response = client.oauth_v2_access(client_id=CLIENT_ID, client_secret=CLIENT_KEY, redirect_uri=redirect_uri, code=query_args['code'])
        except Exception as err:
            self.logger.debug(f"oauth_handler oauth_v2_access error = {err}")
            return make_html_reply(400, "oauth_v2_access error", f"Uoauth_v2_access error: {err}")
        self.logger.threaddebug(f"oauth_response: {json.dumps(oauth_response.data, indent=4, sort_keys=True)}")

        access_token = oauth_response.get("access_token")
        self.logger.debug(f"access_token = {access_token}")
        if access_token is None:
            self.logger.warning(f"missing access_token")
            return make_html_reply(400, "oauth_v2_access error", f"missing access_token")

        refresh_token = oauth_response.get("refresh_token")
        self.logger.debug(f"refresh_token = {refresh_token}")
        if refresh_token is None:
            self.logger.warning(f"missing refresh_token")
            return make_html_reply(400, "oauth_v2_access error", f"missing refresh_token")

        expires_in = oauth_response.get("expires_in")
        self.logger.debug(f"expires_in = {expires_in}")
        if expires_in is None:
            self.logger.warning(f"missing expires_in")
            return make_html_reply(400, "oauth_v2_access error", f"missing expires_in")

        try:
            auth_test = client.auth_test(token=access_token)
        except Exception as err:
            self.logger.debug(f"oauth_handler auth_test error = {err}")
            return make_html_reply(400, "auth_test error", f"auth_test error: {err}")
        self.logger.threaddebug(f"auth_test response: {json.dumps(auth_test.data, indent=4, sort_keys=True)}")

        self.logger.debug(f"oauth_handler validating request for device {query_args['state']}")
        device = indigo.devices.get(int(query_args['state']), None)
        if not device:
            self.logger.warning(f"No device found for validation request: {query_args['state']}")
            return make_html_reply(400, "State validation error", f"No device found for validation request: {query_args['state']}")

        newProps = device.pluginProps
        newProps['bot_token'] = access_token   # historical prop name
        newProps['refresh_token'] = refresh_token
        device.replacePluginPropsOnServer(newProps)
        self.logger.info(f"Completed OAuth validation for Workspace {device.name}")
        return make_html_reply(200, "Slack Authentication Successful", f"Slack Authentication Successful for Workspace {auth_test.get('team')}")

    def refresh_tokens(self):
        self.logger.debug(f"refresh_tokens start")
        for device in indigo.devices.iter("self"):

            refresh_token = device.pluginProps.get('refresh_token', None)
            self.logger.debug(f"{device.name}: Token refresh using {refresh_token}")

            try:
                client = WebClient()
                oauth_response = client.oauth_v2_access(client_id=CLIENT_ID, client_secret=CLIENT_KEY, grant_type="refresh_token", refresh_token=refresh_token)
            except Exception as err:
                self.logger.debug(f"oauth_handler oauth_v2_access error = {err}")
                return
            self.logger.threaddebug(f"oauth_response: {json.dumps(oauth_response.data, indent=4, sort_keys=True)}")

            access_token = oauth_response.get("access_token")
            self.logger.debug(f"access_token = {access_token}")
            if access_token is None:
                self.logger.warning(f"missing access_token")
                return

            refresh_token = oauth_response.get("refresh_token")
            self.logger.debug(f"refresh_token = {refresh_token}")
            if refresh_token is None:
                self.logger.warning(f"missing refresh_token")
                return

            expires_in = oauth_response.get("expires_in")
            self.logger.debug(f"expires_in = {expires_in}")
            if expires_in is None:
                self.logger.warning(f"missing expires_in")
                return

            newProps = device.pluginProps
            newProps['bot_token'] = access_token   # historical prop name
            newProps['refresh_token'] = refresh_token
            device.replacePluginPropsOnServer(newProps)
            self.logger.info(f"Completed Token Refresh for {device.name}")

        # start timer for next refresh.
        self.logger.debug(f"Resetting timer for token refresh")
        try:
            self.refresh_timer = threading.Timer(interval=REFRESH_INTERVAL, function=self.refresh_tokens)   # noqa
            self.refresh_timer.start()
        except Exception as err:
            self.logger.debug(f"Error starting refresh timer: {err}")
        self.logger.debug(f"Done resetting timer for token refresh")
        return

    ########################################
    # Reflector handlers
    ########################################

    def webhook_handler(self, action, dev=None, callerWaitingForResult=None):
        if action.props['incoming_request_method'] != "POST":
            self.logger.warning(f"webhook_handler: Unexpected request method: {action.props['incoming_request_method']}")
            self.logger.debug(f"webhook_handler action.props: {action.props}")
            return {'status': 400}

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
            return {'status': 400}

    def handle_event(self, device, event):

        user = event.get('user', None)
        if not user and (event.get('subtype', None) == "bot_message"):
            user = event.get('username', None)
        if not user:
            user = "--Unknown--"
        self.logger.debug(f"{device.name}: Event type: {event['type']}, Channel: {event['channel']}, User: {user}, Text: {event['text']}")
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

        return {'status': 200}

    ##################

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
