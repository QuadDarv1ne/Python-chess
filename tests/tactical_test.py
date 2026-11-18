"""Тактические пробы движка: поиск находит выигрыш материала, форк, не вешает
свою фигуру и ставит мат в 1.

Каждая позиция — белые ходят, фиксированная глубина, без таймера и без шума.
Сравнение SAN ведём без суффиксов +/#!/? (шах/мат/аннотации), чтобы любое
правильное взятие или мат засчитывалось. Запуск: python tactical_test.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chess_game.enums import SideType
from chess_game import rules as R
from chess_game.game import Game
from chess_game.engine import Engine

PASS = 0
FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [PASS] {name}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name}  {detail}')


def _strip(san):
    return san.strip().rstrip('+#!?')


def best_move(fen, depth=4):
    g = Game.from_fen(fen)
    eng = Engine(max_depth=depth, time_limit=None, noise_scale=0.0)
    res = eng.search(g.field, g.side_to_move, g.castling_rights, g.en_passant_target)
    return res.move, (g.to_san(res.move) if res.move else None), g


print('=== Тактические пробы движка ===\n')

# 1. Свободное взятие ферзя (ничем не защищён).
print('1. Свободный ферзь')
mv, san, g = best_move('4k3/8/8/3q4/8/8/3Q4/4K3 w - - 0 1', depth=3)
check('берёт висящего ферзя Qxd5', _strip(san) == 'Qxd5', f'ход={san}')

# 2. Форк конём: Ne4-f6+ выигрывает ферзя (king g8, queen d7).
print('2. Форк конём Nf6+ → выигрыш ферзя')
mv, san, g = best_move('6k1/3q4/8/8/4N3/8/8/6K1 w - - 0 1', depth=4)
check('находит форк Nf6+', _strip(san) == 'Nf6', f'ход={san}')
if _strip(san) == 'Nf6':
    g.make_move(mv)
    # Единственные разумные ответы — ходы короля (уклонение от шаха).
    king = [m for m in g.legal_moves()
            if g.field.at(m.from_x, m.from_y).type == R.PieceType.KING]
    if king:
        g.make_move(king[0])
        mv2, san2, _ = best_move(g.fen(), depth=2)
        check('добирает ферзя Nxd7', _strip(san2) == 'Nxd7', f'ход={san2}')

# 3. Не вешать ферзя: Qxg5?? проигрывает ферзя (g5 защищена пешкой f6).
print('3. Избегать вешания ферзя')
mv, san, g = best_move('4k3/8/5p2/6p1/7Q/8/8/4K3 w - - 0 1', depth=4)
check('не берёт защищённую пешку Qxg5', _strip(san) != 'Qxg5', f'ход={san}')

# 4. Мат в 1: Q + K против одинокого короля на краю.
print('4. Мат в 1')
mv, san, g = best_move('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', depth=2)
check('ставит мат в 1', san is not None and san.endswith('#'), f'ход={san}')

# 5. Не разменивать тяжёлую фигуру на лёгкую: белая ладья a1 атакует коня a8,
#    защищённого чёрной ладьёй b8. Rxa8 проигрывает ладью(5) за коня(3).
print('5. Не брать защищённого коня ладьёй Rxa8??')
mv, san, g = best_move('n1r4k/8/8/8/8/8/8/R5K1 w - - 0 1', depth=4)
check('не берёт защищённого коня Rxa8', _strip(san) != 'Rxa8', f'ход={san}')

print(f'\n=== Итог: PASS={PASS}, FAIL={FAIL} ===')
sys.exit(1 if FAIL else 0)
