# Phone Inbox

Send photos, videos and other files from your iPhone to your Windows PC over Wi-Fi, like AirDrop for Windows.
Original files, full quality, photos sorted in the order you took them. No cable, no cloud, no app to install.

```
  + 2026-10-13_18-20-00.HEIC   1.1 MB
  + 2026-10-13_20-45-11.MOV   47.9 MB
  + Lecture notes.pdf          2.9 MB
  + New Recording.m4a        9.3 MB
```

- **Originals.** No recompression. Location and camera data stay intact.
- **In order.** Photos and videos are named by capture time, so sorting by name sorts by when you took them.
- **Any file.** PDFs, voice memos, documents: tap Share in any app and pick **Send to Laptop**. They keep their own name.
- **Works on locked-down networks.** Campus, office, hotel and guest Wi-Fi often stop devices from seeing each other. There the PC opens its own Wi-Fi and shows a QR code to join it.
- **Nothing left running.** Close the window and everything is switched off again.

Needs Windows 11 (10 should work), [Python 3.8+](https://www.python.org/downloads/) and an iPhone with the Shortcuts app.

## Setup

**On the PC**, run this in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

It installs [segno](https://github.com/heuer/segno) and [ExifTool](https://exiftool.org), opens port 8765 for your local network, and prints the URL for the shortcut. The `token` in it is the shortcut's password; `py -3 server.py --info` prints it again.

**On the iPhone**, turn on *Settings > Apps > Shortcuts > Advanced > Allow Sharing Large Amounts of Data*, then build a shortcut called **Send to Laptop**. Turn on *Show in Share Sheet* in its details (the ⓘ button) first; that adds the top line.

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

To pick a property such as *Name*, tap the *Repeat Item* variable after inserting it.

## Use

1. Double-click `Phone_Inbox.cmd`.
2. On the iPhone, either:
   - in any app (Photos, Files, Mail, Voice Memos), select what you want, tap Share and choose **Send to Laptop**, or
   - tap the **Send to Laptop** icon itself to pick a single photo or video.

   For many photos, select them in Photos (tap *Select*, then slide across them) and share them all at once.
3. Close the window when you're done.

You can lock the phone while it sends.

| Network | What happens |
|---|---|
| Home Wi-Fi | The phone sends directly. |
| Campus, office, hotel or guest Wi-Fi | The PC turns on its own Wi-Fi and shows a QR code. Scan it, send, switch back. |

On such a network the window looks like this:

```
  Laptop is on  Office-WiFi
  New network (WPA2-Enterprise login): networks like this wall devices off from each other.
  Turning on the laptop's own Wi-Fi network...

  █████████████████████████████████████
  ██ ▄▄▄▄▄ █▄▄▄█▀▄██ ▀█▄█ █▄██ ▄▄▄▄▄ ██
  ██ █   █ █▄▀█▄▀▄██▄ █▄▀ ▀▀ █ █   █ ██
  ██ █▄▄▄█ █▀▀▄▀ ▄▀ █ ▀█▄▄▀█▀█ █▄▄▄█ ██
  ██▄▄▄▄▄▄▄█▄▀▄█ █▄▀ █ █ █▄█▄█▄▄▄▄▄▄▄██
  ...

  On the iPhone: open the Camera, point it at this code, tap "Join".
```

The window remembers what worked on each network. Press **H** to use the PC's own Wi-Fi anyway.

> [!WARNING]
> Some universities and offices forbid personal hotspots. Check the network's rules first.
> The hotspot only runs while the window is open.

## Troubleshooting

- **The shortcut can't connect.** Is the window open, and is the phone on the same Wi-Fi? If so, press **H**. Also check that Shortcuts is allowed in *Settings > Privacy & Security > Local Network*.
- **"Another program is using port 8765".** The window names the program. Close it and open `Phone_Inbox.cmd` again.
- **Photos are named by arrival time.** ExifTool is missing. Run `setup.ps1` again.
- **A file arrives named by date instead of its own name.** The shortcut is missing the `X-Name` and `X-Ext` headers.
- **A Live Photo has no motion.** Shortcuts only passes the still image.

Every start, file and cleanup step is logged in `inbox.log`.

<details>
<summary><b>How it works</b></summary>

<br>

The iPhone uploads each file over plain HTTP to a small receiver on the PC. A random token in the URL keeps other devices out, and the receiver only listens while its window is open. The PC reads the capture date from inside each photo and video with ExifTool. Other files keep the name the shortcut sends along; a file with the same name and size is skipped, one with the same name and a different size gets a `-2`.

Whether the phone can reach the PC depends on the network. A single device can't test that reliably, so the window uses the login type: shared-password Wi-Fi works directly, while personal-login (campus, office), open and wired networks get the hotspot. After each send it remembers what actually worked.

However the window ends (closed, crashed or killed), `guard.ps1` turns the hotspot off and deletes half-received files. A power loss is cleaned up on the next start.

</details>

<details>
<summary><b>iOS versions</b></summary>

<br>

The PC side doesn't depend on iOS at all. The shortcut uses only basic actions that have been in Shortcuts for years. It was built on iOS 18.7, and Apple's iOS 26 documentation describes these actions unchanged. On iOS 17 and earlier, the setting lives under *Settings > Shortcuts > Advanced*.

</details>

<details>
<summary><b>Files and uninstall</b></summary>

<br>

| File | |
|---|---|
| `Phone_Inbox.cmd` | Starts the window |
| `server.py` | Receiver and window |
| `hotspot.ps1` · `guard.ps1` | Hotspot control and cleanup |
| `setup.ps1` | One-time setup |
| `config.json` | Token, target folder, learned networks. Local only. |

To uninstall, run `Remove-NetFirewallRule -DisplayName 'Phone inbox'` as administrator, then delete the folder.

</details>

---

MIT licensed. See [LICENSE](LICENSE).
