# Slack plugin for Indigodomo Home Automation

[![N|Solid](http://forums.indigodomo.com/static/www/images/wordmark.png)](http://indigodomo.com)

## Summary
This plugin extends [Indigo](http://www.indigodomo.com) allowing it to send messages to [Slack](https://slack.com).

## Installation

* This is version 2.+ of the Slack 2 plugin, which uses the current slack_sdk package instead of the older slackclient package.  The SDK requires Python 3, which this plugin supports by running the Python3 code in a separate process which communicates with the Python2 plugin.
* These instructions assume you're running a version of macOS that supports Python3 natively (Catalina or later).  Running an older version of macOS with Python3 installed separately will probably work, but has not been tested.  The plugin assumes that there is a Python 3.8 (or later) binary at /usr/bin/python3.
* For the Apple installed Python3 (Catalina or later) you must install and RUN Xcode to get the latest Python components.  Just installing is not enough, Xcode must be started so you get the "Install additional components" prompt.
* Additional Python packages will need to be installed:

```
sudo /usr/bin/pip3 install slack-sdk
sudo /usr/bin/pip3 install aiohttp
sudo /usr/bin/pip3 install aiofiles
```  

* Download the ZIP file from Releases (above)
* Unzip the file if it doesn't automatically unzip
* On the computer running Indigo, double-click the file "Slack2.indigoPlugin"
* Follow the Indigo dialog and enable the plugin
* The plugin should be visible in the Plugins drop-down menu as "Slack 2"
* Trouble?: Indigo help for the [installation process](http://wiki.indigodomo.com/doku.php?id=indigo_6_documentation:getting_started)

## Configuration
Requires configuring an application in the Slack Developer's Dashboard.
See [the wiki for detailed configuration information](https://github.com/FlyingDiver/Indigo-Slack2/wiki).

