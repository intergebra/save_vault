import io
import json
import os
import socket
import struct
import threading
import time
import zipfile
from pathlib import Path

from .crypto_utils import decrypt_chunk, encrypt_chunk

CHUNK_SIZE = 64 * 1024
END_MARKER = b"__END__"


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed unexpectedly.")
        buf.extend(chunk)
    return bytes(buf)


def _send_msg(sock: socket.socket, key: bytes, plaintext: bytes):
    payload = encrypt_chunk(key, plaintext)
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def _recv_msg(sock: socket.socket, key: bytes) -> bytes:
    length = struct.unpack(">I", _recv_exact(sock, 4))[0]
    payload = _recv_exact(sock, length)
    return decrypt_chunk(key, payload)


def zip_path(path: Path) -> bytes:
    """Zip a save folder (recursively) or a single save file into an in-memory archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if path.is_dir():
            for root, _, files in os.walk(path):
                for fname in files:
                    full = Path(root) / fname
                    arcname = full.relative_to(path.parent)
                    zf.write(full, arcname)
        else:
            zf.write(path, path.name)
    return buf.getvalue()


class AuthError(Exception):
    pass


def send_backup(host: str, port: int, key: bytes, game_name: str, save_path: str,
                 timeout: float = 15.0, log=print) -> str:
    """Locate + zip the save files and push them, encrypted, to the receiver. Returns remote filename."""
    src = Path(save_path).expanduser()
    if not src.exists():
        raise FileNotFoundError(f"Save path does not exist: {src}")

    log(f"[{game_name}] Collecting save files from {src} ...")
    data = zip_path(src)

    log(f"[{game_name}] Connecting to {host}:{port} ...")
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        # --- Auth handshake: server sends a random challenge, we must encrypt it
        #     correctly with the shared key to prove we hold it. ---
        challenge = _recv_exact(sock, 16)
        response = encrypt_chunk(key, challenge)
        sock.sendall(struct.pack(">I", len(response)) + response)
        ack = _recv_exact(sock, 1)
        if ack != b"\x01":
            raise AuthError("Authentication failed: the 256-bit key does not match the receiver.")

        log(f"[{game_name}] Authenticated. Sending backup ...")
        filename = f"{game_name}_{int(time.time())}.zip"
        meta = json.dumps({"game_name": game_name, "filename": filename, "size": len(data)}).encode("utf-8")
        _send_msg(sock, key, meta)

        offset = 0
        total = len(data)
        while offset < total:
            chunk = data[offset: offset + CHUNK_SIZE]
            _send_msg(sock, key, chunk)
            offset += len(chunk)
        _send_msg(sock, key, END_MARKER)
        log(f"[{game_name}] Sent {total / 1024:.1f} KB successfully as {filename}.")
        return filename


class ReceiverServer:
    """Listens for incoming encrypted backups and writes them to dest_folder."""

    def __init__(self, port: int, key: bytes, dest_folder: str, keep_last_n: int = 10,
                 log=print, on_event=None):
        self.port = port
        self.key = key
        self.dest_folder = Path(dest_folder).expanduser()
        self.keep_last_n = keep_last_n
        self.log = log
        self.on_event = on_event
        self._sock = None
        self._thread = None
        self._running = False

    def start(self):
        if self._running:
            return
        self.dest_folder.mkdir(parents=True, exist_ok=True)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.listen(5)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log(f"Receiver listening on port {self.port}. Saving backups to {self.dest_folder}")

    def stop(self):
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        self.log("Receiver stopped.")

    @property
    def running(self):
        return self._running

    def _loop(self):
        while self._running:
            try:
                conn, addr = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn, addr), daemon=True).start()

    def _handle(self, conn: socket.socket, addr):
        try:
            with conn:
                conn.settimeout(20)
                challenge = os.urandom(16)
                conn.sendall(challenge)
                length = struct.unpack(">I", _recv_exact(conn, 4))[0]
                payload = _recv_exact(conn, length)
                try:
                    plaintext = decrypt_chunk(self.key, payload)
                except Exception:
                    conn.sendall(b"\x00")
                    self.log(f"Rejected connection from {addr[0]}: key mismatch.")
                    return
                if plaintext != challenge:
                    conn.sendall(b"\x00")
                    self.log(f"Rejected connection from {addr[0]}: challenge mismatch.")
                    return
                conn.sendall(b"\x01")

                meta = json.loads(_recv_msg(conn, self.key).decode("utf-8"))
                game_name = meta.get("game_name", "unknown_game")
                filename = meta.get("filename", f"{game_name}_{int(time.time())}.zip")
                self.log(f"Receiving '{game_name}' from {addr[0]} ...")

                data = bytearray()
                while True:
                    part = _recv_msg(conn, self.key)
                    if part == END_MARKER:
                        break
                    data.extend(part)

                out_path = self.dest_folder / filename
                out_path.write_bytes(data)
                self.log(f"Saved backup: {out_path.name} ({len(data) / 1024:.1f} KB)")
                self._cleanup_old(game_name)
                if self.on_event:
                    self.on_event(game_name, str(out_path))
        except Exception as exc:
            self.log(f"Receiver error from {addr[0]}: {exc}")

    def _cleanup_old(self, game_name: str):
        if not self.keep_last_n or self.keep_last_n <= 0:
            return
        files = sorted(
            self.dest_folder.glob(f"{game_name}_*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[self.keep_last_n:]:
            try:
                old.unlink()
            except OSError:
                pass
