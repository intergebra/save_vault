"""Save Vault — encrypted game save backup tool.

Run this on both computers:
  - On the source machine: add your games (Library) and Backup Now / enable Auto.
  - On the destination machine: go to Receiver, set a destination folder, and Start Receiver.
  - Both machines must have the SAME 256-bit key set under Settings.
"""

from app.gui import run

if __name__ == "__main__":
    run()
