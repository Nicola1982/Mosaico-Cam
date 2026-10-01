#!/usr/bin/env python3
"""
Mosaico Camere 1.0 - visualizzatore telecamere ONVIF / RTSP a mosaico.
Copyright (C) 2026 Murari Nicola
Licenza: GPL-3.0-or-later (software libero, nessuna garanzia). Vedi LICENSE.txt e CONDIZIONI_USO.txt.
Assistenza e funzioni premium: su accordo con l'autore.

Installazione:
    pip install opencv-python pillow onvif-zeep numpy

Uso:
    python mosaico_cam.py

- "Aggiungi telecamera": scegli ONVIF (IP + utente + password) oppure RTSP diretto (URL).
- Tasto destro su un riquadro: Modifica / Rimuovi / Ingrandisci.
- Doppio click su un riquadro: ingrandisce / torna al mosaico.
- F11: schermo intero.  Esc: esci dallo schermo intero.

Le telecamere sono salvate in cameras.json accanto allo script
(password in chiaro: proteggi il file se il PC e' condiviso).
"""
import json
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from urllib.parse import urlparse, quote, unquote
from concurrent.futures import ThreadPoolExecutor
import uuid
import xml.etree.ElementTree as ET

# RTSP su TCP (piu' stabile) + timeout 5s. Va impostato PRIMA di importare cv2.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageTk
except ImportError as e:
    import subprocess as _sp
    _PKGS = ["opencv-python", "pillow", "numpy", "onvif-zeep"]
    try:
        from tkinter import messagebox
        _r = tk.Tk()
        _r.withdraw()
        if messagebox.askyesno("Moduli mancanti",
                               f"Manca un modulo ({e}).\n\nInstallare ora i moduli necessari?\n"
                               "(servono 1-2 minuti e la connessione internet)"):
            _w = tk.Toplevel(_r)
            _w.title("Installazione")
            tk.Label(_w, text="Installazione in corso, attendere...", padx=30, pady=20).pack()
            _w.update()
            _res = _sp.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *_PKGS],
                           creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
            _w.destroy()
            if _res.returncode == 0:
                _sp.Popen([sys.executable] + sys.argv)  # riavvia il programma
                raise SystemExit(0)
            messagebox.showerror("Errore", "Installazione non riuscita. Da terminale:\n  pip install " + " ".join(_PKGS))
    except SystemExit:
        raise
    except Exception:
        print("Manca un modulo. Installa con: pip install " + " ".join(_PKGS))
    raise SystemExit(1)

if sys.platform == "win32":  # nitidezza su schermi ad alta risoluzione / scala 125-150%
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

if sys.platform == "win32":  # permette all'installer/disinstallatore di accorgersi che il programma e' aperto
    try:
        import ctypes
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "MosaicoCamereAppMutex")
    except Exception:
        pass

# Cartella del programma e cartella dati (persistente anche quando il programma e' un .exe installato)
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def _app_dir():
    base = os.environ.get("APPDATA")
    d = Path(base) / "MosaicoCamere" if base else BASE_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return BASE_DIR


APP_DIR = _app_dir()
for _n in ("cameras.json", "settings.json"):  # migra i file della vecchia versione
    try:
        if not (APP_DIR / _n).exists() and (BASE_DIR / _n).exists():
            shutil.copy2(BASE_DIR / _n, APP_DIR / _n)
    except OSError:
        pass

CONFIG = APP_DIR / "cameras.json"
FPS_UI = 15  # aggiornamenti al secondo del mosaico
APP_NAME = "Mosaico Camere"
APP_VERSION = "1.0"
APP_AUTHOR = "Murari Nicola"

# ------------------------------------------------------------ registrazione
SETTINGS_FILE = APP_DIR / "settings.json"
REC_SUBDIR = "MosaicoCam_Rec"  # sottocartella creata dentro il percorso scelto
REC_FPS = 10                   # fotogrammi/secondo registrati
SEGMENT_SEC = 300              # un file ogni 5 minuti
SETTINGS = {"rec_enabled": False, "rec_dir": "", "retention_hours": 24}


def find_ffmpeg():
    cands = [BASE_DIR / "ffmpeg.exe",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"]
    return shutil.which("ffmpeg") or next((str(c) for c in cands if c.is_file()), None)


FFMPEG = find_ffmpeg()  # None = registrazione a bassa risoluzione


def load_settings():
    try:
        SETTINGS.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass


def save_settings():
    try:
        SETTINGS_FILE.write_text(json.dumps(SETTINGS, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def rec_root():
    return Path(SETTINGS["rec_dir"]) / REC_SUBDIR


def cleanup_old():
    """Cancella i .mp4 piu' vecchi di retention_hours (solo dentro <cartella>/MosaicoCam_Rec)."""
    if not SETTINGS.get("rec_dir"):
        return
    root = rec_root()
    if not root.is_dir():
        return
    try:
        ore = float(SETTINGS.get("retention_hours", 24))
    except (TypeError, ValueError):
        ore = 24.0
    limit = time.time() - ore * 3600
    for p in root.rglob("*.mp4"):
        try:
            if p.stat().st_mtime < limit:
                p.unlink()
        except OSError:
            pass


load_settings()


# ----------------------------------------------------------------- utilita' URL
def with_auth(uri, user, pw, host=None):
    """Inserisce utente/password nell'URL RTSP (ed eventualmente forza l'host)."""
    u = urlparse(uri)
    if not user or "@" in u.netloc:
        return uri
    h = host or u.hostname
    netloc = f"{quote(user, safe='')}:{quote(pw or '', safe='')}@{h}"
    if u.port:
        netloc += f":{u.port}"
    return u._replace(netloc=netloc).geturl()


def find_wsdl():
    """Cartella wsdl di onvif-zeep (dentro l'exe oppure nella libreria installata)."""
    import sysconfig
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(Path(sys._MEIPASS) / "wsdl")
    try:
        import onvif
        cands.append(Path(onvif.__file__).resolve().parent.parent / "wsdl")
    except ImportError:
        pass
    pl = Path(sysconfig.get_paths()["purelib"])
    cands += [pl / "wsdl", pl.parent / "site-packages" / "wsdl"]
    return next((c for c in cands if (c / "devicemgmt.wsdl").exists()), None)


def resolve_url(cam, profile=None):
    """Ritorna l'URL RTSP da aprire. Per ONVIF lo chiede alla telecamera."""
    if cam["type"] == "RTSP":
        return with_auth(cam["url"], cam.get("user"), cam.get("password"))

    try:
        from onvif import ONVIFCamera
    except ImportError:
        raise RuntimeError("manca onvif-zeep (pip install onvif-zeep)")

    wd = find_wsdl()
    kw = {"wsdl_dir": str(wd)} if wd else {}
    c = ONVIFCamera(cam["host"], int(cam.get("port") or 80), cam.get("user", ""), cam.get("password", ""), **kw)
    media = c.create_media_service()
    profiles = media.GetProfiles()
    if not profiles:
        raise RuntimeError("nessun profilo ONVIF")

    def area(p):
        try:
            r = p.VideoEncoderConfiguration.Resolution
            return r.Width * r.Height
        except Exception:
            return 0

    profiles = sorted(profiles, key=area)
    prof = profiles[-1] if (profile or cam.get("profile")) == "main" else profiles[0]  # sub-stream = piu' leggero

    req = media.create_type("GetStreamUri")
    req.ProfileToken = prof.token
    req.StreamSetup = {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}}
    uri = media.GetStreamUri(req).Uri
    # molte telecamere restituiscono IP interni errati: forziamo l'host inserito
    return with_auth(uri, cam.get("user"), cam.get("password"), host=cam["host"])


# ------------------------------------------------------------------- worker
class CamWorker(threading.Thread):
    """Un thread per telecamera: legge di continuo, tiene solo l'ultimo frame."""

    def __init__(self, cam):
        super().__init__(daemon=True)
        self.cam = cam
        self.frame = None
        self.status = "Connessione..."
        self.stop_evt = threading.Event()
        self._writer = None
        self._w_start = 0
        self._w_size = None
        self._last_write = 0
        self.recording = False
        self.rec_hd = False

    def run(self):
        url = None
        while not self.stop_evt.is_set():
            try:
                if url is None:
                    self.status = "Recupero stream..."
                    url = resolve_url(self.cam)
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    raise RuntimeError("stream non raggiungibile")
                self.status = "OK"
                fails = 0
                while not self.stop_evt.is_set():
                    ok, f = cap.read()
                    if not ok:
                        fails += 1
                        if fails > 10:
                            break
                        time.sleep(0.05)
                        continue
                    fails = 0
                    self.frame = f
                    self._record(f)
                cap.release()
                self._close_writer()
                self.status = "Riconnessione..."
                self.frame = None
            except Exception as e:
                self.status = f"Errore: {str(e)[:45]}"
                self._close_writer()
                self.frame = None
                url = None  # per ONVIF ririchiede l'URL al prossimo giro
            self.stop_evt.wait(3)

    def _close_writer(self):
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
        self._writer = None
        self.recording = False

    def _record(self, f):
        if FFMPEG:  # la registrazione HD e' gestita da HDRecorder (ffmpeg)
            return
        try:
            if not (SETTINGS.get("rec_enabled") and SETTINGS.get("rec_dir")):
                self._close_writer()
                return
            now = time.time()
            if now < self._last_write + 1.0 / REC_FPS:
                return
            h, w = f.shape[:2]
            if self._writer is not None and (now - self._w_start > SEGMENT_SEC or self._w_size != (w, h)):
                self._close_writer()
            if self._writer is None:
                folder = rec_root() / re.sub(r"[^\w\-]+", "_", self.cam["name"])
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / time.strftime("%Y%m%d_%H%M%S.mp4")
                wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), REC_FPS, (w, h))
                if not wr.isOpened():
                    self._last_write = now + 5  # riprova tra qualche secondo
                    return
                self._writer, self._w_start, self._w_size = wr, now, (w, h)
                self.recording = True
            self._writer.write(f)
            self._last_write = now
        except Exception:
            self._close_writer()
            self._last_write = time.time() + 5

    def stop(self):
        self.stop_evt.set()


# ------------------------------------------------------------------- dialog
class CamDialog(tk.Toplevel):
    def __init__(self, parent, cam=None):
        super().__init__(parent)
        self.title("Telecamera")
        self.resizable(False, False)
        self.result = None
        cam = cam or {"type": "ONVIF", "port": 80, "profile": "sub"}

        self.vars = {}
        rows = [
            ("name", "Nome", None),
            ("type", "Tipo", ("ONVIF", "RTSP")),
            ("host", "IP / host (ONVIF)", None),
            ("port", "Porta ONVIF", None),
            ("user", "Utente", None),
            ("password", "Password", None),
            ("url", "URL RTSP (se tipo RTSP)", None),
            ("url_rec", "URL RTSP alta definizione (registrazione, opz.)", None),
            ("profile", "Stream (ONVIF)", ("sub", "main")),
        ]
        for i, (key, label, choices) in enumerate(rows):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=3)
            v = tk.StringVar(value=str(cam.get(key, "") or ""))
            self.vars[key] = v
            if choices:
                w = ttk.Combobox(self, textvariable=v, values=choices, state="readonly", width=38)
            else:
                w = ttk.Entry(self, textvariable=v, width=40, show="*" if key == "password" else "")
            w.grid(row=i, column=1, padx=8, pady=3)

        ttk.Label(
            self,
            text="Esempio RTSP: rtsp://192.168.1.10:554/stream1",
            foreground="#666",
        ).grid(row=len(rows), column=0, columnspan=2, padx=8, pady=(4, 0))

        bar = ttk.Frame(self)
        bar.grid(row=len(rows) + 1, column=0, columnspan=2, pady=8)
        ttk.Button(bar, text="Salva", command=self.ok).pack(side="left", padx=4)
        ttk.Button(bar, text="Annulla", command=self.destroy).pack(side="left", padx=4)

        self.transient(parent)
        self.grab_set()
        self.wait_window()

    def ok(self):
        d = {k: v.get().strip() for k, v in self.vars.items()}
        if not d["name"]:
            messagebox.showerror("Errore", "Inserisci un nome", parent=self)
            return
        if d["type"] == "ONVIF" and not d["host"]:
            messagebox.showerror("Errore", "Inserisci l'IP della telecamera", parent=self)
            return
        if d["type"] == "RTSP" and not d["url"].lower().startswith("rtsp://"):
            messagebox.showerror("Errore", "L'URL deve iniziare con rtsp://", parent=self)
            return
        self.result = d
        self.destroy()


# ------------------------------------------------- registrazione HD (ffmpeg)
def main_url_guess(url):
    """Da un URL sub-stream ricava quello principale (alta definizione) per i modelli piu' comuni."""
    u = re.sub(r"(/Streaming/Channels/\d*?)02\b", r"\g<1>01", url)   # Hikvision
    if u != url:
        return u
    for a, b in (("/stream2", "/stream1"),             # Tapo
                 ("subtype=1", "subtype=0"),           # Dahua
                 ("_sub", "_main")):                   # Reolink
        if a in url:
            return url.replace(a, b)
    return url


def rec_url(cam):
    """URL RTSP ad alta definizione da registrare."""
    if cam["type"] == "ONVIF":
        return resolve_url(cam, profile="main")
    u = (cam.get("url_rec") or "").strip() or main_url_guess(cam["url"])
    return with_auth(u, cam.get("user"), cam.get("password"))


class HDRecorder(threading.Thread):
    """Registra lo stream principale con ffmpeg, senza ricodificare (poca CPU, qualita' piena)."""

    def __init__(self, worker):
        super().__init__(daemon=True)
        self.w = worker
        self.cam = worker.cam
        self.stop_evt = threading.Event()
        self.proc = None
        self.started = 0
        self.safe = re.sub(r"[^\w\-]+", "_", self.cam["name"])

    def folder(self):
        return rec_root() / self.safe

    def newest_mtime(self):
        try:
            return max((f.stat().st_mtime for f in self.folder().glob("*.mp4")), default=0)
        except OSError:
            return 0

    def _start(self):
        url = rec_url(self.cam)
        folder = self.folder()
        folder.mkdir(parents=True, exist_ok=True)
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url,
               "-map", "0:v:0", "-c:v", "copy", "-an",
               "-f", "segment", "-segment_time", str(SEGMENT_SEC), "-reset_timestamps", "1",
               "-strftime", "1", "-segment_format", "mp4",
               "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
               str(folder / "%Y%m%d_%H%M%S.mp4")]
        with open(APP_DIR / f"ffmpeg_{self.safe}.log", "w") as log:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.started = time.time()

    def _stop_proc(self):
        p, self.proc = self.proc, None
        self.w.rec_hd = False
        if p is None:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.write(b"q")  # chiusura pulita: ffmpeg finalizza il file
                    p.stdin.flush()
                except Exception:
                    pass
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
        except Exception:
            pass

    def run(self):
        while not self.stop_evt.is_set():
            active = bool(SETTINGS.get("rec_enabled") and SETTINGS.get("rec_dir"))
            try:
                if not active:
                    self._stop_proc()
                elif self.proc is None:
                    self._start()
                elif self.proc.poll() is not None:      # ffmpeg terminato (rete/credenziali): riprova dopo 10s
                    self._stop_proc()
                    self.stop_evt.wait(10)
                    continue
                elif time.time() - self.started > 60 and time.time() - self.newest_mtime() > 45:
                    self._stop_proc()                    # stream bloccato: riavvia
                self.w.rec_hd = self.proc is not None and self.proc.poll() is None
            except Exception:
                self._stop_proc()
                self.stop_evt.wait(10)
            self.stop_evt.wait(1)
        self._stop_proc()

    def stop(self):
        self.stop_evt.set()


# ------------------------------------------------------- ricerca telecamere
COMMON_RTSP_PATHS = [
    "/stream2", "/stream1",                                # Tapo e molte cinesi (sub prima)
    "/Streaming/Channels/102", "/Streaming/Channels/101",  # Hikvision
    "/cam/realmonitor?channel=1&subtype=1",                # Dahua
    "/h264Preview_01_sub", "/h264Preview_01_main",         # Reolink
    "/H.264", "/live/ch00_1", "/onvif1", "/11", "/1",
]

WSD_PROBE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
    'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
    'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    '<e:Header><w:MessageID>uuid:UUID</w:MessageID>'
    '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
    '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
    '</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>'
    '</e:Envelope>'
)


def local_ips():
    """IPv4 locali (una per scheda di rete attiva)."""
    ips = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # non invia nulla: serve solo a scoprire l'IP in uso
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


def parse_probe(data, addr):
    """Interpreta la risposta WS-Discovery di una telecamera ONVIF."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    xaddrs = scopes = ""
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "XAddrs":
            xaddrs = el.text or ""
        elif tag == "Scopes":
            scopes = el.text or ""
    if not xaddrs and not scopes:
        return None
    port = 80
    for x in xaddrs.split():
        u = urlparse(x)
        if u.hostname and u.hostname.count(".") == 3:  # solo IPv4
            port = u.port or 80
            break
    nm = re.search(r"onvif://www\.onvif\.org/name/(\S+)", scopes)
    hw = re.search(r"onvif://www\.onvif\.org/hardware/(\S+)", scopes)
    name = unquote(nm.group(1)) if nm else (unquote(hw.group(1)) if hw else "")
    info = " / ".join(unquote(m.group(1)) for m in (nm, hw) if m) or "dispositivo ONVIF"
    return {"ip": addr[0], "port": port, "name": name, "info": f"{info}  (porta ONVIF {port})"}


def onvif_discover(timeout=4.0):
    """WS-Discovery: invia un Probe multicast da ogni scheda di rete e raccoglie le risposte."""
    found = {}
    msg = WSD_PROBE.replace("UUID", str(uuid.uuid4())).encode()
    socks = []
    for ip in local_ips():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.bind((ip, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            s.settimeout(0.4)
            for _ in range(2):
                s.sendto(msg, ("239.255.255.250", 3702))
            socks.append(s)
        except OSError:
            pass
    end = time.time() + timeout
    while time.time() < end and socks:
        for s in socks:
            try:
                data, addr = s.recvfrom(65535)
            except (socket.timeout, OSError):
                continue
            d = parse_probe(data, addr)
            if d:
                found[d["ip"]] = d
    for s in socks:
        s.close()
    return found


def scan_port(ip, port=554, timeout=0.6):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def rtsp_scan():
    """Scansiona la porta 554 su tutta la rete /24 di ogni scheda di rete."""
    mine = local_ips()
    hosts = set()
    for lip in mine:
        base = lip.rsplit(".", 1)[0]
        hosts.update(f"{base}.{i}" for i in range(1, 255))
    hosts = sorted(hosts - set(mine))
    found = []
    with ThreadPoolExecutor(max_workers=128) as ex:
        for ip, ok in zip(hosts, ex.map(scan_port, hosts)):
            if ok:
                found.append(ip)
    return found


def probe_rtsp(url):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        return bool(cap.isOpened() and cap.read()[0])
    finally:
        cap.release()


def guess_rtsp_url(ip, user, pw, port=554):
    """Prova i percorsi RTSP piu' comuni; ritorna l'URL (senza credenziali) che funziona."""
    urls = [with_auth(f"rtsp://{ip}:{port}{p}", user, pw) for p in COMMON_RTSP_PATHS]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for p, ok in zip(COMMON_RTSP_PATHS, ex.map(probe_rtsp, urls)):
            if ok:
                return f"rtsp://{ip}:{port}{p}"
    return None


class DiscoveryDialog(tk.Toplevel):
    def __init__(self, parent, existing, on_add):
        super().__init__(parent)
        self.title("Ricerca telecamere in rete")
        fit_geometry(self, 700, 520)
        self.minsize(360, 320)
        self.on_add = on_add
        self.existing = {(c.get("host") or urlparse(c.get("url") or "").hostname) for c in existing}
        self.q = queue.Queue()
        self.devices = {}
        self.busy = False
        self.closed = False
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.status = tk.StringVar()
        _st = ttk.Label(self, textvariable=self.status, wraplength=660)
        _st.pack(fill="x", padx=8, pady=(8, 2))
        autowrap(_st)
        self.pb = ttk.Progressbar(self, mode="indeterminate")
        self.pb.pack(fill="x", padx=8)

        self.tree = ttk.Treeview(self, columns=("ip", "tipo", "info"), show="headings",
                                 selectmode="extended", height=10)
        for c, t, w in (("ip", "IP", 130), ("tipo", "Tipo", 80), ("info", "Dettagli", 420)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)

        f = ttk.LabelFrame(self, text="Credenziali per le telecamere selezionate")
        f.pack(fill="x", padx=8, pady=2)
        self.user, self.pw, self.prof = tk.StringVar(), tk.StringVar(), tk.StringVar(value="sub")
        ttk.Label(f, text="Utente").grid(row=0, column=0, padx=4, pady=4)
        ttk.Entry(f, textvariable=self.user, width=16).grid(row=0, column=1)
        ttk.Label(f, text="Password").grid(row=0, column=2, padx=4)
        ttk.Entry(f, textvariable=self.pw, width=16, show="*").grid(row=0, column=3)
        ttk.Label(f, text="Stream").grid(row=0, column=4, padx=4)
        ttk.Combobox(f, textvariable=self.prof, values=("sub", "main"), state="readonly",
                     width=6).grid(row=0, column=5, padx=(0, 4))
        _hint = ttk.Label(self, foreground="#666", wraplength=660,
                  text="Tapo: account telecamera creato nell'app Tapo. EZVIZ: utente admin + codice di "
                       "verifica. Puoi lasciare vuoto e completare dopo con tasto destro > Modifica.",
                  )
        _hint.pack(fill="x", padx=8, pady=2)
        autowrap(_hint)

        bar = ttk.Frame(self)
        bar.pack(pady=8)
        ttk.Button(bar, text="Cerca di nuovo", command=self.search).pack(side="left", padx=4)
        ttk.Button(bar, text="Aggiungi selezionate", command=self.add_selected).pack(side="left", padx=4)
        ttk.Button(bar, text="Chiudi", command=self.close).pack(side="left", padx=4)

        self.search()

    def close(self):
        self.closed = True
        self.destroy()

    def start_busy(self, msg):
        self.busy = True
        self.status.set(msg)
        self.pb.start(12)
        self.after(200, self.poll)

    def finish(self, msg):
        self.busy = False
        self.pb.stop()
        self.status.set(msg)

    # ---- ricerca
    def search(self):
        if self.busy:
            return
        self.tree.delete(*self.tree.get_children())
        self.devices.clear()
        self.start_busy("Ricerca in corso (ONVIF + scansione porta 554), circa 5 secondi...")
        threading.Thread(target=self._search_worker, daemon=True).start()

    def _search_worker(self):
        try:
            with ThreadPoolExecutor(max_workers=2) as ex:
                f1, f2 = ex.submit(onvif_discover), ex.submit(rtsp_scan)
                onv, rtsp = f1.result(), f2.result()
            devs = {}
            for ip, d in onv.items():
                devs[ip] = {**d, "onvif": True}
            for ip in rtsp:
                if ip not in devs:
                    devs[ip] = {"ip": ip, "port": 554, "name": "", "onvif": False,
                                "info": "porta RTSP 554 aperta (solo RTSP)"}
            order = sorted(devs.values(), key=lambda d: tuple(int(x) for x in d["ip"].split(".")))
            self.q.put(("found", order))
        except Exception as e:
            self.q.put(("error", str(e)))

    def show(self, devs):
        for d in devs:
            info = d["info"] + ("   [gia' in elenco]" if d["ip"] in self.existing else "")
            self.tree.insert("", "end", iid=d["ip"], values=(d["ip"], "ONVIF" if d["onvif"] else "RTSP", info))
            self.devices[d["ip"]] = d
        if devs:
            self.finish(f"Trovati {len(devs)} dispositivi. Seleziona (Ctrl+click per piu' righe) e premi 'Aggiungi selezionate'.")
        else:
            self.finish("Nessun dispositivo trovato. Controlla di essere sulla stessa rete delle telecamere "
                        "e, se Windows chiede il permesso firewall per Python, consenti la rete privata.")

    # ---- aggiunta
    def add_selected(self):
        if self.busy:
            return
        sel = [self.devices[i] for i in self.tree.selection() if i not in self.existing]
        if not sel:
            messagebox.showinfo("Ricerca", "Seleziona almeno una telecamera non ancora in elenco.", parent=self)
            return
        args = (sel, self.user.get().strip(), self.pw.get(), self.prof.get())
        self.start_busy(f"Verifica di {len(sel)} telecamere in corso...")
        threading.Thread(target=self._add_worker, args=args, daemon=True).start()

    def _add_worker(self, sel, user, pw, prof):
        def one(d):
            ip = d["ip"]
            nm = f"{d['name'] or 'Camera'} ({ip})"
            if d["onvif"]:
                cam = {"name": nm, "type": "ONVIF", "host": ip, "port": str(d["port"]),
                       "user": user, "password": pw, "profile": prof}
                try:
                    resolve_url(cam)
                    note = "ok"
                except Exception as e:
                    note = f"da verificare ({str(e)[:50]})"
            else:
                url = guess_rtsp_url(ip, user, pw, d["port"])
                cam = {"name": nm, "type": "RTSP", "url": url or f"rtsp://{ip}:{d['port']}/",
                       "user": user, "password": pw}
                note = "ok" if url else "percorso RTSP non trovato: modifica l'URL"
            return cam, note

        try:
            with ThreadPoolExecutor(max_workers=4) as ex:
                self.q.put(("added", list(ex.map(one, sel))))
        except Exception as e:
            self.q.put(("error", str(e)))

    def added(self, res):
        self.on_add([c for c, _ in res])
        self.finish("Fatto.")
        righe = "\n".join(f"- {c['name']}: {n}" for c, n in res)
        messagebox.showinfo("Telecamere aggiunte", righe, parent=self)
        self.close()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "found":
                    self.show(data)
                elif kind == "added":
                    self.added(data)
                    return
                elif kind == "error":
                    self.finish(f"Errore: {data}")
        except queue.Empty:
            pass
        if self.busy:
            self.after(200, self.poll)


# ------------------------------------------------------------ interfaccia adattiva
def fit_geometry(win, w, h):
    """Dimensiona e centra una finestra in base allo schermo e alla scala DPI."""
    sc = win.winfo_fpixels("1i") / 96.0
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(int(w * sc), int(sw * 0.95)), min(int(h * sc), int(sh * 0.90))
    win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")


def autowrap(label):
    """Il testo va a capo in base alla larghezza reale della finestra."""
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(120, e.width - 8)))


def short_path(p, n=42):
    p = str(p)
    return p if len(p) <= n else "..." + p[-(n - 3):]


def best_grid(n, W, H, aspect=16 / 9):
    """Sceglie colonne/righe che danno i riquadri piu' grandi per la finestra attuale."""
    best = (1, n, -1.0)
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        w, h = W / cols, H / rows
        area = min(w, h * aspect) * min(h, w / aspect)
        if area > best[2]:
            best = (cols, rows, area)
    return best[0], best[1]


class FlowBar(ttk.Frame):
    """Barra di pulsanti che va a capo su piu' righe quando la finestra e' stretta."""

    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self._lastw = None
        self.bind("<Configure>", self._on_cfg)

    def add(self, widget):
        self.items.append(widget)
        self._lastw = None
        self.reflow(self.winfo_width())

    def _on_cfg(self, event):
        if event.width != self._lastw:
            self.reflow(event.width)

    def reflow(self, width):
        self._lastw = width
        if width <= 1:
            width = 1 << 30  # prima del primo disegno: tutto su una riga
        x = row = col = 0
        for w in self.items:
            rw = w.winfo_reqwidth() + 10
            if col and x + rw > width:
                row += 1
                col = x = 0
            w.grid(row=row, column=col, padx=4, pady=3, sticky="w")
            x += rw
            col += 1


# ---------------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION} - ONVIF / RTSP")
        fit_geometry(self, 1100, 700)
        self.minsize(400, 300)
        self.configure(bg="#111")

        bar = FlowBar(self)
        bar.pack(side="top", fill="x")
        bar.add(ttk.Button(bar, text="+ Aggiungi telecamera", command=self.add_cam))
        bar.add(ttk.Button(bar, text="Cerca telecamere", command=self.discover))
        bar.add(ttk.Button(bar, text="Schermo intero (F11)", command=self.toggle_fs))
        self.rec_var = tk.BooleanVar(value=bool(SETTINGS["rec_enabled"] and SETTINGS["rec_dir"]))
        SETTINGS["rec_enabled"] = self.rec_var.get()
        bar.add(ttk.Checkbutton(bar, text="Registra", variable=self.rec_var, command=self.toggle_rec))
        bar.add(ttk.Button(bar, text="Cartella registrazioni...", command=self.choose_dir))
        bar.add(ttk.Button(bar, text="Informazioni", command=self.about))

        status = ttk.Frame(self)
        status.pack(side="bottom", fill="x")
        ttk.Label(status, text=f"v{APP_VERSION} - {APP_AUTHOR}", foreground="#666").pack(side="right", padx=8)
        self.info = ttk.Label(status, text="", anchor="w")
        self.info.pack(side="left", fill="x", expand=True, padx=8, pady=2)

        self.container = tk.Frame(self, bg="#000")
        self.container.pack(fill="both", expand=True)
        self.container.grid_propagate(False)
        self.container.bind("<Configure>", self.on_resize)

        self.cams = self.load()
        self.workers = []
        self.labels = []
        self.focus_idx = None
        self.fullscreen = False

        self.menu = tk.Menu(self, tearoff=0)
        self.menu_idx = None

        self.bind("<F11>", lambda e: self.toggle_fs())
        self.bind("<Escape>", lambda e: self.toggle_fs(False))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.start_all()
        threading.Thread(target=self.cleanup_loop, daemon=True).start()
        self.after(200, self.tick)

    # ---- persistenza
    def load(self):
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            return []

    def save(self):
        CONFIG.write_text(json.dumps(self.cams, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- gestione telecamere
    def start_all(self):
        for r in getattr(self, "recorders", []):
            r.stop()
        for w in self.workers:
            w.stop()
        self.workers = [CamWorker(c) for c in self.cams]
        for w in self.workers:
            w.start()
        self.recorders = [HDRecorder(w) for w in self.workers] if FFMPEG else []
        for r in self.recorders:
            r.start()
        self.focus_idx = None
        self.rebuild_tiles()

    def add_cam(self):
        d = CamDialog(self).result
        if d:
            self.cams.append(d)
            self.save()
            self.start_all()

    def discover(self):
        DiscoveryDialog(self, self.cams, self.add_found)

    def add_found(self, new_cams):
        self.cams.extend(new_cams)
        self.save()
        self.start_all()

    def edit_cam(self, i):
        d = CamDialog(self, self.cams[i]).result
        if d:
            self.cams[i] = d
            self.save()
            self.start_all()

    def remove_cam(self, i):
        if messagebox.askyesno("Rimuovi", f"Rimuovere '{self.cams[i]['name']}'?"):
            del self.cams[i]
            self.save()
            self.start_all()

    # ---- UI
    def rebuild_tiles(self):
        for ch in self.container.winfo_children():
            ch.destroy()
        self.labels = []
        for i in range(len(self.workers)):
            lbl = tk.Label(self.container, bg="#000", bd=0)
            lbl.bind("<Double-Button-1>", lambda e, i=i: self.toggle_focus(i))
            lbl.bind("<Button-3>", lambda e, i=i: self.popup(e, i))
            lbl.bind("<Button-2>", lambda e, i=i: self.popup(e, i))  # macOS
            self.labels.append(lbl)
        self.layout_tiles()

    def layout_tiles(self):
        for lbl in self.labels:
            lbl.grid_forget()
        idxs = [self.focus_idx] if self.focus_idx is not None else list(range(len(self.labels)))
        n = len(idxs)
        if n == 0:
            return
        W, H = self.container.winfo_width(), self.container.winfo_height()
        if W < 50 or H < 50:
            W, H = 1100, 650
        cols, rows = best_grid(n, W, H)
        for c in range(20):
            self.container.columnconfigure(c, weight=0, uniform="")
            self.container.rowconfigure(c, weight=0, uniform="")
        for c in range(cols):
            self.container.columnconfigure(c, weight=1, uniform="c")
        for r in range(rows):
            self.container.rowconfigure(r, weight=1, uniform="r")
        for k, i in enumerate(idxs):
            self.labels[i].grid(row=k // cols, column=k % cols, sticky="nsew", padx=1, pady=1)
        self.grid_cols, self.grid_rows = cols, rows

    def on_resize(self, event=None):
        if getattr(self, "_rz", None):
            self.after_cancel(self._rz)
        self._rz = self.after(120, self._relayout)

    def _relayout(self):
        self._rz = None
        n = 1 if self.focus_idx is not None else len(self.labels)
        if n and best_grid(n, self.container.winfo_width(), self.container.winfo_height()) != (
                getattr(self, "grid_cols", 0), getattr(self, "grid_rows", 0)):
            self.layout_tiles()

    def toggle_focus(self, i):
        self.focus_idx = None if self.focus_idx == i else i
        self.layout_tiles()

    def popup(self, event, i):
        self.menu.delete(0, "end")
        self.menu.add_command(label="Ingrandisci / mosaico", command=lambda: self.toggle_focus(i))
        self.menu.add_command(label="Modifica", command=lambda: self.edit_cam(i))
        self.menu.add_command(label="Rimuovi", command=lambda: self.remove_cam(i))
        self.menu.tk_popup(event.x_root, event.y_root)

    def choose_dir(self):
        d = filedialog.askdirectory(
            title="Scegli disco / cartella per le registrazioni",
            initialdir=SETTINGS["rec_dir"] or str(Path.home()),
        )
        if not d:
            return False
        SETTINGS["rec_dir"] = d
        save_settings()
        messagebox.showinfo(
            "Registrazioni",
            f"Salvo in:\n{rec_root()}\n\nI file .mp4 in questa cartella piu' vecchi di "
            f"{SETTINGS['retention_hours']} ore vengono cancellati automaticamente.",
        )
        return True

    def toggle_rec(self):
        if self.rec_var.get() and not SETTINGS["rec_dir"]:
            if not self.choose_dir():
                self.rec_var.set(False)
        SETTINGS["rec_enabled"] = self.rec_var.get()
        if self.rec_var.get() and not FFMPEG:
            self.offer_ffmpeg()
        save_settings()

    def offer_ffmpeg(self):
        if not shutil.which("winget"):
            messagebox.showinfo("Registrazione a bassa risoluzione",
                                "ffmpeg non trovato: registro lo stream del mosaico (bassa risoluzione).\n\n"
                                "Per l'alta definizione installa ffmpeg e metti ffmpeg.exe accanto al programma.")
            return
        if not messagebox.askyesno("Registrazione in alta definizione",
                                   "Per registrare in alta definizione serve ffmpeg (gratuito).\n\n"
                                   "Installarlo ora? (1-2 minuti, serve internet)\n\n"
                                   "Se rispondi No, registro a bassa risoluzione."):
            return
        self.info.config(text="Installazione di ffmpeg in corso...")
        self.ff_job = {"done": False}

        def job(state):
            try:
                subprocess.run(["winget", "install", "-e", "--id", "Gyan.FFmpeg",
                                "--accept-package-agreements", "--accept-source-agreements"],
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=900,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                pass
            state["done"] = True

        threading.Thread(target=job, args=(self.ff_job,), daemon=True).start()

    def refresh_ffmpeg(self):
        global FFMPEG
        FFMPEG = find_ffmpeg()
        return FFMPEG

    def about(self):
        messagebox.showinfo(
            "Informazioni",
            f"{APP_NAME}\nVersione {APP_VERSION}\n\nCreato da {APP_AUTHOR}\nCopyright (C) 2026\n\n"
            "Visualizzatore di telecamere ONVIF / RTSP a mosaico,\n"
            "con registrazione e ricerca automatica in rete.\n\n"
            "Licenza: GPL-3.0-or-later (software libero, senza garanzia).\n"
            "Assistenza e funzioni premium: su accordo con l'autore.\n"
            "Condizioni d'uso complete: file CONDIZIONI_USO.txt\n"
            "nella cartella di installazione.",
        )

    def cleanup_loop(self):
        while True:
            cleanup_old()
            time.sleep(600)

    def toggle_fs(self, state=None):
        self.fullscreen = (not self.fullscreen) if state is None else state
        self.attributes("-fullscreen", self.fullscreen)

    def render(self, worker, tw, th):
        canvas = np.zeros((th, tw, 3), np.uint8)
        f = worker.frame
        if f is not None:
            h, w = f.shape[:2]
            s = min(tw / w, th / h)
            nw, nh = max(1, int(w * s)), max(1, int(h * s))
            small = cv2.resize(f, (nw, nh), interpolation=cv2.INTER_AREA)
            y, x = (th - nh) // 2, (tw - nw) // 2
            canvas[y:y + nh, x:x + nw] = small
        sc = max(0.45, min(1.3, tw / 640))  # testo proporzionale alla dimensione del riquadro
        y = int(12 + 12 * sc)
        label = worker.cam["name"] if worker.status == "OK" else f"{worker.cam['name']} - {worker.status}"
        cv2.putText(canvas, label, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55 * sc, (0, 0, 0), max(2, round(3 * sc)), cv2.LINE_AA)
        cv2.putText(canvas, label, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55 * sc, (255, 255, 255), max(1, round(sc)), cv2.LINE_AA)
        if worker.recording or worker.rec_hd:
            cv2.circle(canvas, (tw - int(14 * sc), y - int(4 * sc)), max(3, int(6 * sc)), (0, 0, 255), -1)
            cv2.putText(canvas, "REC", (tw - int(62 * sc), y), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * sc, (255, 255, 255), max(1, round(sc)), cv2.LINE_AA)
        return ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)))

    def tick(self):
        try:
            job = getattr(self, "ff_job", None)
            if job and job["done"]:
                self.ff_job = None
                if self.refresh_ffmpeg():
                    self.start_all()
                    messagebox.showinfo("ffmpeg", "ffmpeg installato: da ora registro in alta definizione.")
                else:
                    messagebox.showerror("ffmpeg", "Installazione di ffmpeg non riuscita: continuo a bassa risoluzione.")
            W, H = self.container.winfo_width(), self.container.winfo_height()
            if self.workers and W > 10 and H > 10:
                cols = getattr(self, "grid_cols", 1)
                rows = getattr(self, "grid_rows", 1)
                tw, th = max(16, W // cols - 2), max(16, H // rows - 2)
                idxs = [self.focus_idx] if self.focus_idx is not None else range(len(self.workers))
                for i in idxs:
                    img = self.render(self.workers[i], tw, th)
                    self.labels[i].configure(image=img)
                    self.labels[i].image = img
                ok = sum(1 for w in self.workers if w.status == "OK")
                rec = f" | REC {'HD' if FFMPEG else 'SD'}: {short_path(rec_root())}" if SETTINGS["rec_enabled"] and SETTINGS["rec_dir"] else ""
                self.info.config(text=f"{ok}/{len(self.workers)} telecamere online{rec}")
            elif not self.workers:
                self.info.config(text="Nessuna telecamera: clicca 'Aggiungi telecamera'")
        finally:
            self.after(int(1000 / FPS_UI), self.tick)

    def on_close(self):
        for r in getattr(self, "recorders", []):
            r.stop()
        for w in self.workers:
            w.stop()
        for w in self.workers:
            w.join(timeout=2)  # chiude i file video in modo pulito
        for r in getattr(self, "recorders", []):
            r.join(timeout=8)
        self.destroy()


def selftest():
    """Diagnostica: python MosaicoCamere.exe --selftest  ->  scrive selftest.txt nella cartella dati."""
    out = [f"{APP_NAME} {APP_VERSION} - {APP_AUTHOR}", f"Python {sys.version.split()[0]} (exe={getattr(sys, 'frozen', False)})",
           f"OpenCV {cv2.__version__}", f"Cartella dati: {APP_DIR}", f"ffmpeg: {FFMPEG}"]
    try:
        import onvif
        out.append(f"onvif wsdl: {find_wsdl() or 'MANCANTE'}")
        resolve_url({"type": "ONVIF", "host": "127.0.0.1", "port": "9", "user": "", "password": ""})
    except Exception as e:  # atteso: connessione rifiutata (non un errore di wsdl)
        out.append(f"onvif prova: {type(e).__name__}: {str(e)[:150]}")
    (APP_DIR / "selftest.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    if "--wsdl-path" in sys.argv:
        print(find_wsdl() or "")
        raise SystemExit(0)
    if "--selftest" in sys.argv:
        selftest()
        raise SystemExit(0)
    try:
        App().mainloop()
    except Exception:
        import traceback
        err = traceback.format_exc()
        print(err)
        (APP_DIR / "errore.log").write_text(err, encoding="utf-8")
        try:
            from tkinter import messagebox
            _r = tk.Tk()
            _r.withdraw()
            messagebox.showerror("Errore", f"{err[-800:]}\n\n(salvato in {APP_DIR / 'errore.log'})")
        except Exception:
            pass
        if sys.stdin:
            input("\nErrore (salvato in errore.log). Premi Invio per chiudere...")
