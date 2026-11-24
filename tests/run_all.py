"""Запуск всех проверок проекта одной командой.

Пример:
    python tests/run_all.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = (
    'selfcheck.py',
    'perft.py',
    'repetition_test.py',
    'tactical_test.py',
    'engine_smoke.py',
    'game_smoke.py',
    'audio_smoke.py',
)


def main() -> int:
    failed = []
    for name in TESTS:
        path = ROOT / 'tests' / name
        print(f'\n>>> {name}\n')
        rc = subprocess.call([sys.executable, str(path)], cwd=ROOT)
        if rc != 0:
            failed.append(name)
    print('\n=== Сводка ===')
    if failed:
        print('FAIL:', ', '.join(failed))
        return 1
    print(f'Все {len(TESTS)} наборов пройдены.')
    return 0


if __name__ == '__main__':
    sys.exit(main())