import threading
import time


class BackupScheduler:
    """Polls profiles and triggers run_backup(profile) when their interval elapses."""

    def __init__(self, get_profiles, run_backup, log=print):
        self.get_profiles = get_profiles
        self.run_backup = run_backup
        self.log = log
        self._running = False
        self._thread = None
        self._last_run = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            now = time.time()
            for profile in list(self.get_profiles()):
                if not profile.get("auto_enabled"):
                    continue
                interval = max(1, int(profile.get("interval_minutes", 30))) * 60
                last = self._last_run.get(profile["id"], 0)
                if now - last >= interval:
                    self._last_run[profile["id"]] = now
                    try:
                        self.run_backup(profile)
                    except Exception as exc:
                        self.log(f"Auto-backup failed for {profile.get('name')}: {exc}")
            time.sleep(5)
