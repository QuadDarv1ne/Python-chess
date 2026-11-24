"""Самопроверка ядра шахмат (аналог tools/selfcheck.py из Python-checkers).

Запуск:
    PYTHONPATH=/home/z/my-project/download/chess python \
        /home/z/my-project/download/chess/tests/selfcheck.py

Проверяет: число ходов из стартовой позиции, мат дурака, детский мат,
взятие на проходе, рокировку (доступность и запрет под шахом), инвариант
apply/undo (поле восстанавливается).
"""
import sys
from pathlib import Path

# Добавляем корень проекта (где лежит пакет chess_game) в sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Консоль Windows по умолчанию в cp1251 — переключаем вывод в UTF-8, иначе
# юникодные символы (→, ≈, кириллица) роняют тест с UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8')

from chess_game.enums import PieceType, SideType
from chess_game.field import Field
from chess_game.move import Move
from chess_game.point import Point
from chess_game import rules as R


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


def apply_line(field, rights, ep, moves):
    '''Проиграть список Move на field, отслеживая права и ep. Возвращает (rights, ep).'''
    for move in moves:
        R.apply_move(field, move)
        rights = R.update_castling_rights(rights, move)
        ep = R.en_passant_target(move) if move.is_double_pawn else None
    return rights, ep


# --- 1. Стартовая позиция: по 20 ходов у каждой стороны ----------------------

def test_start_position_moves():
    print('Тест: число ходов из стартовой позиции')
    field = Field()
    rights = R.CastlingRights()
    white = R.legal_moves(field, SideType.WHITE, rights, None)
    check('у белых 20 ходов', len(white) == 20, f'получено {len(white)}')
    # Симметрия: если перевернуть доску, у чёрных тоже 20
    black = R.legal_moves(field, SideType.BLACK, rights, None)
    check('у чёрных 20 ходов из старта', len(black) == 20, f'получено {len(black)}')

    # После 1.e4 у чёрных тоже 20 ходов
    e4 = Move.double_pawn(4, 6, 4, 4)
    R.apply_move(field, e4)
    rights = R.update_castling_rights(rights, e4)
    ep = R.en_passant_target(e4)
    black_after = R.legal_moves(field, SideType.BLACK, rights, ep)
    check('после 1.e4 у чёрных 20 ходов', len(black_after) == 20, f'получено {len(black_after)}')


# --- 2. Мат дурака: 1.f3 e5 2.g4 Qh4# ---------------------------------------

def test_fools_mate():
    print('Тест: мат дурака (Qh4#)')
    field = Field()
    rights = R.CastlingRights()
    moves = [
        Move.normal(5, 6, 5, 5),            # 1. f3
        Move.double_pawn(4, 1, 4, 3),       # 1... e5
        Move.double_pawn(6, 6, 6, 4),       # 2. g4
        Move.normal(3, 0, 7, 4),            # 2... Qh4#
    ]
    rights, ep = apply_line(field, rights, None, moves)
    status = R.game_status(field, SideType.WHITE, rights, ep)
    check('белым поставлен мат', status == 'checkmate', f'статус={status}')
    check('белый король под шахом', R.in_check(field, SideType.WHITE))


# --- 3. Детский мат: 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6 4.Qxf7# --------------------

def test_scholars_mate():
    print('Тест: детский мат (Qxf7#)')
    field = Field()
    rights = R.CastlingRights()
    moves = [
        Move.double_pawn(4, 6, 4, 4),   # 1. e4
        Move.double_pawn(4, 1, 4, 3),   # 1... e5
        Move.normal(5, 7, 2, 4),        # 2. Bc4
        Move.normal(1, 0, 2, 2),        # 2... Nc6
        Move.normal(3, 7, 7, 3),        # 3. Qh5
        Move.normal(6, 0, 5, 2),        # 3... Nf6
        Move.normal(7, 3, 5, 1),        # 4. Qxf7#
    ]
    rights, ep = apply_line(field, rights, None, moves)
    status = R.game_status(field, SideType.BLACK, rights, ep)
    check('чёрным поставлен мат', status == 'checkmate', f'статус={status}')


# --- 4. Взятие на проходе ----------------------------------------------------

def test_en_passant():
    print('Тест: взятие на проходе')
    field = Field.empty()
    # Белая пешка e4, чёрная пешка d4; чёрные только что сыграли d7-d5? Нет:
    # ep возникает, когда ТОЛЬКО ЧТО походила двойным пешка противника.
    # Сценарий: белые e2-e4 (открывает e3), у чёрных есть пешка на d4 —
    # она может взять e3 на проходе. Здесь ход чёрных.
    field.set_piece(4, 4, PieceType.PAWN, SideType.WHITE)   # белая e4
    field.set_piece(3, 4, PieceType.PAWN, SideType.BLACK)   # чёрная d4
    field.set_piece(4, 7, PieceType.KING, SideType.WHITE)
    field.set_piece(4, 0, PieceType.KING, SideType.BLACK)
    ep = Point(4, 5)  # e3 — открыто ходом e2-e4
    rights = R.CastlingRights(wk=False, wq=False, bk=False, bq=False)
    moves = R.legal_moves(field, SideType.BLACK, rights, ep)
    ep_move = None
    for m in moves:
        if m.is_en_passant and m.from_x == 3 and m.from_y == 4 and m.to_x == 4 and m.to_y == 5:
            ep_move = m
            break
    check('ход взятия на проходе сгенерирован', ep_move is not None)

    if ep_move:
        undo = R.apply_move(field, ep_move)
        # Побитая белая пешка снята с e4 (4,4), чёрная встала на e3 (4,5)
        check('побитая пешка снята', field.type_at(4, 4) == PieceType.NONE)
        check('пешка встала на e3', field.type_at(4, 5) == PieceType.PAWN
              and field.color_at(4, 5) == SideType.BLACK)
        R.undo_move(field, undo)
        check('undo восстановил e4', field.type_at(4, 4) == PieceType.PAWN
              and field.color_at(4, 4) == SideType.WHITE)
        check('undo восстановил d4', field.type_at(3, 4) == PieceType.PAWN
              and field.color_at(3, 4) == SideType.BLACK)


# --- 5. Рокировка ------------------------------------------------------------

def test_castling():
    print('Тест: рокировка')
    field = Field.empty()
    # Белые: король e1, ладьи a1/h1, клетки между пусты
    field.set_piece(4, 7, PieceType.KING, SideType.WHITE)
    field.set_piece(0, 7, PieceType.ROOK, SideType.WHITE)
    field.set_piece(7, 7, PieceType.ROOK, SideType.WHITE)
    # Чёрный король где-то далеко, чтобы не мешал
    field.set_piece(4, 0, PieceType.KING, SideType.BLACK)
    rights = R.CastlingRights(wk=True, wq=True, bk=False, bq=False)

    white_moves = R.legal_moves(field, SideType.WHITE, rights, None)
    castle_k = any(m.is_castle and m.castle_side == 'K' for m in white_moves)
    castle_q = any(m.is_castle and m.castle_side == 'Q' for m in white_moves)
    check('короткая рокировка доступна', castle_k)
    check('длинная рокировка доступна', castle_q)

    # Под шахом роковать нельзя: поставим чёрную ладью на e8 → шах по e-файлу
    field.set_piece(4, 0, PieceType.ROOK, SideType.BLACK)  # e8 — ладья
    field.set_piece(7, 0, PieceType.KING, SideType.BLACK)  # король в угол
    white_moves2 = R.legal_moves(field, SideType.WHITE, rights, None)
    castle_any = any(m.is_castle for m in white_moves2)
    check('под шахом рокировки нет', not castle_any)
    check('белый король под шахом', R.in_check(field, SideType.WHITE))


# --- 6. Инвариант apply/undo для всех ходов из стартовой позиции -------------

def test_apply_undo_invariant():
    print('Тест: инвариант apply/undo')
    field = Field()
    snapshot = bytes(field.type_at(x, y).value
                     for y in range(field.y_size) for x in range(field.x_size))
    rights = R.CastlingRights()
    for move in R.legal_moves(field, SideType.WHITE, rights, None):
        undo = R.apply_move(field, move)
        R.undo_move(field, undo)
        after = bytes(field.type_at(x, y).value
                      for y in range(field.y_size) for x in range(field.x_size))
        if after != snapshot:
            check(f'undo восстановил поле для {move}', False)
            return
    check('undo восстановил поле для всех 20 ходов', True)


# --- 7. Превращение пешки ----------------------------------------------------

def test_promotion():
    print('Тест: превращение пешки')
    field = Field.empty()
    field.set_piece(0, 1, PieceType.PAWN, SideType.WHITE)    # белая пешка a7
    field.set_piece(4, 7, PieceType.KING, SideType.WHITE)
    field.set_piece(4, 0, PieceType.KING, SideType.BLACK)
    rights = R.CastlingRights(wk=False, wq=False, bk=False, bq=False)
    moves = R.legal_moves(field, SideType.WHITE, rights, None)
    promos = [m for m in moves if m.from_x == 0 and m.from_y == 1
              and m.to_x == 0 and m.to_y == 0 and m.is_promotion]
    check('4 хода превращения на a8', len(promos) == 4, f'получено {len(promos)}')
    kinds = {m.promotion for m in promos}
    check('превращения во все 4 фигуры',
          kinds == {PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT},
          str(kinds))

    # Применяем превращение в ферзя — на a8 должна встать белая ферзь
    queen_move = next(m for m in promos if m.promotion == PieceType.QUEEN)
    undo = R.apply_move(field, queen_move)
    check('на a8 белый ферзь', field.type_at(0, 0) == PieceType.QUEEN
          and field.color_at(0, 0) == SideType.WHITE)
    check('a7 пуста', field.type_at(0, 1) == PieceType.NONE)
    R.undo_move(field, undo)
    check('undo вернул пешку на a7', field.type_at(0, 1) == PieceType.PAWN)

    # Превращение со взятием: чёрная ладья на b8, пешка a7 бьёт b8 с превращением
    field.set_piece(1, 0, PieceType.ROOK, SideType.BLACK)
    moves = R.legal_moves(field, SideType.WHITE, rights, None)
    cap_promos = [m for m in moves if m.from_x == 0 and m.from_y == 1
                  and m.to_x == 1 and m.to_y == 0 and m.is_promotion]
    check('4 хода превращения со взятием на b8', len(cap_promos) == 4,
          f'получено {len(cap_promos)}')


# --- 8. Пат ------------------------------------------------------------------

def test_stalemate():
    print('Тест: пат')
    # Пат: белый король a1, чёрный король b3, чёрный слон c2.
    #   b2 бьётся чёрным королём (b3), a2 — тоже чёрным королём,
    #   b1 — слоном c2 по диагонали; a1 не под боем → белым некупиться.
    field = Field.empty()
    field.set_piece(0, 7, PieceType.KING, SideType.WHITE)    # a1
    field.set_piece(1, 5, PieceType.KING, SideType.BLACK)    # b3
    field.set_piece(2, 6, PieceType.BISHOP, SideType.BLACK)  # c2
    rights = R.CastlingRights(wk=False, wq=False, bk=False, bq=False)
    status = R.game_status(field, SideType.WHITE, rights, None)
    check('белый король НЕ под шахом', not R.in_check(field, SideType.WHITE))
    check('белым поставлен пат', status == 'stalemate', f'статус={status}')


def main():
    print('=== Самопроверка ядра шахмат ===\n')
    test_start_position_moves()
    test_fools_mate()
    test_scholars_mate()
    test_en_passant()
    test_castling()
    test_apply_undo_invariant()
    test_promotion()
    test_stalemate()
    print(f'\n=== Итог: PASS={PASS}, FAIL={FAIL} ===')
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == '__main__':
    main()
