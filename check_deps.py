"""Проверка зависимостей перед сборкой.

PyQt6 и PyQt6-WebEngine должны быть собраны с одной и той же версией Qt:
PyQt6-WebEngine отстаёт от PyQt6, и если поставить их без пина, в одном
процессе окажутся две разные библиотеки Qt. Тогда приложение падает с
"ImportError: DLL load failed while importing QtWebEngineWidgets".

Запуск:
    python check_deps.py
"""

import sys
from importlib.metadata import PackageNotFoundError, version


def _version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _minor(value):
    if not value:
        return None
    return ".".join(value.split(".")[:2])


def main() -> int:
    packages = ("PyQt6", "PyQt6-Qt6", "PyQt6-WebEngine", "PyQt6-WebEngine-Qt6",
                "genshin", "aiohttp", "cryptography")

    print("Установленные версии:")
    for name in packages:
        print(f"  {name:24} {_version(name) or '— не установлен'}")

    problems = []

    for name in ("PyQt6", "PyQt6-WebEngine"):
        if not _version(name):
            problems.append(f"{name} не установлен")

    qt_core = _minor(_version("PyQt6-Qt6"))
    qt_web = _minor(_version("PyQt6-WebEngine-Qt6"))
    if qt_core and qt_web and qt_core != qt_web:
        problems.append(
            f"разные версии Qt: PyQt6-Qt6 {qt_core}, PyQt6-WebEngine-Qt6 {qt_web}. "
            "Встроенный браузер работать не будет."
        )

    for name in ("genshin", "aiohttp", "cryptography"):
        if not _version(name):
            problems.append(f"{name} не установлен")

    if problems:
        print("\nПроблемы:")
        for problem in problems:
            print(f"  ✗ {problem}")
        print(
            "\nКак исправить:\n"
            "  pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6-WebEngine PyQt6-WebEngine-Qt6\n"
            "  pip install -r requirements.txt"
        )
        return 1

    print(f"\n✓ Версии совместимы (Qt {qt_core or '?'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
