#!/usr/bin/env python3
"""Genera un acceso directo con la ruta real de esta copia del proyecto."""
import argparse
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--salida", default=str(Path(__file__).with_name("QoS-Demo.desktop")))
    args = p.parse_args()
    raiz = Path(__file__).resolve().parents[1]
    # El formato desktop requiere escapar porcentajes, barras y comillas.
    ruta = str(raiz / "demo/iniciar_demo.sh").replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    plantilla = ('[Desktop Entry]\nType=Application\nName=Demo QoS adaptativa\n'
                 'Comment=Iniciar la consola del laboratorio\nExec="%s"\n'
                 'Terminal=true\nCategories=Education;Network;\n') % ruta
    salida = Path(args.salida)
    salida.write_text(plantilla)
    salida.chmod(0o755)
    print("Acceso directo generado en", salida)


if __name__ == "__main__":
    main()
