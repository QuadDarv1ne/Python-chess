"""Детекция троекратного повторения внутри поиска.

Сценарий: позиция P0 — белый король a1 под шахом чёрного ферзя a3; единственный
легальный ход — Kb1. После него возникает P1 (чёрные ходят, у них ферзь против
одинокого короля — белый проигрывает). Сидим в поиск историю, где P1 уже возник
дважды до P0: тогда ход Kb1 создаёт 3-е повторение P1 → ничья (score 0).
Без детекции повторов тот же ход ведёт к сильному минусу (материал/мат).

Запуск: python repetition_test.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chess_game.game import Game
from chess_game.engine import Engine
from chess_game import rules as R

PASS = FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [PASS] {name}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name}  {detail}')


print('=== Детекция повторов внутри поиска ===\n')

P0_fen = '7k/8/8/8/8/q7/8/K7 w - - 0 1'      # белые: Ka1 под шахом Qa3; единственный ход Kb1
P1_fen = '7k/8/8/8/8/q7/8/1K6 b - - 0 1'      # после Kb1: чёрные с ферзём против короля

g0 = Game.from_fen(P0_fen)
g1 = Game.from_fen(P1_fen)

# Белые в P0 имеют ровно один легальный ход — Kb1 (a2 и b2 под боем Qa3).
legal0 = g0.legal_moves()
check('в P0 единственный ход белых', len(legal0) == 1, f'ходов={len(legal0)}')

P0_key = R.position_key(g0.field, g0.side_to_move, g0.castling_rights, g0.en_passant_target)
P1_key = R.position_key(g1.field, g1.side_to_move, g1.castling_rights, g1.en_passant_target)

# История партии: P1 возник дважды, затем P0 (текущий корень).
rep_keys = [P1_key, P1_key, P0_key]

# 1. С детекцией повторов: Kb1 → 3-е повторение P1 → ничья, score ≈ 0.
eng = Engine(max_depth=4, time_limit=None, noise_scale=0.0)
res = eng.search(g0.field, g0.side_to_move, g0.castling_rights,
                 g0.en_passant_target, rep_keys=rep_keys)
check('с реп: ход найден', res.move is not None, f'move={res.move}')
check('с реп: score ≈ 0 (ничья по повтору)',
      res.move is not None and abs(res.score) < 50, f'score={res.score}')

# 2. Без детекции повторов: Kb1 → проигрышная позиция (чёрные с ферзём) → score << 0.
eng2 = Engine(max_depth=4, time_limit=None, noise_scale=0.0)
res2 = eng2.search(g0.field, g0.side_to_move, g0.castling_rights,
                   g0.en_passant_target)
check('без реп: score сильно отрицательный (проигрыш)',
      res2.score < -200, f'score={res2.score}')

# 3. Та же позиция, но P1 в истории лишь один раз → 2-е повторение, не ничья.
rep_keys_once = [P1_key, P0_key]
eng3 = Engine(max_depth=4, time_limit=None, noise_scale=0.0)
res3 = eng3.search(g0.field, g0.side_to_move, g0.castling_rights,
                   g0.en_passant_target, rep_keys=rep_keys_once)
check('одно повторение P1 → не ничья (score < -200)',
      res3.score < -200, f'score={res3.score}')

print(f'\n=== Итог: PASS={PASS}, FAIL={FAIL} ===')
sys.exit(1 if FAIL else 0)
