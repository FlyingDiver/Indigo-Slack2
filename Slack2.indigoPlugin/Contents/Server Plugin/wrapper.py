import os
import sys
import json
import asyncio
import aiofiles

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest


# Write JSON string to STDOUT for input to plugin

async def msg_write(msg):
    sys.stdout.write(u"{}\n".format(json.dumps(msg)))
    sys.stdout.flush()


async def send_to_slack(channel, text):
    try:
        response = await web_client.chat_postMessage(channel=channel, text=text)
        assert response["message"]["text"] == text
    except SlackApiError as e:
        assert e.response["ok"] is False
        assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
        raise e

async def main():

    # Process incoming events from Slack, uses the SocketModeClient bot_client
        
    async def process(client: SocketModeClient, req: SocketModeRequest):

        await msg_write({'msg': 'received', 'type': req.type,  'envelope_id': req.envelope_id, 'payload': req.payload})

        if req.type == "events_api":
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await bot_client.send_socket_mode_response(response)


    # Send API commands Slack, uses the AsyncWebClient web_client

    async def send_to_slack(channel, text):
        try:
            response = await web_client.chat_postMessage(channel=channel, text=text)
        except SlackApiError as err:
            await msg_write({'msg': 'error', 'error': err.args})
        else:
            await msg_write({'msg': 'status', 'status': "Send OK"})


    async def upload_to_slack(channel, filepath):
        try:
            response = await web_client.files_upload(channels=channel, file=filepath)
        except Exception as err:
            await msg_write({'msg': 'error', 'error': err.args})
        else:
            await msg_write({'msg': 'status', 'status': "Upload OK"})
            

    async def conversations_list():
        try:
            response = await web_client.conversations_list()        
        except SlackApiError as err:
            await msg_write({'msg': 'error', 'error': err.args})
        else:
            channels = [ 
                {"id": channel["id"], "name": channel["name"]}
                for channel in response["channels"] 
            ]
            await msg_write({'msg': 'channels', 'channels': channels})


    # Read Input from stdin (from the plugin) and executes commands

    async def read_input():
        async with aiofiles.open('/dev/stdin', mode='r') as f:
            while True:
                line  = await f.readline()
                try:
                    request = json.loads(line.rstrip())
                except:
                    await msg_write({'msg': 'error', 'error': "JSON decode error: {}".format(line)})
                else:
                    await msg_write({'msg': 'echo', 'request': request})
                    cmd = request['cmd']
         
                    if cmd == 'chat_postMessage':
                        await send_to_slack(request['channel'], request['text'])

                    elif cmd == 'files_upload':
                        await upload_to_slack(request['channel'], request['filepath'])

                    elif cmd == 'conversations_list':
                        await conversations_list()


        
    # Initialize SocketModeClient with an app-level token + AsyncWebClient
    try:
        web_client = AsyncWebClient(token=sys.argv[2])
        bot_client = SocketModeClient(app_token=sys.argv[1], web_client=web_client)
    except SlackApiError as e:
        await msg_write({'msg': 'error', 'error': err.args})
        assert e.response["ok"] is False
        assert e.response["error"] 
        exit()
    else:
        await msg_write({'msg': 'status', 'status': "Clients Created"})

    try:
        bot_client.socket_mode_request_listeners.append(process)
    except SlackApiError as err:
        await msg_write({'msg': 'status', 'status': "Listener Error"})
        await msg_write({'msg': 'error', 'error': err.args})
        exit()
    else:
        await msg_write({'msg': 'status', 'status': "Listener Added"})


    try:
        await bot_client.connect()
    except SlackApiError as err:
        await msg_write({'msg': 'status', 'status': "Socket Connect Error"})
        await msg_write({'msg': 'error', 'error': err.args})
        exit()
    else:
        await msg_write({'msg': 'status', 'status': "Socket Connected"})

    # report the allowed conversations (channels)  
    await conversations_list()
    
    # loop on input from plugin
    await read_input()      # never returns    

    
# actual start of the program
    
asyncio.run(main())
