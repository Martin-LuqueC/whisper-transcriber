"""
Transcriptor de audio: version con interfaz moderna.
Abre una pagina en tu navegador, pero todo corre en tu computadora (localhost).
No necesita internet ni programas extra. Reutiliza el motor de app.py.
"""

import base64
import json
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import app as motor  # funciones de transcripcion y Word

CARPETA = Path(__file__).resolve().parent
PAGINA = CARPETA / "interfaz.html"
ICONO_PNG = CARPETA / "icono.png"
ICONO_ICO = CARPETA / "transcriptor.ico"
SIN_VENTANA = 0x08000000  # para que Windows no muestre una consola negra
EXT_AUDIO = {".m4a", ".mp3", ".wav", ".ogg", ".opus", ".aac", ".flac", ".mp4",
             ".webm", ".3gp", ".amr", ".wma", ".mkv", ".mov"}

estado = {"fase": "libre", "archivo": None, "avance": 0.0, "lineas": [], "mensaje": "",
          "resultado": None, "minutos": None, "error": None}
candado = threading.Lock()
ultimo_contacto = time.time()


def nombre_libre(nombre: str, tamano: int) -> Path:
    """Devuelve donde guardar la grabacion (reusa si ya existe igual)."""
    motor.ENTRADA.mkdir(exist_ok=True)
    nombre = Path(nombre).name.replace("/", "_").replace("\\", "_") or "grabacion.m4a"
    destino = motor.ENTRADA / nombre
    if destino.exists() and destino.stat().st_size == tamano:
        return destino
    base, ext, n = destino.stem, destino.suffix, 2
    while destino.exists():
        destino = motor.ENTRADA / f"{base} ({n}){ext}"
        n += 1
    return destino


def historial():
    motor.SALIDA.mkdir(exist_ok=True)
    items = []
    for f in sorted(motor.SALIDA.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
        info = ""
        txt = f.with_suffix(".txt")
        if txt.exists():
            for linea in txt.read_text(encoding="utf-8", errors="ignore").splitlines()[:4]:
                if linea.startswith(("Duracion:", "Duration:")):
                    info = linea.split("|")[0].split(":", 1)[1].strip()
        items.append({"nombre": f.stem, "fecha": time.strftime("%d/%m/%Y %H:%M", time.localtime(f.stat().st_mtime)),
                      "duracion": info})
    return items


def trabajo(archivo: Path, modelo: str, idioma, voces, ui="es"):
    def avisar(tipo, dato):
        with candado:
            if tipo == "estado":
                estado["mensaje"] = dato
            elif tipo == "linea":
                estado["lineas"].append(dato)
            elif tipo == "avance":
                estado["avance"] = round(dato, 1)
            elif tipo == "fin":
                docx, minutos = dato
                estado.update(fase="listo", resultado=docx.stem, minutos=round(minutos, 1), avance=100.0,
                              mensaje="Transcripción lista")
    try:
        motor.transcribir(archivo, modelo, idioma, avisar, voces, ui)
    except Exception as error:
        import traceback
        traceback.print_exc()
        with candado:
            estado.update(fase="error", error=str(error), mensaje="Hubo un error")


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def responder(self, cuerpo, tipo="application/json", codigo=200):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        global ultimo_contacto
        ultimo_contacto = time.time()
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/":
            self.responder(PAGINA.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/icono.png" and ICONO_PNG.exists():
            self.responder(ICONO_PNG.read_bytes(), "image/png")
        elif url.path == "/estado":
            desde = int(q.get("desde", ["0"])[0])
            with candado:
                copia = dict(estado)
                copia["lineas"] = estado["lineas"][desde:]
                copia["total"] = len(estado["lineas"])
            self.responder(copia)
        elif url.path == "/historial":
            self.responder(historial())
        elif url.path == "/abrir":
            nombre = Path(q.get("nombre", [""])[0]).name
            tipo = q.get("tipo", ["docx"])[0]
            if tipo == "carpeta":
                ruta = motor.SALIDA
            else:
                ruta = motor.SALIDA / f"{nombre}.{'txt' if tipo == 'txt' else 'docx'}"
            if ruta.exists() and hasattr(os, "startfile"):
                os.startfile(ruta)
            self.responder({"ok": ruta.exists()})
        else:
            self.responder({"error": "no existe"}, codigo=404)

    def do_POST(self):
        global ultimo_contacto
        ultimo_contacto = time.time()
        url = urlparse(self.path)
        if url.path == "/subir":
            nombre = unquote(self.headers.get("X-Nombre", "grabacion.m4a"))
            tamano = int(self.headers.get("Content-Length", "0"))
            if Path(nombre).suffix.lower() not in EXT_AUDIO:
                self.rfile.read(tamano)
                return self.responder({"error": "Ese tipo de archivo no es una grabación."}, codigo=400)
            destino = nombre_libre(nombre, tamano)
            pendiente = tamano
            if destino.exists():  # ya estaba copiada
                while pendiente > 0:
                    pendiente -= len(self.rfile.read(min(1 << 20, pendiente)))
            else:
                with destino.open("wb") as f:
                    while pendiente > 0:
                        bloque = self.rfile.read(min(1 << 20, pendiente))
                        if not bloque:
                            break
                        f.write(bloque)
                        pendiente -= len(bloque)
            ya = (motor.SALIDA / f"{destino.stem}.docx").exists()
            self.responder({"archivo": destino.name, "yaTranscrita": ya})
        elif url.path == "/iniciar":
            datos = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            archivo = motor.ENTRADA / Path(datos.get("archivo", "")).name
            if not archivo.exists():
                return self.responder({"error": "No encuentro la grabación."}, codigo=400)
            with candado:
                if estado["fase"] == "trabajando":
                    return self.responder({"error": "Ya hay una transcripción en curso."}, codigo=409)
                estado.update(fase="trabajando", archivo=archivo.name, avance=0.0, lineas=[], resultado=None,
                              minutos=None, error=None, mensaje="Preparando...")
            modelo = "large-v3-turbo" if datos.get("calidad") == "precisa" else "small"
            idioma = datos.get("idioma") if datos.get("idioma") in ("en", "es") else None
            voces = {"no": None, "auto": 0, "2": 2, "3": 3, "4": 4}.get(str(datos.get("voces", "auto")), 0)
            ui = "en" if datos.get("ui") == "en" else "es"
            threading.Thread(target=trabajo, args=(archivo, modelo, idioma, voces, ui), daemon=True).start()
            self.responder({"ok": True})
        elif url.path == "/cerrar":
            self.responder({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self.responder({"error": "no existe"}, codigo=404)


def vigilante(servidor):
    """
    Apaga el programa solo si la ventana lleva 30 minutos sin dar senales y no hay nada
    transcribiendo. (Edge "duerme" las ventanas en segundo plano, por eso el margen es amplio.)
    """
    while True:
        time.sleep(30)
        with candado:
            ocupado = estado["fase"] == "trabajando"
        if not ocupado and time.time() - ultimo_contacto > 30 * 60:
            servidor.shutdown()
            return


def buscar_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            ruta = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if ruta.exists():
                return ruta
    return None


def abrir_ventana(url: str):
    """Abre la interfaz como aplicacion (ventana propia de Edge, sin pestanas)."""
    edge = buscar_edge()
    if edge:
        try:
            subprocess.Popen([str(edge), f"--app={url}", "--window-size=1320,960"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def crear_acceso_directo():
    """Crea 'Transcriptor' en el escritorio la primera vez (solo Windows)."""
    if os.name != "nt":
        return
    pythonw = CARPETA / "venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        return
    q = lambda r: str(r).replace("'", "''")
    comando = (
        "$e=[Environment]::GetFolderPath('Desktop');"
        "$l=Join-Path $e 'Transcriptor.lnk';"
        "if(-not (Test-Path $l)){"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($l);"
        f"$s.TargetPath='{q(pythonw)}';"
        f"$s.Arguments='\"{q(CARPETA / 'app_web.py')}\"';"
        f"$s.WorkingDirectory='{q(CARPETA)}';"
        f"$s.IconLocation='{q(ICONO_ICO)}';"
        "$s.Description='Transcriptor de audio';"
        "$s.Save()}"
    )
    try:
        codificado = base64.b64encode(comando.encode("utf-16-le")).decode()
        subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", codificado],
                       creationflags=SIN_VENTANA, timeout=30)
    except Exception:
        pass  # si falla, el programa funciona igual


def registro():
    """Guarda cualquier error (incluso si el programa se cierra de golpe) en registro.txt."""
    try:
        f = open(CARPETA / "registro.txt", "a", encoding="utf-8", buffering=1)
        f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} inicio =====\n")
        os.dup2(f.fileno(), 2)
        import sys
        sys.stderr = f
        import faulthandler
        faulthandler.enable(f)
    except Exception:
        pass


def main():
    registro()
    servidor = None
    for puerto in range(8765, 8785):
        try:
            servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
            break
        except OSError:
            continue
    if servidor is None:
        raise SystemExit("No encontre un puerto libre.")
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    threading.Thread(target=vigilante, args=(servidor,), daemon=True).start()
    threading.Timer(0.6, lambda: abrir_ventana(url)).start()
    threading.Thread(target=crear_acceso_directo, daemon=True).start()
    servidor.serve_forever()


if __name__ == "__main__":
    main()
