#!/usr/bin/env python3
"""
Cliente de la API REST del controlador (historia PCIII-19).

La usan los escenarios y las pruebas para cambiar el clasificador de Ryu sin
reiniciarlo. Solo usa la biblioteca estándar: funciona con el Python del
sistema (sudo python3) y con el del .venv.

  python3 controlador/api.py estado
  python3 controlador/api.py clasificador politica
  python3 controlador/api.py clasificador ninguno
"""
import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8080"
AVISO = ("No responde la API del controlador en {url}. Enciende la aplicación del proyecto "
         "(no simple_switch_13):\n  cd ~/qos-adaptativa && source .venv/bin/activate && "
         "ryu-manager controlador/qos_app.py")


class ErrorApi(RuntimeError):
    pass


def _pedir(metodo, ruta, datos=None, url=URL, espera=5):
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    req = urllib.request.Request(url + ruta, data=cuerpo, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=espera) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detalle = json.loads(e.read().decode("utf-8")).get("error", "")
        except ValueError:
            detalle = ""
        raise ErrorApi(f"{metodo} {ruta}: HTTP {e.code} {detalle}".strip()) from None
    except (urllib.error.URLError, OSError):
        raise ErrorApi(AVISO.format(url=url)) from None


def estado(url=URL) -> dict:
    return _pedir("GET", "/qos/estado", url=url)


def poner_clasificador(nombre: str, url=URL) -> dict:
    """Cambia el clasificador de Ryu. Borra las reglas por flujo para que cada
    flujo se vuelva a decidir con el nuevo."""
    return _pedir("PUT", "/qos/clasificador", {"nombre": nombre}, url=url)


def disponible(url=URL) -> bool:
    try:
        estado(url)
        return True
    except ErrorApi:
        return False


def main():
    args = sys.argv[1:]
    try:
        if args[:1] == ["estado"]:
            print(json.dumps(estado(), ensure_ascii=False, indent=2))
        elif args[:1] == ["clasificador"] and len(args) == 2:
            e = poner_clasificador(args[1])
            print(f"Clasificador: {e['clasificador']} (reglas por flujo borradas en: "
                  f"{', '.join(e['switches_acceso']) or 'ningún switch conectado'})")
        else:
            sys.exit(__doc__)
    except ErrorApi as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
