"""
Transcriptor de entrevistas: version con ventana.
Eliges una grabacion, se copia a "grabaciones", se transcribe con Whisper
en tu computadora y se guarda en "transcripciones" como Word (.docx) y texto (.txt).
"""

import os
import queue
import re
import shutil
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

CARPETA = Path(__file__).resolve().parent
ENTRADA = CARPETA / "grabaciones"
SALIDA = CARPETA / "transcripciones"
VOCABULARIO = CARPETA / "vocabulario.txt"

TIPOS_AUDIO = [
    ("Grabaciones", "*.mp4 *.m4a *.mp3 *.wav *.ogg *.opus *.aac *.flac *.webm *.3gp *.amr *.wma *.mkv *.mov"),
    ("Todos los archivos", "*.*"),
]


# ---------------------------------------------------------------- utilidades

def formato_tiempo(segundos: float) -> str:
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def leer_vocabulario():
    if not VOCABULARIO.exists():
        return None
    palabras = [l.strip() for l in VOCABULARIO.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.strip().startswith("#")]
    return ", ".join(palabras)[:600] or None


def copiar_a_grabaciones(origen: Path) -> Path:
    """Copia la grabacion a la carpeta 'grabaciones' (si ya esta ahi, no hace nada)."""
    ENTRADA.mkdir(exist_ok=True)
    if origen.resolve().parent == ENTRADA.resolve():
        return origen
    destino = ENTRADA / origen.name
    if destino.exists() and destino.stat().st_size == origen.stat().st_size:
        return destino  # ya estaba copiada
    n = 2
    while destino.exists():
        destino = ENTRADA / f"{origen.stem} ({n}){origen.suffix}"
        n += 1
    shutil.copy2(origen, destino)
    return destino


def guardar_docx(ruta: Path, titulo: str, encabezado: list[str], lineas: list[str]):
    """Crea un archivo Word sencillo sin necesitar programas extra."""
    def parrafo(texto, negrita=False, tam=None, color=None):
        props = ""
        if negrita or tam or color:
            props = "<w:rPr>"
            if negrita:
                props += "<w:b/>"
            if color:
                props += f'<w:color w:val="{color}"/>'
            if tam:
                props += f'<w:sz w:val="{tam}"/>'
            props += "</w:rPr>"
        return (f'<w:p><w:r>{props}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r></w:p>')

    colores = ["1F4E79", "C55A11", "375623", "7030A0", "C00060", "806000"]

    def corrida(texto, color=None, negrita=False, tam=None):
        props = ""
        if color or negrita or tam:
            props = "<w:rPr>" + ("<w:b/>" if negrita else "") + (f'<w:color w:val="{color}"/>' if color else "") \
                    + (f'<w:sz w:val="{tam}"/>' if tam else "") + "</w:rPr>"
        return f'<w:r>{props}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'

    def separar_linea(linea):
        """'[00:01:23] Hablante 2: texto' -> ('00:01:23', 2, 'texto')."""
        tiempo, texto, quien, palabra = "", linea, None, "Hablante"
        if linea.startswith("[") and "] " in linea:
            tiempo, texto = linea[1:].split("] ", 1)
        m = re.match(r"(Hablante|Speaker) (\d+): (.*)", texto)
        if m:
            palabra, quien, texto = m.group(1), int(m.group(2)), m.group(3)
        return tiempo, quien, texto, palabra

    cuerpo = parrafo(titulo, negrita=True, tam=32)
    cuerpo += "".join(parrafo(t, color="595959", tam=20) for t in encabezado)
    cuerpo += parrafo("")
    anterior = object()
    for linea in lineas:
        tiempo, quien, texto, palabra = separar_linea(linea)
        if quien is None:
            cuerpo += f'<w:p>{corrida(tiempo + "  ", "808080") if tiempo else ""}{corrida(texto)}</w:p>'
            continue
        if quien != anterior:  # nuevo bloque: nombre del hablante en color
            color = colores[(quien - 1) % len(colores)]
            cuerpo += ('<w:p><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="40"/></w:pPr>'
                       f'{corrida(f"{palabra} {quien}", color, True)}{corrida("   " + tiempo, "8C8C8C", tam=18)}</w:p>')
            anterior = quien
        cuerpo += f'<w:p><w:pPr><w:spacing w:after="60"/></w:pPr>{corrida(texto)}</w:p>'

    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{cuerpo}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        '</w:body></w:document>'
    )
    tipos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    relaciones = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", relaciones)
        z.writestr("word/document.xml", documento)


# ---------------------------------------------------------------- transcripcion

_modelos = {}


def transcribir(archivo: Path, nombre_modelo: str, idioma, avisar, voces=None, ui="es"):
    """
    Corre en segundo plano. 'avisar(tipo, dato)' manda mensajes a la ventana.
    voces: None = no separar voces; 0 = detectar cuantas personas; 2, 3... = numero exacto.
    """
    inicio = time.time()
    separar = voces is not None
    en = ui == "en"  # idioma de las etiquetas del Word y del texto
    etiqueta = "Speaker" if en else "Hablante"
    peso_voces = 30.0 if separar else 0.0  # parte de la barra que ocupa la separacion de voces

    if nombre_modelo not in _modelos:
        avisar("estado", "Cargando el modelo... (la primera vez se descarga y tarda unos minutos)")
        from faster_whisper import WhisperModel
        _modelos[nombre_modelo] = WhisperModel(nombre_modelo, device="cpu", compute_type="int8",
                                               cpu_threads=os.cpu_count() or 4)
    modelo = _modelos[nombre_modelo]

    entrada = str(archivo)
    tramos = []
    if separar:
        import voces as mod_voces
        mod_voces.preparar(avisar)
        avisar("estado", "Separando voces...")

        def aviso_voces(tipo, dato):
            if tipo == "avance_voces":
                avisar("avance", dato * peso_voces / 100)
            else:
                avisar(tipo, dato)
        tramos = mod_voces.separar_archivo(archivo, voces, aviso_voces)
        n = len({h for _, _, h in tramos})
        avisar("estado", f"Encontré {n} voces. Transcribiendo...")
    else:
        avisar("estado", "Transcribiendo...")

    segmentos, info = modelo.transcribe(
        entrada, language=idioma, beam_size=5, vad_filter=True,
        condition_on_previous_text=False, hotwords=leer_vocabulario(),
        word_timestamps=separar,
    )
    duracion = info.duration or 1
    lineas = []

    def agregar(t0, texto, quien=None):
        texto = texto.strip()
        if not texto:
            return
        linea = f"[{formato_tiempo(t0)}] " + (f"{etiqueta} {quien}: " if quien else "") + texto
        lineas.append(linea)
        avisar("linea", linea)

    for seg in segmentos:
        if separar and tramos and seg.words:
            # parte la frase si cambia la persona que habla a mitad
            actual, inicio_tramo, palabras = None, seg.start, []
            for w in seg.words:
                quien = mod_voces.hablante_en(tramos, (w.start + w.end) / 2)
                if actual is not None and quien != actual and palabras:
                    agregar(inicio_tramo, "".join(palabras), actual)
                    palabras, inicio_tramo = [], w.start
                actual = quien
                palabras.append(w.word)
            agregar(inicio_tramo, "".join(palabras), actual)
        else:
            agregar(seg.start, seg.text)
        avisar("avance", peso_voces + min(100.0, seg.end / duracion * 100) * (100 - peso_voces) / 100)

    SALIDA.mkdir(exist_ok=True)
    detalle_voces = (f"  |  {'Speakers' if en else 'Voces'}: {len({h for _, _, h in tramos})}" if separar else "")
    encabezado = [
        f"{'File' if en else 'Archivo'}: {archivo.name}",
        f"{'Transcribed' if en else 'Transcrito'}: {datetime.now():%Y-%m-%d %H:%M}",
        f"{'Duration' if en else 'Duracion'}: {formato_tiempo(duracion)}  |  {'Language' if en else 'Idioma'}: {info.language}"
        f"  |  {'Model' if en else 'Modelo'}: {nombre_modelo}{detalle_voces}",
    ]
    txt = SALIDA / f"{archivo.stem}.txt"
    txt.write_text("\n".join(encabezado) + "\n" + "=" * 70 + "\n\n" + "\n".join(lineas) + "\n",
                   encoding="utf-8")
    docx = SALIDA / f"{archivo.stem}.docx"
    guardar_docx(docx, archivo.stem, encabezado, lineas)

    minutos = (time.time() - inicio) / 60
    avisar("fin", (docx, minutos))


# ---------------------------------------------------------------- ventana

class App:
    def __init__(self, raiz: tk.Tk):
        self.raiz = raiz
        self.archivo = None
        self.resultado = None
        self.mensajes = queue.Queue()

        raiz.title("Transcriptor de entrevistas")
        raiz.geometry("760x600")
        raiz.minsize(620, 480)

        marco = ttk.Frame(raiz, padding=16)
        marco.pack(fill="both", expand=True)

        ttk.Label(marco, text="Transcriptor de entrevistas",
                  font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(marco, text="Todo se procesa en tu computadora. El audio no sale de tu Surface.",
                  foreground="#666").pack(anchor="w", pady=(0, 12))

        fila = ttk.Frame(marco)
        fila.pack(fill="x")
        self.btn_elegir = ttk.Button(fila, text="Elegir grabación...", command=self.elegir)
        self.btn_elegir.pack(side="left")
        self.lbl_archivo = ttk.Label(fila, text="Ninguna grabación elegida", foreground="#666")
        self.lbl_archivo.pack(side="left", padx=12)

        opciones = ttk.Frame(marco)
        opciones.pack(fill="x", pady=12)

        self.calidad = tk.StringVar(value="small")
        caja1 = ttk.LabelFrame(opciones, text="Calidad", padding=8)
        caja1.pack(side="left", fill="y")
        ttk.Radiobutton(caja1, text="Rápida (1 hora tarda aprox. 10 a 20 min)",
                        variable=self.calidad, value="small").pack(anchor="w")
        ttk.Radiobutton(caja1, text="Precisa (1 hora tarda aprox. 30 a 60 min)",
                        variable=self.calidad, value="large-v3-turbo").pack(anchor="w")

        self.idioma = tk.StringVar(value="auto")
        caja2 = ttk.LabelFrame(opciones, text="Idioma", padding=8)
        caja2.pack(side="left", fill="y", padx=12)
        for texto, valor in [("Automático", "auto"), ("Inglés", "en"), ("Español", "es")]:
            ttk.Radiobutton(caja2, text=texto, variable=self.idioma, value=valor).pack(anchor="w")

        self.btn_transcribir = ttk.Button(marco, text="Transcribir", command=self.iniciar,
                                          state="disabled")
        self.btn_transcribir.pack(anchor="w")

        self.barra = ttk.Progressbar(marco, maximum=100)
        self.barra.pack(fill="x", pady=(12, 4))
        self.lbl_estado = ttk.Label(marco, text="")
        self.lbl_estado.pack(anchor="w")

        self.texto = ScrolledText(marco, height=12, wrap="word", font=("Segoe UI", 10))
        self.texto.pack(fill="both", expand=True, pady=8)

        finales = ttk.Frame(marco)
        finales.pack(fill="x")
        self.btn_word = ttk.Button(finales, text="Abrir transcripción en Word",
                                   command=self.abrir_word, state="disabled")
        self.btn_word.pack(side="left")
        ttk.Button(finales, text="Abrir carpeta de transcripciones",
                   command=lambda: self.abrir(SALIDA)).pack(side="left", padx=8)

        self.raiz.after(150, self.revisar_mensajes)

    # acciones
    def elegir(self):
        ruta = filedialog.askopenfilename(title="Elige la grabación", filetypes=TIPOS_AUDIO)
        if not ruta:
            return
        self.archivo = Path(ruta)
        self.lbl_archivo.config(text=self.archivo.name, foreground="#000")
        self.btn_transcribir.config(state="normal")
        self.btn_word.config(state="disabled")

    def iniciar(self):
        if not self.archivo or not self.archivo.exists():
            messagebox.showerror("Transcriptor", "No encuentro la grabación. Elígela de nuevo.")
            return
        if (SALIDA / f"{self.archivo.stem}.docx").exists():
            if not messagebox.askyesno("Transcriptor",
                                       "Esta grabación ya tiene transcripción.\n¿Quieres hacerla de nuevo?"):
                return
        try:
            self.lbl_estado.config(text="Copiando la grabación a la carpeta 'grabaciones'...")
            self.raiz.update_idletasks()
            copia = copiar_a_grabaciones(self.archivo)
        except Exception as error:
            messagebox.showerror("Transcriptor", f"No pude copiar la grabación:\n{error}")
            return

        self.texto.delete("1.0", "end")
        self.barra["value"] = 0
        self.bloquear(True)
        idioma = None if self.idioma.get() == "auto" else self.idioma.get()
        hilo = threading.Thread(target=self.trabajo, args=(copia, self.calidad.get(), idioma),
                                daemon=True)
        hilo.start()

    def trabajo(self, archivo, modelo, idioma):
        try:
            transcribir(archivo, modelo, idioma, lambda t, d: self.mensajes.put((t, d)))
        except Exception as error:
            self.mensajes.put(("error", str(error)))

    def revisar_mensajes(self):
        try:
            while True:
                tipo, dato = self.mensajes.get_nowait()
                if tipo == "estado":
                    self.lbl_estado.config(text=dato)
                elif tipo == "linea":
                    self.texto.insert("end", dato + "\n")
                    self.texto.see("end")
                elif tipo == "avance":
                    self.barra["value"] = dato
                    self.lbl_estado.config(text=f"Transcribiendo... {dato:.0f}%")
                elif tipo == "fin":
                    docx, minutos = dato
                    self.resultado = docx
                    self.barra["value"] = 100
                    self.lbl_estado.config(text=f"Listo en {minutos:.1f} min. Guardado como {docx.name}")
                    self.bloquear(False)
                    self.btn_word.config(state="normal")
                elif tipo == "error":
                    self.bloquear(False)
                    self.lbl_estado.config(text="Hubo un error.")
                    messagebox.showerror("Transcriptor", f"No pude transcribir:\n{dato}")
        except queue.Empty:
            pass
        self.raiz.after(150, self.revisar_mensajes)

    def bloquear(self, ocupado: bool):
        estado = "disabled" if ocupado else "normal"
        self.btn_elegir.config(state=estado)
        self.btn_transcribir.config(state=estado)

    def abrir_word(self):
        if self.resultado:
            self.abrir(self.resultado)

    @staticmethod
    def abrir(ruta: Path):
        ruta.mkdir(exist_ok=True) if ruta.suffix == "" else None
        try:
            os.startfile(ruta)  # solo existe en Windows
        except AttributeError:
            print(f"Abre manualmente: {ruta}")


if __name__ == "__main__":
    raiz = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(raiz)
    raiz.mainloop()
