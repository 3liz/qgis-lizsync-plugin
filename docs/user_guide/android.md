---
Title: LizSync plugin - PostgreSQL in Android
Favicon: ../icon.png
Index: yes
...

[TOC]

## Introduction

There is two way to use PostgreSQL on Android, with two different apps:

* UserLand: https://userland.tech/
* Termux: https://termux.com/

## Installation and configuration

### UserLand

todo

### Termux

A full script has been developped to ease the installation and use of PostgreSQL and PostGIS in Termux. See: https://github.com/mdouchin/termux-postgis-script/

## Connection between your computer and Android

### WIFI connection

You just need to connect to the same WIFI hotspot from your computer and from your Android device. Then, each one will have an IP address, and you will able to connect from your computer to your Android PostgreSQL server.

Inside Termux, you can follow this guideline: https://github.com/mdouchin/termux-postgis-script/#use-postgresql

The WIFI connection can sometimes be unstable, which could cause issues when transfering a large amount of data. You can use USB connection instead.

### USB connection

You can **speed up** the data transfer and have a more stable connection between your computer and your Android device by using the USB cable to create a network and share the Android device WIFI or 3/4/5G connection with your computer. Depending on your Android version, the steps should roughly be:

- Stops the WIFI or wired internet connection on your computer
- Start the WIFI or 3/4/5G connection on your Android device. Make sure your internet connection is working before going on.
- Plug an USB wire between your computer and your device
- Do not use the "File sharing mode" (do not accept it if a message asking to allow it prompts)
- Go to Android preferences, connections, and activate "USB tethering/modem"
- The connection is active: your computer should be able to use the device internet connection. Try by testing a website inside your computer browser.
- You now need to figure out the IP addresses of your computer and your Android device for this local network. They should share the same beginning. For example, in your Android shell, type `ip add` and look for an IP beginning with `192.168.`. For example `192.168.42.184`. In your computer, you should be able to get your IP address form the internet connection manager, for example by clicking "Details" on you connection name.
- Use these IP to connect from your computer to your Android PostgreSQL database.

### Termux
