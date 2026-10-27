# Phone Inbox

Send photos, videos and any other file from your iPhone to your Windows PC over Wi-Fi, like AirDrop for Windows. No cable, no cloud, no app to install.

```
  + IMG_4821.HEIC          1.1 MB
  + IMG_4822.MOV          47.9 MB
  + Lecture notes.pdf      2.9 MB
  + New Recording.m4a      9.3 MB
```

Files arrive as the originals, uncompressed, with their own names. Each file's date on the PC is when it was taken, recorded or created, not when it was sent. On campus, office and guest Wi-Fi, where devices often can't see each other, the PC opens its own Wi-Fi and shows a QR code to join it. Closing the window switches everything off again.

Needs Windows 11 (10 should work), [Python 3.8+](https://www.python.org/downloads/) and an iPhone with the Shortcuts app.

## Setup

On the PC, run this in the project folder. It installs [segno](https://github.com/heuer/segno) and [ExifTool](https://exiftool.org), opens port 8765 for the local network and prints the URL for the shortcut. The `token` in the URL is the shortcut's password; `py -3 server.py --info` prints it again.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

On the iPhone, turn on *Settings > Apps > Shortcuts > Advanced > Allow Sharing Large Amounts of Data*. Then build a shortcut called **Send to Laptop** and turn on *Show in Share Sheet* in its details (the ⓘ button), which adds the first line below. To pick a property such as *Name*, tap the *Repeat Item* variable after inserting it.

```
Receive Any input from Share Sheet        If there's no input: Ask For Photos
Repeat with each item in Shortcut Input
    Get Contents of URL                   your URL · POST
                                          Headers: X-Name = Repeat Item › Name
                                                   X-Ext  = Repeat Item › File Extension
                                          Request Body: File = Repeat Item
End Repeat
Show Notification                         Sent to laptop
```

## Use

Double-click `Phone_Inbox.cmd`. On the iPhone, select what you want in any app (Photos, Files, Mail, Voice Memos), tap Share and choose **Send to Laptop**. Tapping the shortcut's own icon picks a single photo. You can lock the phone while it sends. Close the window when you're done.

On home Wi-Fi the phone sends directly. On networks that keep devices apart, the window looks like this; scan the code, send, then switch the phone back to the usual Wi-Fi.

```
  Laptop is on  Office-WiFi
  New network (WPA2-Enterprise login): networks like this wall devices off from each other.
  Turning on the laptop's own Wi-Fi network...

  █████████████████████████████████████
  ██ ▄▄▄▄▄ █▄▄▄█▀▄██ ▀█▄█ █▄██ ▄▄▄▄▄ ██
  ██ █   █ █▄▀█▄▀▄██▄ █▄▀ ▀▀ █ █   █ ██
  ...

  On the iPhone: open the Camera, point it at this code, tap "Join".
```

The window remembers what worked on each network. Press **H** to use the PC's own Wi-Fi anyway.

> [!WARNING]
> Some universities and offices forbid personal hotspots. Check the network's rules first. The hotspot only runs while the window is open.

## Troubleshooting

If the shortcut can't connect, check that the window is open and the phone is on the same Wi-Fi, then press **H**. Shortcuts also needs *Settings > Privacy & Security > Local Network*. If the window says another program is using port 8765, it names that program; close it and start again.

A file dated by when it was sent either has no date inside (common for images saved from the web or messengers), or ExifTool is missing; run `setup.ps1` again. A file named by date instead of its own name means the shortcut lacks the `X-Name` and `X-Ext` headers. Live Photos arrive as stills, because Shortcuts only passes the image.

Every start, file and cleanup step is logged in `inbox.log`.

<details>
<summary><b>How it works</b></summary>

<br>

The iPhone uploads each file over plain HTTP to a small receiver on the PC. The token keeps other devices out, and the receiver only listens while its window is open. The PC reads each file's date with ExifTool and sets the file's created and modified time to it. A file already there with the same name and size is skipped; a different file with the same name gets `-2`.

Whether the phone can reach the PC depends on the network, and a single device can't test that reliably. So the window goes by the login type: shared-password Wi-Fi works directly, while personal-login, open and wired networks get the hotspot. After each send it remembers what actually worked.

However the window ends (closed, crashed or killed), `guard.ps1` turns the hotspot off and deletes half-received files. A power loss is cleaned up on the next start.

The shortcut only uses basic actions that have been in Shortcuts for years. It was built on iOS 18.7; on iOS 17 and earlier the setting above lives under *Settings > Shortcuts > Advanced*.

</details>

<details>
<summary><b>Files and uninstall</b></summary>

<br>

`Phone_Inbox.cmd` starts the window, `server.py` is the receiver, `hotspot.ps1` and `guard.ps1` control and clean up the hotspot, and `setup.ps1` is the one-time setup. `config.json` holds the token, target folder and learned networks and stays local.

To uninstall, run `Remove-NetFirewallRule -DisplayName 'Phone inbox'` as administrator, then delete the folder.

</details>

---

MIT licensed. See [LICENSE](LICENSE).
