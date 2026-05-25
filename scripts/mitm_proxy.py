#!/usr/bin/env python3
"""
W600 ↔ MyHeatPump cloud MITM proxy.

The USR-W600 is reconfigured to connect to THIS proxy instead of
www.myheatpump.com:18899. The proxy:
  1. Accepts the W600's incoming TCP connection.
  2. Resolves www.myheatpump.com and opens its own outbound connection.
  3. Forwards bytes in both directions transparently (app continues to work).
  4. Logs every byte to two .bin files, separated by direction.

Usage:
    python3 mitm_proxy.py
    # ... change W600 SocketB destination to <this-host>:18899 ...
    # ... change DHW setpoint in app a few times ...
    # ... Ctrl+C ...
    # Two files appear:
    #   from_w600_<timestamp>.bin  (W600 → cloud, contains status echo)
    #   to_w600_<timestamp>.bin    (cloud → W600, contains WRITE COMMANDS)

The second file is the prize — that's where the setpoint-change bytes are.
"""

import argparse
import datetime
import logging
import socket
import socketserver
import threading
import time

# ──────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────
LISTEN_HOST    = "0.0.0.0"
LISTEN_PORT    = 18899
UPSTREAM_HOST  = "www.myheatpump.com"
UPSTREAM_PORT  = 18899
LOG_DIR        = "."

log = logging.getLogger("mitm")


def relay(src: socket.socket, dst: socket.socket, log_path: str | None, tag: str,
          stop_event: threading.Event, hex_log: bool) -> None:
    """Forward bytes src→dst. If log_path is given, also tee them to a file."""
    total = 0
    f = open(log_path, "wb") if log_path else None
    try:
        src.settimeout(1.0)
        while not stop_event.is_set():
            try:
                chunk = src.recv(8192)
            except socket.timeout:
                continue
            if not chunk:
                log.info("[%s] connection closed by source (after %d bytes)", tag, total)
                break
            dst.sendall(chunk)
            if f:
                f.write(chunk)
                f.flush()
            total += len(chunk)
            if hex_log:
                if len(chunk) < 64:
                    hexv = " ".join(f"{b:02X}" for b in chunk)
                    log.info("[%s] %3d bytes: %s", tag, len(chunk), hexv)
                else:
                    log.info("[%s] %d bytes (first 32): %s ...", tag, len(chunk),
                             " ".join(f"{b:02X}" for b in chunk[:32]))
            else:
                log.debug("[%s] %d bytes", tag, len(chunk))
    except Exception as e:
        log.warning("[%s] relay error: %s", tag, e)
    finally:
        if f: f.close()
        stop_event.set()
        try: src.shutdown(socket.SHUT_RD)
        except Exception: pass
        try: dst.shutdown(socket.SHUT_WR)
        except Exception: pass


class MitmHandler(socketserver.BaseRequestHandler):
    hex_log = False    # set by main()
    capture = False    # set by main()

    def handle(self) -> None:
        client_sock = self.request
        client_addr = self.client_address
        log.info("W600 connected from %s", client_addr)

        try:
            upstream = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=10)
            log.info("Upstream connected to %s:%d", UPSTREAM_HOST, UPSTREAM_PORT)
        except OSError as e:
            log.error("Cannot reach upstream %s:%d → %s", UPSTREAM_HOST, UPSTREAM_PORT, e)
            client_sock.close()
            return

        if self.capture:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path_in  = f"{LOG_DIR}/from_w600_{ts}.bin"
            path_out = f"{LOG_DIR}/to_w600_{ts}.bin"
            log.info("Logging  W600→cloud  to %s", path_in)
            log.info("Logging  cloud→W600  to %s  ← writes here", path_out)
        else:
            path_in = path_out = None  # relay only, no disk writes

        stop = threading.Event()
        t1 = threading.Thread(target=relay,
                              args=(client_sock, upstream, path_in,  "W600→CLOUD", stop, self.hex_log),
                              daemon=True)
        t2 = threading.Thread(target=relay,
                              args=(upstream, client_sock, path_out, "CLOUD→W600", stop, self.hex_log),
                              daemon=True)
        t1.start(); t2.start()
        t1.join();  t2.join()

        for s in (client_sock, upstream):
            try: s.close()
            except Exception: pass
        log.info("Session ended")


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    global LOG_DIR, LISTEN_PORT
    p = argparse.ArgumentParser(
        description="W600 ↔ cloud MITM proxy. Default: silent transparent relay (no logs, no captures).",
    )
    p.add_argument("-v", "--verbose", action="count", default=0,
                   help="-v: log connection events. -vv: also log hex chunks.")
    p.add_argument("-q", "--quiet", action="store_true", help="Errors only.")
    p.add_argument("-c", "--capture", action="store_true",
                   help="Write capture .bin files to disk (one pair per W600 session). "
                        "Off by default — without this flag the proxy just relays bytes.")
    p.add_argument("--listen-port", type=int, default=LISTEN_PORT)
    p.add_argument("--log-dir", default=LOG_DIR,
                   help="Directory for capture .bin files when --capture is set (default: current dir).")
    args = p.parse_args()

    if args.quiet:        level = logging.ERROR
    elif args.verbose >= 1: level = logging.INFO
    else:                  level = logging.WARNING

    logging.basicConfig(level=level,
                        format="%(asctime)s %(levelname)s %(message)s")
    MitmHandler.hex_log = (args.verbose >= 2)
    MitmHandler.capture = args.capture

    LOG_DIR = args.log_dir
    LISTEN_PORT = args.listen_port

    with ThreadedTCPServer((LISTEN_HOST, LISTEN_PORT), MitmHandler) as srv:
        log.warning("MITM proxy listening on %s:%d → upstream %s:%d",
                    LISTEN_HOST, LISTEN_PORT, UPSTREAM_HOST, UPSTREAM_PORT)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            log.warning("Shutting down")


if __name__ == "__main__":
    main()
