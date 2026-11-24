"""Правила шахмат: генерация ходов, атака клетки, шах/мат/пат, применение хода.

Логика собрана здесь, чтобы game.py отвечал только за состояние партии и
связь с UI. Роли модуля повторяют checkers.rules: функции генерации работают
с (field, side, права_рокировки, клетка_en_passant), а apply_move / undo_move
работают только с расстановкой фигур и возвращают данные для отката.

Координаты: x = 0..7 — файлы a..h, y = 0..7 — горизонтали 8..1.
Белые фигуры идут снизу вверх (y убывает), чёрные — сверху вниз (y растёт).
"""
from dataclasses import dataclass, replace

from chess_game.constants import (
    BISHOP_DIRS, ROOK_DIRS, QUEEN_DIRS, KNIGHT_OFFSETS, KING_OFFSETS,
)
from chess_game.enums import PieceType, SideType
from chess_game.field import Field
from chess_game.move import Move
from chess_game.point import Point


# --- Права на рокировку ------------------------------------------------------

@dataclass(frozen=True)
class CastlingRights:
    '''Какие из четырёх рокировок всё ещё разрешены.

    Права снимаются, когда король или ладья сходили, либо когда ладья на
    углу побита. Хранятся отдельно от позиции фигур, чтобы не зависеть от
    флагов «ходил ли» на самих фигурах.
    '''
    wk: bool = True   # белые короткие (O-O)
    wq: bool = True   # белые длинные (O-O-O)
    bk: bool = True   # чёрные короткие
    bq: bool = True   # чёрные длинные

    @property
    def key(self):
        return (self.wk, self.wq, self.bk, self.bq)


def update_castling_rights(rights: CastlingRights, move: Move) -> CastlingRights:
    '''Новые права после хода: король/ладья сходили или ладью побили.

    Углы: a1=(0,7)→wq, h1=(7,7)→wk, a8=(0,0)→bq, h8=(7,0)→bk.
    '''
    fx, fy = move.from_x, move.from_y
    tx, ty = move.to_x, move.to_y
    wk, wq, bk, bq = rights.wk, rights.wq, rights.bk, rights.bq

    # Король сходил — теряем обе рокировки своей стороны
    if (fx, fy) == (4, 7):
        wk = wq = False
    elif (fx, fy) == (4, 0):
        bk = bq = False

    # Ладья ушла со своего угла
    if (fx, fy) == (7, 7):
        wk = False
    elif (fx, fy) == (0, 7):
        wq = False
    elif (fx, fy) == (7, 0):
        bk = False
    elif (fx, fy) == (0, 0):
        bq = False

    # Ладью на углу побили (ход завершился на углу противника)
    if (tx, ty) == (7, 7):
        wk = False
    elif (tx, ty) == (0, 7):
        wq = False
    elif (tx, ty) == (7, 0):
        bk = False
    elif (tx, ty) == (0, 0):
        bq = False

    return CastlingRights(wk=wk, wq=wq, bk=bk, bq=bq)


def en_passant_target(move: Move) -> Point:
    '''Клетка, открывшаяся для взятия на проходе после двойного хода пешки'''
    # Пешка перепрыгнула через клетку между from и to
    mid_y = (move.from_y + move.to_y) // 2
    return Point(move.from_x, mid_y)


# --- Атака клетки ------------------------------------------------------------

def is_square_attacked(field: Field, x: int, y: int, by_side: SideType) -> bool:
    '''Бьёт ли сторона by_side клетку (x, y) хоть одной фигурой.

    Проверки разложены по типам фигур, чтобы не генерировать ходы — это
    быстрее и не уходит в рекурсию (важно для рокировки и шаха).
    '''
    # Пешки: белая пешка бьёт вверх (y убывает), значит бьёт (x,y) с (x±1, y+1).
    # Чёрная пешка бьёт вниз (y растёт), значит бьёт (x,y) с (x±1, y-1).
    if by_side == SideType.WHITE:
        for dx in (-1, 1):
            ax, ay = x + dx, y + 1
            if field.is_within(ax, ay) and field.type_at(ax, ay) == PieceType.PAWN \
                    and field.color_at(ax, ay) == by_side:
                return True
    else:
        for dx in (-1, 1):
            ax, ay = x + dx, y - 1
            if field.is_within(ax, ay) and field.type_at(ax, ay) == PieceType.PAWN \
                    and field.color_at(ax, ay) == by_side:
                return True

    # Кони
    for off in KNIGHT_OFFSETS:
        nx, ny = x + off.x, y + off.y
        if field.is_within(nx, ny) and field.type_at(nx, ny) == PieceType.KNIGHT \
                and field.color_at(nx, ny) == by_side:
            return True

    # Король (соседние клетки)
    for off in KING_OFFSETS:
        nx, ny = x + off.x, y + off.y
        if field.is_within(nx, ny) and field.type_at(nx, ny) == PieceType.KING \
                and field.color_at(nx, ny) == by_side:
            return True

    # Скользящие по диагоналям: слон или ферзь
    for d in BISHOP_DIRS:
        nx, ny = x + d.x, y + d.y
        while field.is_within(nx, ny):
            t = field.at(nx, ny)
            if not t.is_empty:
                if t.color == by_side and t.type in (PieceType.BISHOP, PieceType.QUEEN):
                    return True
                break
            nx += d.x
            ny += d.y

    # Скользящие по прямым: ладья или ферзь
    for d in ROOK_DIRS:
        nx, ny = x + d.x, y + d.y
        while field.is_within(nx, ny):
            t = field.at(nx, ny)
            if not t.is_empty:
                if t.color == by_side and t.type in (PieceType.ROOK, PieceType.QUEEN):
                    return True
                break
            nx += d.x
            ny += d.y

    return False


def in_check(field: Field, side: SideType) -> bool:
    '''Стоит ли король стороны под шахом'''
    kpos = field.king_position(side)
    if kpos is None:
        return False
    return is_square_attacked(field, kpos[0], kpos[1], SideType.opposite(side))


# --- Псевдо-легальная генерация (без проверки оставления короля под шахом) ----

def _pawn_moves(field: Field, x: int, y: int, color: SideType, ep: Point) -> list:
    moves = []
    if color == SideType.WHITE:
        forward = -1
        start_rank = 6
        promo_rank = 0
    else:
        forward = 1
        start_rank = 1
        promo_rank = 7

    # Ход вперёд на одну клетку
    ny = y + forward
    if field.is_within(x, ny) and field.type_at(x, ny) == PieceType.NONE:
        if ny == promo_rank:
            for p in (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT):
                moves.append(Move.promoting(x, y, x, ny, p))
        else:
            moves.append(Move.normal(x, y, x, ny))
            # Двойной ход с начальной позиции
            ny2 = y + 2 * forward
            if y == start_rank and field.type_at(x, ny2) == PieceType.NONE:
                moves.append(Move.double_pawn(x, y, x, ny2))

    # Диагональные взятия и взятие на проходе
    for dx in (-1, 1):
        cx, cy = x + dx, y + forward
        if not field.is_within(cx, cy):
            continue
        target = field.at(cx, cy)
        if not target.is_empty and target.color != color:
            if cy == promo_rank:
                for p in (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT):
                    moves.append(Move.promoting(x, y, cx, cy, p))
            else:
                moves.append(Move.normal(x, y, cx, cy))
        elif ep is not None and ep.x == cx and ep.y == cy:
            # Клетка пуста, но это цель en passant — берём пешку за ней
            moves.append(Move.en_passant(x, y, cx, cy))

    return moves


def _knight_moves(field: Field, x: int, y: int, color: SideType) -> list:
    moves = []
    for off in KNIGHT_OFFSETS:
        nx, ny = x + off.x, y + off.y
        if not field.is_within(nx, ny):
            continue
        t = field.at(nx, ny)
        if t.is_empty or t.color != color:
            moves.append(Move.normal(x, y, nx, ny))
    return moves


def _slide_moves(field: Field, x: int, y: int, color: SideType, dirs) -> list:
    moves = []
    for d in dirs:
        nx, ny = x + d.x, y + d.y
        while field.is_within(nx, ny):
            t = field.at(nx, ny)
            if t.is_empty:
                moves.append(Move.normal(x, y, nx, ny))
            else:
                if t.color != color:
                    moves.append(Move.normal(x, y, nx, ny))
                break
            nx += d.x
            ny += d.y
    return moves


def _king_step_moves(field: Field, x: int, y: int, color: SideType) -> list:
    moves = []
    for off in KING_OFFSETS:
        nx, ny = x + off.x, y + off.y
        if not field.is_within(nx, ny):
            continue
        t = field.at(nx, ny)
        if t.is_empty or t.color != color:
            moves.append(Move.normal(x, y, nx, ny))
    return moves


def _castle_moves(field: Field, side: SideType, rights: CastlingRights) -> list:
    '''Рокировка: права есть, клетки между пусты, король не проходит через шах.

    Проверка «не через шах» здесь обязательна — post-move in_check в
    legal_moves ловит только конечную клетку, а правила требуют, чтобы ни
    начальная, ни промежуточная, ни конечная не были под боем.
    '''
    moves = []
    if side == SideType.WHITE:
        y = 7
        enemy = SideType.BLACK
        king = field.at(4, y)
        if king.type != PieceType.KING or king.color != side:
            return moves
        if rights.wk and field.type_at(5, y) == PieceType.NONE and field.type_at(6, y) == PieceType.NONE:
            if field.at(7, y).type == PieceType.ROOK and field.at(7, y).color == side:
                if not is_square_attacked(field, 4, y, enemy) \
                        and not is_square_attacked(field, 5, y, enemy) \
                        and not is_square_attacked(field, 6, y, enemy):
                    moves.append(Move.castle(4, y, 6, y, 'K'))
        if rights.wq and field.type_at(1, y) == PieceType.NONE \
                and field.type_at(2, y) == PieceType.NONE \
                and field.type_at(3, y) == PieceType.NONE:
            if field.at(0, y).type == PieceType.ROOK and field.at(0, y).color == side:
                if not is_square_attacked(field, 4, y, enemy) \
                        and not is_square_attacked(field, 3, y, enemy) \
                        and not is_square_attacked(field, 2, y, enemy):
                    moves.append(Move.castle(4, y, 2, y, 'Q'))
    else:
        y = 0
        enemy = SideType.WHITE
        king = field.at(4, y)
        if king.type != PieceType.KING or king.color != side:
            return moves
        if rights.bk and field.type_at(5, y) == PieceType.NONE and field.type_at(6, y) == PieceType.NONE:
            if field.at(7, y).type == PieceType.ROOK and field.at(7, y).color == side:
                if not is_square_attacked(field, 4, y, enemy) \
                        and not is_square_attacked(field, 5, y, enemy) \
                        and not is_square_attacked(field, 6, y, enemy):
                    moves.append(Move.castle(4, y, 6, y, 'K'))
        if rights.bq and field.type_at(1, y) == PieceType.NONE \
                and field.type_at(2, y) == PieceType.NONE \
                and field.type_at(3, y) == PieceType.NONE:
            if field.at(0, y).type == PieceType.ROOK and field.at(0, y).color == side:
                if not is_square_attacked(field, 4, y, enemy) \
                        and not is_square_attacked(field, 3, y, enemy) \
                        and not is_square_attacked(field, 2, y, enemy):
                    moves.append(Move.castle(4, y, 2, y, 'Q'))
    return moves


def pseudo_legal_moves(field: Field, side: SideType,
                       rights: CastlingRights, ep: Point = None) -> list:
    '''Все ходы стороны без фильтра «король не остаётся под шахом»'''
    moves = []
    for x, y, piece in field.pieces(side):
        t = piece.type
        if t == PieceType.PAWN:
            moves.extend(_pawn_moves(field, x, y, side, ep))
        elif t == PieceType.KNIGHT:
            moves.extend(_knight_moves(field, x, y, side))
        elif t == PieceType.BISHOP:
            moves.extend(_slide_moves(field, x, y, side, BISHOP_DIRS))
        elif t == PieceType.ROOK:
            moves.extend(_slide_moves(field, x, y, side, ROOK_DIRS))
        elif t == PieceType.QUEEN:
            moves.extend(_slide_moves(field, x, y, side, QUEEN_DIRS))
        elif t == PieceType.KING:
            moves.extend(_king_step_moves(field, x, y, side))
            moves.extend(_castle_moves(field, side, rights))
    return moves


# --- Применение хода к полю (только фигуры; права/ходы хранит game.py) --------

def apply_move(field: Field, move: Move) -> dict:
    '''Выполнить ход на поле и вернуть данные для отката.

    Не трогает права рокировки, клетку en passant и счётчики — это состояние
    партии, им владеет game.py. En passant здесь однозначен по координатам:
    побитая пешка стоит на (to_x, from_y).
    '''
    fx, fy = move.from_x, move.from_y
    tx, ty = move.to_x, move.to_y
    mover = field.at(fx, fy)
    moved_type, moved_color = mover.type, mover.color

    captured = None      # (cx, cy, ctype, ccolor)
    rook_move = None     # (rfrom_x, rfrom_y, rto_x, rto_y, rook_color)

    if move.is_en_passant:
        cx, cy = tx, fy  # побитая пешка — за клеткой приземления
        cap = field.at(cx, cy)
        captured = (cx, cy, cap.type, cap.color)
        cap.clear()
        field.at(tx, ty).set(moved_type, moved_color)
        field.at(fx, fy).clear()
    elif move.is_castle:
        # Король
        field.at(tx, ty).set(moved_type, moved_color)
        field.at(fx, fy).clear()
        # Ладья перекидывается на другую сторону от короля
        if move.castle_side == 'K':
            rfrom_x, rfrom_y, rto_x, rto_y = 7, fy, 5, fy
        else:  # 'Q'
            rfrom_x, rfrom_y, rto_x, rto_y = 0, fy, 3, fy
        rook = field.at(rfrom_x, rfrom_y)
        rook_color = rook.color
        field.at(rto_x, rto_y).set(PieceType.ROOK, rook_color)
        field.at(rfrom_x, rfrom_y).clear()
        rook_move = (rfrom_x, rfrom_y, rto_x, rto_y, rook_color)
    else:
        target = field.at(tx, ty)
        if not target.is_empty:
            captured = (tx, ty, target.type, target.color)
        if move.is_promotion:
            field.at(tx, ty).set(move.promotion, moved_color)
        else:
            field.at(tx, ty).set(moved_type, moved_color)
        field.at(fx, fy).clear()

    return {
        'from': (fx, fy),
        'to': (tx, ty),
        'moved_type': moved_type,
        'moved_color': moved_color,
        'captured': captured,
        'rook_move': rook_move,
        'is_promotion': move.is_promotion,
        'is_castle': move.is_castle,
        'is_en_passant': move.is_en_passant,
    }


def undo_move(field: Field, undo: dict):
    '''Откатить ход, выполненный apply_move'''
    fx, fy = undo['from']
    tx, ty = undo['to']

    # Убираем фигуру с клетки назначения
    field.clear_at(tx, ty)
    # Возвращаем ходившую фигуру на исходную клетку (пешку, если было превращение)
    mtype = PieceType.PAWN if undo['is_promotion'] else undo['moved_type']
    field.at(fx, fy).set(mtype, undo['moved_color'])

    # Возвращаем побитую фигуру
    if undo['captured']:
        cx, cy, ctype, ccolor = undo['captured']
        field.at(cx, cy).set(ctype, ccolor)

    # Возвращаем ладью при рокировке
    if undo['rook_move']:
        rfrom_x, rfrom_y, rto_x, rto_y, rook_color = undo['rook_move']
        field.at(rfrom_x, rfrom_y).set(PieceType.ROOK, rook_color)
        field.clear_at(rto_x, rto_y)


# --- Легальные ходы и статус позиции ----------------------------------------

def legal_moves(field: Field, side: SideType,
                rights: CastlingRights, ep: Point = None) -> list:
    '''Псевдо-легальные ходы, отфильтрованные по «король не под шахом».

    Каждый ход применяется к полю, проверяется in_check для своей стороны,
    затем откатывается. Это простой и надёжный способ; для скорости в движке
    есть отдельная генерация, но для UI/проверок статуса этого достаточно.
    '''
    legal = []
    for move in pseudo_legal_moves(field, side, rights, ep):
        undo = apply_move(field, move)
        safe = not in_check(field, side)
        undo_move(field, undo)
        if safe:
            legal.append(move)
    return legal


def game_status(field: Field, side: SideType,
                rights: CastlingRights, ep: Point = None) -> str:
    '''Статус позиции для стороны, чей ход: 'normal' / 'check' / 'checkmate' / 'stalemate'.

    Ничьи по правилу 50 ходов и троекратному повторению здесь не проверяются:
    им нужны счётчики и история, ими владеет game.py.
    '''
    legal = legal_moves(field, side, rights, ep)
    checked = in_check(field, side)
    if not legal:
        return 'checkmate' if checked else 'stalemate'
    return 'check' if checked else 'normal'


# --- Ключ позиции для повторов ----------------------------------------------

def _ep_capture_possible(field: Field, side: SideType, ep: Point) -> bool:
    '''Может ли пешка стороны side взять en passant на клетке ep.

    Захватывающая пешка стоит на соседнем файле и на горизонтали только что
    сдвинувшейся двойной пешки: для белых (чёрная пешка двойным ходом) — на
    ранг НИЖЕ клетки ep, для чёрных — на ранг ВЫШЕ. По FIDE (ст. 9.2) две
    позиции считаются одинаковыми для троекратного повторения, даже если клетка
    ep задана, но ни одна пешка не может ею воспользоваться.
    '''
    if ep is None:
        return False
    ex, ey = ep.x, ep.y
    # Белые ловят чёрную двойную пешку: та на ранге ВЫШЕ клетки ep (dy=ey+1).
    # Чёрные ловят белую двойную пешку: та на ранге НИЖЕ клетки ep (dy=ey-1).
    dy = ey + 1 if side == SideType.WHITE else ey - 1
    if dy < 0 or dy > 7:
        return False
    for fx in (ex - 1, ex + 1):
        if fx < 0 or fx > 7:
            continue
        p = field.at(fx, dy)
        if p.is_empty or p.type != PieceType.PAWN or p.color != side:
            continue
        # Геометрически пешка бьёт клетку ep, но если она связана, взятие
        # не входит в возможные ходы — для ст. 9.2 FIDE клетка ep тогда не
        # отличает позицию.
        undo = apply_move(field, Move.en_passant(fx, dy, ex, ey))
        legal = not in_check(field, side)
        undo_move(field, undo)
        if legal:
            return True
    return False


def position_key(field: Field, side: SideType,
                 rights: CastlingRights, ep: Point = None) -> bytes:
    '''Компактный ключ позиции для поиска троекратного повторения.

    Кодируем (тип, цвет) каждой клетки, сторону хода, права рокировки и клетку
    en passant. Клетка ep учитывается ТОЛЬКО когда сторона хода действительно
    может ей воспользоваться (FIDE ст. 9.2): иначе две позиции, различающиеся
    лишь неактуальной ep-клеткой, считались бы разными и повторение
    просматривалось бы.
    '''
    parts = bytearray()
    for y in range(field.y_size):
        for x in range(field.x_size):
            piece = field.at(x, y)
            # тип и цвет в один байт не лезут (6 типов × 2 + пусто = 13), берём два
            parts.append(piece.type.value if piece.type else 0)
            parts.append(piece.color.value if piece.color else 0)
    parts.append(side.value)
    parts.extend((1 if rights.wk else 0, 1 if rights.wq else 0,
                  1 if rights.bk else 0, 1 if rights.bq else 0))
    # 255 = сигнальное «нет en passant»; координаты клетки в диапазоне 0..7.
    # Неактуальную ep (никто не может взять) приравниваем к «нет ep».
    if ep is not None and _ep_capture_possible(field, side, ep):
        parts.append(ep.x)
        parts.append(ep.y)
    else:
        parts.append(255)
        parts.append(255)
    return bytes(parts)
