"""Perft-тест генерации ходов (золотой стандарт корректности).

Считает число листьев на фиксированной глубине и сверяется с эталонами.
Эталоны — общеизвестные значения для стандартных тестовых позиций (см.
chessprogramming wiki «Perft Results»). Совпадение означает, что генерация
ходов корректна во всех тонких случаях: рокировка, en passant, превращение,
уклонение от шаха, связанные фигуры.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chess_game.enums import SideType
from chess_game.field import Field
from chess_game.game import parse_fen
from chess_game import rules as R

PASS = 0
FAIL = 0


def perft(field, side, rights, ep, depth):
    if depth == 0:
        return 1
    moves = R.legal_moves(field, side, rights, ep)
    if depth == 1:
        return len(moves)
    opp = SideType.opposite(side)
    nodes = 0
    for move in moves:
        undo = R.apply_move(field, move)
        new_rights = R.update_castling_rights(rights, move)
        new_ep = R.en_passant_target(move) if move.is_double_pawn else None
        nodes += perft(field, opp, new_rights, new_ep, depth - 1)
        R.undo_move(field, undo)
    return nodes


# (название, FEN или None для стартовой, depth, ожидаемое)
CASES = [
    ('Стартовая: perft(1)', None, 1, 20),
    ('Стартовая: perft(2)', None, 2, 400),
    ('Стартовая: perft(3)', None, 3, 8902),
    ('Стартовая: perft(4)', None, 4, 197281),
    ('Kiwipete: perft(1)', 'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1', 1, 48),
    ('Kiwipete: perft(2)', 'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1', 2, 2039),
    ('Kiwipete: perft(3)', 'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1', 3, 97862),
    ('Эндшпиль: perft(3)', '8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1', 3, 2812),
    ('Промо: perft(2)', 'r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1', 2, 264),
    ('Позиция 5: perft(2)', 'rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8', 2, 1486),
]


def check(name, got, expected):
    global PASS, FAIL
    ok = got == expected
    if ok:
        PASS += 1
        print(f'  [PASS] {name}: {got}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name}: получено {got}, ожидалось {expected}')


def main():
    print('=== Perft-тест генерации ходов ===\n')
    for name, fen, depth, expected in CASES:
        if fen is None:
            field = Field()
            side = SideType.WHITE
            rights = R.CastlingRights()
            ep = None
        else:
            field, side, rights, ep, _, _ = parse_fen(fen)
        t0 = time.perf_counter()
        got = perft(Field.copy(field), side, rights, ep, depth)
        check(name, got, expected)
    print(f'\n=== Итог: PASS={PASS}, FAIL={FAIL} ===')
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == '__main__':
    main()
