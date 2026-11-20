"""
Transcriptor de entrevistas y reuniones.
Gratis: usa Whisper (faster-whisper) y corre completo en tu computadora.
El audio nunca sale de tu maquina.

Uso: pon tus audios en la carpeta "grabaciones" y haz doble clic en transcribir.bat
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

CARPETA = Path(__file__).resolve().parent
ENTRADA = CARPETA / "grabaciones"
SALIDA = CARPETA / "transcripciones"
VOCABULARIO = CARPETA / "vocabulario.txt"

EXTENSIONES = {".m4a", ".mp3", ".wav", ".ogg", ".opus", ".aac", ".flac",
               ".mp4", ".webm", ".3gp", ".amr", ".wma", ".mkv", ".mov"}

MODELOS = {
    "1": ("small", "Rapido (buena calidad, 1 hora de audio tarda aprox. 10 a 20 min)"),
    "2": ("large-v3-turbo", "Preciso (mejor calidad, 1 hora de audio tarda aprox. 30 a 60 min)"),
}

IDIOMAS = {
    "1": (None, "Detectar automaticamente"),
    "2": ("en", "Ingles"),
    "3": ("es", "Espanol"),
}


def formato_tiempo(segundos: float) -> str:
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def leer_vocabulario() -> str | None:
    """Lee palabras clave (nombres, empresas, terminos) para que Whisper las escriba bien."""
    if not VOCABULARIO.exists():
        return None
    palabras = []
    for linea in VOCABULARIO.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#"):
            palabras.append(linea)
    texto = ", ".join(palabras)
    return texto[:600] or None  # Whisper solo acepta un texto corto aqui


def elegir(titulo: str, opciones: dict, defecto: str):
    print(f"\n{titulo}")
    for clave, (_, descripcion) in opciones.items():
        marca = "  (recomendado)" if clave == defecto else ""
        print(f"  {clave}. {descripcion}{marca}")
    respuesta = input(f"Escribe el numero y presiona Enter [{defecto}]: ").strip() or defecto
    if respuesta not in opciones:
        print(f"Opcion no valida, uso la {defecto}.")
        respuesta = defecto
    return opciones[respuesta][0]


def transcribir_archivo(modelo, archivo: Path, idioma, vocabulario, nombre_modelo: str):
    destino = SALIDA / f"{archivo.stem}.txt"
    parcial = SALIDA / f"{archivo.stem}.parcial.txt"
    inicio = time.time()

    print(f"\n=== Transcribiendo: {archivo.name} ===")
    segmentos, info = modelo.transcribe(
        str(archivo),
        language=idioma,
        beam_size=5,
        vad_filter=True,                     # ignora silencios largos
        condition_on_previous_text=False,    # evita que repita frases en audios largos
        hotwords=vocabulario,                # ayuda a escribir bien nombres y terminos
    )
    duracion = info.duration or 1

    print(f"Idioma detectado: {info.language}  |  Duracion: {formato_tiempo(duracion)}")

    with parcial.open("w", encoding="utf-8") as f:
        f.write(f"Archivo: {archivo.name}\n")
        f.write(f"Transcrito: {datetime.now():%Y-%m-%d %H:%M}\n")
        f.write(f"Duracion: {formato_tiempo(duracion)}  |  Idioma: {info.language}  |  Modelo: {nombre_modelo}\n")
        f.write("=" * 70 + "\n\n")
        for seg in segmentos:
            texto = seg.text.strip()
            if not texto:
                continue
            linea = f"[{formato_tiempo(seg.start)}] {texto}"
            f.write(linea + "\n")
            f.flush()
            avance = min(100.0, seg.end / duracion * 100)
            print(f"{avance:5.1f}%  {linea}")

    if destino.exists():
        destino.unlink()
    parcial.rename(destino)
    minutos = (time.time() - inicio) / 60
    print(f"\nListo en {minutos:.1f} minutos. Guardado en: transcripciones\\{destino.name}")


def main():
    ENTRADA.mkdir(exist_ok=True)
    SALIDA.mkdir(exist_ok=True)

    pendientes = [
        f for f in sorted(ENTRADA.iterdir())
        if f.is_file() and f.suffix.lower() in EXTENSIONES
        and not (SALIDA / f"{f.stem}.txt").exists()
    ]

    if not pendientes:
        print("No hay grabaciones nuevas.")
        print('Copia tus audios a la carpeta "grabaciones" y vuelve a ejecutar.')
        return

    print("Grabaciones por transcribir:")
    for f in pendientes:
        print(f"  * {f.name}")

    nombre_modelo = elegir("Que calidad quieres?", MODELOS, "1")
    idioma = elegir("En que idioma es la grabacion?", IDIOMAS, "1")
    vocabulario = leer_vocabulario()

    print("\nCargando el modelo de transcripcion...")
    print("(La primera vez se descarga de internet y puede tardar varios minutos. Despues ya no.)")
    from faster_whisper import WhisperModel

    modelo = WhisperModel(nombre_modelo, device="cpu", compute_type="int8",
                          cpu_threads=os.cpu_count() or 4)

    for archivo in pendientes:
        try:
            transcribir_archivo(modelo, archivo, idioma, vocabulario, nombre_modelo)
        except Exception as error:  # sigue con el siguiente archivo si uno falla
            print(f"\nNo pude transcribir {archivo.name}: {error}")

    print("\nTodo terminado. Abre la carpeta \"transcripciones\" para ver los textos.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.")
        sys.exit(1)
