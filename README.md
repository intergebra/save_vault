# Save Vault

A small desktop app that backs up game save files from one computer to another over the
network, encrypted end-to-end with a 256-bit key that only your two machines know.

## Features

- **Library** — add any game by pointing at its save folder (or a single save file).
- **Encrypted transfer** — AES-256-GCM, authenticated with a shared 256-bit key.
  Every connection starts with a challenge/response handshake, so a machine that doesn't
  know the key can't connect, read, or forge backups.
- **Receiver** — run on the destination computer to accept incoming backups into a folder
  you choose, with automatic pruning of old backups (keep last N).
- **Manual or automatic** — click "Backup Now", or flip "Auto" on a game to back it up on
  a timer (interval configurable per game).
- **Steam-inspired dark UI** — sidebar navigation, game library cards, live activity log.

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.10+ .

## Setup (do this once, on both computers)

1. Run `python main.py` on **Computer A** (the one that has the save files).
2. Go to **Settings → Generate New Key → Copy to Clipboard → Save Key**.
3. Run `python main.py` on **Computer B** (the one that will store backups).
4. Go to **Settings**, paste the same key, and **Save Key**. Both machines now share the
   same 256-bit secret — keep it private, it's the only thing authenticating your transfers.

## Configure the receiver (Computer B)

1. Go to **Receiver**.
2. Set the **Listen Port** (default `5001`) and **Destination Folder**.
3. Click **Start Receiver**. Leave the app running (or set your OS to launch it at login)
   to keep receiving backups.
4. Note Computer B's local IP (e.g. `192.168.1.42`) — you'll need it on Computer A. If
   backing up over the internet rather than a LAN, use a VPN like Tailscale/WireGuard/RadminVPN, or
   forward the chosen port on your router.

## Configure a game (Computer A)

1. Go to **Library → + Add Game**.
2. Fill in:
   - **Game Name** — used to label the backup file.
   - **Save Folder / File** — where that game stores its saves.
   - **Remote Host** — Computer B's IP address.
   - **Remote Port** — must match the Receiver's Listen Port.
   - **Auto-backup Interval** — how often to back up automatically, in minutes.
3. Click **Save Game**.
4. Click **Backup Now** to test it, or flip the **Auto** switch to back up on that schedule
   automatically while the app is running.

Backups arrive on Computer B as timestamped zip files:
`<GameName>_<unix-timestamp>.zip` inside your chosen destination folder.

## How the security works

- The key is a random 256-bit value (32 bytes), shown/entered as 64 hex characters.
- Every message (auth challenge response, metadata, each file chunk) is individually
  encrypted with AES-256-GCM using a fresh random nonce, which also gives you tamper
  detection — a corrupted or forged chunk fails to decrypt and the transfer aborts.
- The receiver never accepts a connection until the sender proves it holds the same key
  by correctly encrypting a random challenge.
- This is a private-key scheme, not a certificate/TLS setup — it's meant for two machines
  you personally control on a trusted network or VPN, not for public internet exposure
  without additional protection (e.g. a VPN or firewall rules restricting who can reach
  the receiver's port).
