"""
Separacion de voces (quien habla y cuando), gratis y en tu computadora.
Usa sherpa-onnx. La primera vez instala la libreria y descarga dos modelos pequenos.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

CARPETA = Path(__file__).resolve().parent
MODELOS = CARPETA / "modelos"
SEGMENTACION = MODELOS / "sherpa-onnx-pyannote-segmentation-3-0" / "model.int8.onnx"
HUELLA_VOZ = MODELOS / "nemo_en_titanet_small.onnx"

URL_SEGMENTACION = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
URL_HUELLA_VOZ = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                  "speaker-recongition-models/nemo_en_titanet_small.onnx")
SIN_VENTANA = 0x08000000


def _python() -> str:
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    return str(python)


def _sin_ventana():
    return {"creationflags": SIN_VENTANA} if os.name == "nt" else {}


def leer_audio(ruta: str):
    """Lee cualquier audio/video y lo deja en mono, 16 kHz, numeros decimales."""
    import av
    import numpy as np
    partes = []
    with av.open(ruta) as contenedor:
        conversor = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for cuadro in contenedor.decode(audio=0):
            for c in conversor.resample(cuadro):
                partes.append(c.to_ndarray().reshape(-1))
        for c in conversor.resample(None):
            partes.append(c.to_ndarray().reshape(-1))
    return np.concatenate(partes).astype(np.float32) / 32768.0


def separar_archivo(archivo, personas: int, avisar):
    """Corre la separacion de voces en un proceso aparte y devuelve los tramos."""
    salida = Path(tempfile.gettempdir()) / f"voces_{os.getpid()}.json"
    proceso = subprocess.Popen(
        [_python(), str(Path(__file__).resolve()), str(archivo), str(personas), str(salida)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore",
        **_sin_ventana())
    for linea in proceso.stdout:
        if linea.startswith("AVANCE "):
            try:
                avisar("avance_voces", float(linea.split()[1]))
            except ValueError:
                pass
    error = proceso.stderr.read()
    if proceso.wait() != 0 or not salida.exists():
        raise RuntimeError("La separación de voces falló: " + (error.strip().splitlines() or ["sin detalle"])[-1])
    tramos = [tuple(t) for t in json.loads(salida.read_text(encoding="utf-8"))]
    salida.unlink(missing_ok=True)
    return tramos


def _descargar(url: str, destino: Path, avisar, texto: str):
    temporal = destino.with_suffix(destino.suffix + ".parcial")
    with urllib.request.urlopen(url, timeout=60) as r, temporal.open("wb") as f:
        total = int(r.headers.get("Content-Length", 0)) or 1
        hecho = 0
        while True:
            bloque = r.read(1 << 20)
            if not bloque:
                break
            f.write(bloque)
            hecho += len(bloque)
            avisar("estado", f"{texto} {min(100, hecho * 100 // total)}%")
    temporal.replace(destino)


def preparar(avisar):
    """Instala sherpa-onnx y descarga los modelos si faltan (solo la primera vez)."""
    # ojo: NO importar sherpa_onnx aqui (choca con Whisper si se cargan en el mismo programa)
    if importlib.util.find_spec("sherpa_onnx") is None:
        avisar("estado", "Instalando la separación de voces (solo la primera vez, 1 a 2 min)...")
        subprocess.run([_python(), "-m", "pip", "install", "--only-binary=:all:", "sherpa-onnx"],
                       check=True, capture_output=True, **_sin_ventana())
    MODELOS.mkdir(exist_ok=True)
    if not SEGMENTACION.exists():
        paquete = MODELOS / "segmentacion.tar.bz2"
        _descargar(URL_SEGMENTACION, paquete, avisar, "Descargando modelo de voces (1 de 2)...")
        with tarfile.open(paquete, "r:bz2") as t:
            t.extractall(MODELOS, filter="data")
        paquete.unlink(missing_ok=True)
    if not HUELLA_VOZ.exists():
        _descargar(URL_HUELLA_VOZ, HUELLA_VOZ, avisar, "Descargando modelo de voces (2 de 2)...")


def separar(audio, personas: int, avisar):
    """
    audio: numpy float32 mono a 16 kHz. personas: 0 = automatico, o el numero exacto.
    Devuelve una lista de (inicio, fin, numero_de_hablante) ordenada en el tiempo.
    """
    import sherpa_onnx

    hilos = max(1, (os.cpu_count() or 4))
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(SEGMENTACION)),
            num_threads=hilos,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(HUELLA_VOZ), num_threads=hilos),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=personas if personas > 0 else -1,
                                                    threshold=0.9),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError("La configuración de separación de voces no es válida.")
    separador = sherpa_onnx.OfflineSpeakerDiarization(config)

    def progreso(hecho, total):
        avisar("avance_voces", hecho * 100.0 / max(total, 1))
        return 0

    resultado = separador.process(audio, callback=progreso).sort_by_start_time()
    tramos = [(s.start, s.end, s.speaker) for s in resultado]

    # renumerar por orden de aparicion: el primero que habla es "Hablante 1"
    orden = {}
    for _, _, h in tramos:
        orden.setdefault(h, len(orden) + 1)
    return [(a, b, orden[h]) for a, b, h in tramos]


def hablante_en(tramos, momento: float):
    """Quien habla en un momento dado (o el tramo mas cercano)."""
    mejor, distancia = None, float("inf")
    for a, b, h in tramos:
        if a <= momento <= b:
            return h
        d = a - momento if momento < a else momento - b
        if d < distancia:
            mejor, distancia = h, d
    return mejor


if __name__ == "__main__":
    # Modo "proceso aparte": python voces.py <audio> <personas> <salida.json>
    ruta, personas, destino = sys.argv[1], int(sys.argv[2]), sys.argv[3]

    def _aviso(tipo, dato):
        if tipo == "avance_voces":
            print(f"AVANCE {dato:.1f}", flush=True)

    audio = leer_audio(ruta)
    resultado = separar(audio, personas, _aviso)
    Path(destino).write_text(json.dumps(resultado), encoding="utf-8")
