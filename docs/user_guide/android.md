# Use your Android device as a PostgreSQL server

## Termux application

[Termux](https://termux.com/) is an **Android terminal emulator** and Linux environment app that allows to install Linux softwares on your device. You can use this tool to install a PostgreSQL server inside your Android device, and use it to hold a LisSync **clone database**.

For more information on Termux, please read the [Termux Wiki](https://wiki.termux.com/wiki/Main_Page).

## Install and configure PostgreSQL on Termux

A full **set of scripts** has been developed to ease the installation, configuration and use of **PostgreSQL and PostGIS** in Termux. See [the README file](https://github.com/mdouchin/termux-postgis-script/) for a detailed how-to.

Once you have successfully installed this set of scripts, you can use your Android tablet or smartphone as a **PostgreSQL clone database server**.

## Connection between your computer and your Android device

### WIFI connection

You just need to connect to the **same WIFI hotspot** from your computer and from your Android device. Then, each one will have an **IP address** in the same network, and you will able to connect from your computer to your Android PostgreSQL server.

Inside Termux, you can follow this guideline: https://github.com/mdouchin/termux-postgis-script/#use-postgresql

!!! tip
    The WIFI connection can sometimes be unstable, which could cause issues when transfering a large amount of data. You can use USB connection instead. See below.

### USB connection

You can **speed up the data transfer** and have a **more stable connection** between your computer and your Android device by using the USB cable to create a network and share the Android device WIFI or 3/4/5G connection with your computer. Depending on your Android version, the steps should roughly be:

- Stops the WIFI or wired internet connection on your computer
- Start the WIFI or 3/4/5G connection on your Android device. Make sure your internet connection is working before going on.
- Plug an USB wire between your computer and your device
- Do not use the "File sharing mode" (do not accept it if a message asking to allow it prompts)
- Go to Android preferences, connections, and activate "USB tethering/modem"
- The connection is active: your computer should be able to use the device internet connection. Try by testing a website inside your computer browser.
- You now need to figure out the IP addresses of your computer and your Android device for this local network. They should share the same beginning. For example, in your Android shell, type `ip add` and look for an IP beginning with `192.168.`. For example `192.168.42.184`. In your computer, you should be able to get your IP address form the internet connection manager, for example by clicking "Details" on you connection name. You can also use a **shell** or **command prompt** to know the IP address of your computer in the newly created network. Use `ipconfig` in Windows, and `ifconfig` or `ip ad` in your Linux terminal.
- **Use the Android Termux IP** to connect from your computer to your Android PostgreSQL database.
