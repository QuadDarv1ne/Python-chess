"""Поиск лучшего хода: negamax + alpha-beta + quiescence + итеративное углубление.

Структура повторяет checkers.engine: поиск работает с позициями, применяет
ходы к полю и откатывает их, плюс обновляет права рокировки и клетку en
passant (они нужны генерации на следующем уровне). Отличия от шашек:

- Ход — это одна полуплоскость, а не серия взятий, поэтому «Turn» не нужен.
- На дне поиска вызывается quiescence. Если сторона под шахом — stand-pat
  незаконен (нельзя «пасовать» под шахом), поэтому ищутся все уклонения
  (evasions); иначе — stand-pat + взятия с delta-отсечением.
- Легальность проверяется прямо в поиске: после apply_move смотрим, не
  оказался ли свой король под шахом.
- Мат оценивается с поправкой на глубину (closer mate = больше модуль), а в
  транспозиционной таблице мат-оценки хранятся относительно узла, чтобы
  корректно читаться с любой глубины.

Ускорения: таблица транспозиций (EXACT/LOWER/UPPER + best move для ordering),
MVV-LVA для взятий, killer-ходы и history-эвристика для тихих, null-move
pruning (R=2) с защитой от цугцванга по не-пешечному материалу, PV-ход с
прошлой итерации первым в корне, сужение alpha-окна по корневым ходам.
"""
import random
import threading
from collections import Counter
from dataclasses import dataclass
from math import inf
from time import perf_counter
from typing import Callable, Optional

from chess_game import rules as R
from chess_game.constants import PIECE_VALUES
from chess_game.enums import PieceType, SideType
from chess_game.field import Field
from chess_game.move import Move
from chess_game.point import Point

# Оценка мата: больше любой позиционной оценки, но не бесконечность, чтобы
# различать «мат быстрее / медленнее».
MATE_SCORE = 1_000_000.0
MATE_THRESHOLD = MATE_SCORE - 1000.0

# «Большое» число для delta-отсечения в quiescence: запас на отдачу фигуры.
DELTA_MARGIN = 200

# Лимит размера таблицы транспозиций; при превышении очищаем (иначе память
# растёт без меры в длинных партиях).
MAX_TT_ENTRIES = 200_000

# Глубина, до которой quiescence ещё разыскивает уклонения от шаха; защита от
# бесконтрольного роста дерева проверок.
MAX_QPLY = 80

# Флаги записей таблицы транспозиций (значение относительно окна поиска)
EXACT, LOWER_BOUND, UPPER_BOUND = 0, 1, 2


# --- Кодирование мат-оценок для TT ------------------------------------------
# Мат-оценка зависит от расстояния от корня: «мат в 2 хода» и «мат в 5 ходов»
# — разные значения. В TT позиция может встретиться с другой ply, поэтому
# храним значение относительно УЗЛА (расстояние до мата от этого узла), а при
# чтении пересчитываем обратно. См. chessprogramming wiki "TT mate scoring".

def _mate_store(value: float, ply: int) -> float:
    '''Перевести оценку из «от корня» в «от узла» при записи в TT'''
    if value > MATE_THRESHOLD:
        return value + ply
    if value < -MATE_THRESHOLD:
        return value - ply
    return value


def _mate_load(value: float, ply: int) -> float:
    '''Перевести оценку из «от узла» в «от корня» при чтении из TT'''
    if value > MATE_THRESHOLD:
        return value - ply
    if value < -MATE_THRESHOLD:
        return value + ply
    return value


# --- Piece-square tables (сотые пешки, с точки зрения белых, a8 — индекс 0) ---
# Стандартные таблицы для начинающего движка: поощряют развитие, центр,
# безопасность короля; для чёрных отражаются по вертикали и берутся с минусом.

_PST = {
    PieceType.PAWN: [
        0,  0,  0,  0,  0,  0,  0,  0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
        5,  5, 10, 25, 25, 10,  5,  5,
        0,  0,  0, 20, 20,  0,  0,  0,
        5, -5,-10,  0,  0,-10, -5,  5,
        5, 10, 10,-20,-20, 10, 10,  5,
        0,  0,  0,  0,  0,  0,  0,  0,
    ],
    PieceType.KNIGHT: [
        -50,-40,-30,-30,-30,-30,-40,-50,
        -40,-20,  0,  0,  0,  0,-20,-40,
        -30,  0, 10, 15, 15, 10,  0,-30,
        -30,  5, 15, 20, 20, 15,  5,-30,
        -30,  0, 15, 20, 20, 15,  0,-30,
        -30,  5, 10, 15, 15, 10,  5,-30,
        -40,-20,  0,  5,  5,  0,-20,-40,
        -50,-40,-30,-30,-30,-30,-40,-50,
    ],
    PieceType.BISHOP: [
        -20,-10,-10,-10,-10,-10,-10,-20,
        -10,  0,  0,  0,  0,  0,  0,-10,
        -10,  0,  5, 10, 10,  5,  0,-10,
        -10,  5,  5, 10, 10,  5,  5,-10,
        -10,  0, 10, 10, 10, 10,  0,-10,
        -10, 10, 10, 10, 10, 10, 10,-10,
        -10,  5,  0,  0,  0,  0,  5,-10,
        -20,-10,-10,-10,-10,-10,-10,-20,
    ],
    PieceType.ROOK: [
        0,  0,  0,  0,  0,  0,  0,  0,
        5, 10, 10, 10, 10, 10, 10,  5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        0,  0,  0,  5,  5,  0,  0,  0,
    ],
    PieceType.QUEEN: [
        -20,-10,-10, -5, -5,-10,-10,-20,
        -10,  0,  0,  0,  0,  0,  0,-10,
        -10,  0,  5,  5,  5,  5,  0,-10,
        -5,  0,  5,  5,  5,  5,  0, -5,
        0,  0,  5,  5,  5,  5,  0, -5,
        -10,  5,  5,  5,  5,  5,  0,-10,
        -10,  0,  5,  0,  0,  0,  0,-10,
        -20,-10,-10, -5, -5,-10,-10,-20,
    ],
    PieceType.KING: [
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -20,-30,-30,-40,-40,-30,-30,-20,
        -10,-20,-20,-20,-20,-20,-20,-10,
        20, 20,  0,  0,  0,  0, 20, 20,
        20, 30, 10,  0,  0, 10, 30, 20,
    ],
}


def _pst_value(piece_type: PieceType, x: int, y: int, color: SideType) -> int:
    '''Значение из таблицы для фигуры на (x,y). Белые — прямо, чёрные — зеркально.'''
    table = _PST[piece_type]
    if color == SideType.WHITE:
        return table[y * 8 + x]
    return -table[(7 - y) * 8 + x]


# Эндшпильная PST короля: в отличие от миттельшпильной (беречь), поощряет
# выход в центр — в эндшпиле король становится активной фигурой.
_PST_KING_EG = [
    -50, -40, -20, -30, -30, -20, -40, -50,
    -30, -20,   0,   0,   0,   0, -20, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -20,   0,   0,   0,   0, -20, -30,
    -50, -40, -20, -30, -30, -20, -40, -50,
]

# Полный не-пешечный не-королевский материал обеих сторон в стартовой позиции —
# для расчёта фазы игры (≈6400 сотых пешки).
_START_NON_PAWN_MAT = 2 * (
    PIECE_VALUES[PieceType.QUEEN]
    + 2 * PIECE_VALUES[PieceType.ROOK]
    + 2 * PIECE_VALUES[PieceType.BISHOP]
    + 2 * PIECE_VALUES[PieceType.KNIGHT]
)


def _king_pst(x: int, y: int, color: SideType, phase: float) -> float:
    '''PST короля, интерполированная между миттельшпилем (phase=1) и эндшпилем (0).'''
    mg = _PST[PieceType.KING]
    eg = _PST_KING_EG
    if color == SideType.WHITE:
        i = y * 8 + x
    else:
        i = (7 - y) * 8 + x
    return mg[i] * phase + eg[i] * (1.0 - phase) \
        if color == SideType.WHITE \
        else -(mg[i] * phase + eg[i] * (1.0 - phase))


def _pawn_shield_penalty(field: Field, king_x: int, king_y: int,
                         color: SideType, phase: float) -> float:
    '''Штраф за отсутствие пешечного щита перед королём, взвешенный по фазе
    (в эндшпиле щит не нужен — король активен).'''
    if phase <= 0.0:
        return 0.0
    forward = -1 if color == SideType.WHITE else 1   # направление «вперёд»
    penalty = 0.0
    for dx in (-1, 0, 1):
        fx = king_x + dx
        if fx < 0 or fx > 7:
            continue
        shielded = False
        for dy in (1, 2):
            ny = king_y + forward * dy
            if ny < 0 or ny > 7:
                continue
            p = field.at(fx, ny)
            if (not p.is_empty and p.type == PieceType.PAWN
                    and p.color == color):
                shielded = True
                break
        if not shielded:
            penalty += 11.0
    return penalty * phase


def evaluate(field: Field, side: SideType) -> float:
    '''Оценка позиции в сотых пешки со стороны side (больше — лучше для side).

    Состав: материал (без короля) + piece-square таблицы + пешечная структура
    (штраф за сдвоенные и изолированные пешки, бонус за проходные) + бонус за
    разнопольную пару слонов + оценка короля, интерполированная по фазе
    (миттельшпиль — беречь и держать пешечный щит; эндшпиль — выходить в центр).
    Мобильность сознательно не считается: в чистом Python генерация ходов на
    каждом листе замедлила бы движок в разы, а PST уже косвенно поощряет
    развитие фигур.
    '''
    score = 0  # с точки зрения белых
    pawn_files = {SideType.WHITE: [0] * 8, SideType.BLACK: [0] * 8}
    # Клетки пешек каждой стороны — нужны для определения проходных пешек.
    pawn_squares = {SideType.WHITE: [], SideType.BLACK: []}
    # Цвета клеток слонов: 0 и 1. Пара есть только если присутствуют оба цвета.
    bishop_colors = {SideType.WHITE: set(), SideType.BLACK: set()}
    king_pos = {SideType.WHITE: None, SideType.BLACK: None}
    non_pawn_mat = 0
    for x, y, piece in field.pieces():
        t = piece.type
        if t == PieceType.NONE:
            continue
        c = piece.color
        if t == PieceType.KING:
            king_pos[c] = (x, y)
            continue                       # король оценим ниже с учётом фазы
        score += (PIECE_VALUES[t] if c == SideType.WHITE else -PIECE_VALUES[t])
        score += _pst_value(t, x, y, c)
        if t == PieceType.PAWN:
            pawn_files[c][x] += 1
            pawn_squares[c].append((x, y))
        elif t == PieceType.BISHOP:
            bishop_colors[c].add((x + y) % 2)
        if t != PieceType.PAWN:
            non_pawn_mat += PIECE_VALUES[t]

    # Фаза игры: 1.0 — миттельшпиль, 0.0 — эндшпиль.
    phase = non_pawn_mat / _START_NON_PAWN_MAT
    if phase > 1.0:
        phase = 1.0
    elif phase < 0.0:
        phase = 0.0

    # Король: интерполированная PST + пешечный щит (только в миттельшпиле).
    for c in (SideType.WHITE, SideType.BLACK):
        kp = king_pos[c]
        if kp is None:                     # позиция без короля — не случается после parse_fen
            continue
        kx, ky = kp
        sgn = 1 if c == SideType.WHITE else -1
        # _king_pst уже возвращает знак с точки зрения белых (для чёрных — со
        # сменой знака), поэтому прибавляем как есть. Множитель sgn применяем
        # только к штрафу за щит: штраф уменьшает оценку СВОЕЙ стороны.
        score += _king_pst(kx, ky, c, phase)
        score -= sgn * _pawn_shield_penalty(field, kx, ky, c, phase)

    # Пешечная структура: сдвоенные (штраф за каждую лишнюю на файле) и
    # изолированные (нет своих пешек на соседних файлах) пешки.
    for c in (SideType.WHITE, SideType.BLACK):
        files = pawn_files[c]
        sgn = 1 if c == SideType.WHITE else -1
        for fx in range(8):
            n = files[fx]
            if n == 0:
                continue
            if n > 1:
                score -= sgn * 12 * (n - 1)              # сдвоенные
            left = files[fx - 1] if fx > 0 else 0
            right = files[fx + 1] if fx < 7 else 0
            if left == 0 and right == 0:
                score -= sgn * 15 * n                     # изолированные

    # Проходные пешки: на соседних файлах (и своём) впереди нет пешек
    # противника. Бонус растёт с продвижением к превращению — в эндшпиле
    # проходная часто решает партию. Веса по «шагам до превращения» (0..6).
    passed_bonus = (0, 5, 15, 30, 55, 90, 140)
    for c in (SideType.WHITE, SideType.BLACK):
        enemy = SideType.opposite(c)
        enemy_pawns = pawn_squares[enemy]
        # Для белых «впереди» — меньший y, для чёрных — больший.
        forward_sign = -1 if c == SideType.WHITE else 1
        sgn = 1 if c == SideType.WHITE else -1
        for px, py in pawn_squares[c]:
            blocked = False
            for ex, ey in enemy_pawns:
                if abs(ex - px) <= 1 and (ey - py) * forward_sign > 0:
                    blocked = True
                    break
            if blocked:
                continue
            # progress: 0 на начальной горизонтали, 6 у порога превращения.
            progress = (py - 1) if c == SideType.BLACK else (6 - py)
            progress = max(0, min(6, progress))
            score += sgn * passed_bonus[progress]

    # Разнопольная пара: в множестве оба цвета клеток. Несколько слонов на
    # одном цвете дают один элемент и бонус не получают.
    if bishop_colors[SideType.WHITE] == {0, 1}:
        score += 30
    if bishop_colors[SideType.BLACK] == {0, 1}:
        score -= 30

    return score if side == SideType.WHITE else -score


# --- Генерация взятий для quiescence ----------------------------------------

def _is_capture_or_promo(field: Field, move: Move) -> bool:
    if move.is_promotion:
        return True
    if move.is_en_passant:
        return True
    return not field.at(move.to_x, move.to_y).is_empty


def _capture_moves(field: Field, side: SideType,
                  rights: R.CastlingRights, ep: Point) -> list:
    return [m for m in R.pseudo_legal_moves(field, side, rights, ep)
            if _is_capture_or_promo(field, m)]


def _victim_value(field: Field, move: Move) -> int:
    '''Стоимость побитой фигуры (для MVV-LVA и delta-отсечения)'''
    if move.is_en_passant:
        return PIECE_VALUES[PieceType.PAWN]
    target = field.at(move.to_x, move.to_y)
    return PIECE_VALUES[target.type] if not target.is_empty else 0


def _tactic_gain(field: Field, move: Move) -> int:
    '''Материальный потолок хода для delta-отсечения.

    Тихое превращение не бьёт фигуру, но меняет пешку на ферзя/ладью/слона/коня.
    Без этой добавки quiescence выбрасывает такой ход, когда stand-pat уже
    близок к alpha.
    '''
    gain = _victim_value(field, move)
    if move.is_promotion:
        gain += PIECE_VALUES[move.promotion] - PIECE_VALUES[PieceType.PAWN]
    return gain


def _next_halfmove(field: Field, move: Move, halfmove: int) -> int:
    '''Счётчик 50 ходов после хода. Сбрасывается взятием, ходом пешки и превращением.'''
    if move.is_en_passant or move.is_promotion:
        return 0
    if field.at(move.from_x, move.from_y).type == PieceType.PAWN:
        return 0
    if not field.at(move.to_x, move.to_y).is_empty:
        return 0
    return halfmove + 1


def _has_non_pawn_material(field: Field, side: SideType) -> bool:
    '''Есть ли у стороны хоть одна фигура кроме короля и пешек.

    Защита null-move от цугцванга: в эндшпиле K+P пропуск хода может изменить
    оценку, поэтому там null-move не делаем.
    '''
    for _, _, piece in field.pieces(side):
        if piece.type in (PieceType.KNIGHT, PieceType.BISHOP,
                          PieceType.ROOK, PieceType.QUEEN):
            return True
    return False


# --- Результат поиска --------------------------------------------------------

@dataclass
class SearchResult:
    '''Результат поиска'''
    move: Optional[Move] = None
    score: float = 0.0
    depth: int = 0
    nodes: int = 0
    elapsed: float = 0.0
    cancelled: bool = False
    pv: list = None    # главный вариант (список Move), извлекается из TT


# --- Движок ------------------------------------------------------------------

class Engine:
    '''Negamax + alpha-beta + quiescence с итеративным углублением и TT.'''

    def __init__(self, max_depth: int = 3, time_limit: Optional[float] = None,
                 noise_scale: float = 0.0,
                 cancel: Optional[threading.Event] = None,
                 progress: Optional[Callable] = None):
        self.max_depth = max_depth
        self.time_limit = time_limit
        self.noise_scale = noise_scale
        self.cancel = cancel
        self.progress = progress

        self.__nodes = 0
        self.__deadline = inf
        self.__cancelled = False
        self.__killers = {}        # ply -> (move, move) два killer-хода
        self.__history = {}        # (from_x, from_y, to_x, to_y) -> счёт
        self.__pv_move = None      # лучший ход с прошлой итерации (для корня)
        self.__tt = {}             # key -> (depth, flag, value_node_rel, best_move)
        self.__rep_before = Counter()   # ключ -> повторения в истории партии до корня
        self.__path_counter = Counter()  # ключ -> повторения на текущем пути поиска

    # -- Время --

    def __time_is_up(self) -> bool:
        if self.__cancelled:
            return True
        if self.cancel is not None and self.cancel.is_set():
            self.__cancelled = True
            return True
        if perf_counter() >= self.__deadline:
            self.__cancelled = True
            return True
        return False

    # -- Сортировка ходов --

    def __order(self, field: Field, moves: list, ply: int,
                tt_move: Move = None) -> list:
        '''Порядок: TT/PV-ход, взятия (MVV-LVA), превращения, killer, history.'''
        killers = self.__killers.get(ply, (None, None))

        def score(move):
            if tt_move is not None and move == tt_move:
                return 10_000_000
            s = 0
            if _is_capture_or_promo(field, move):
                victim = _victim_value(field, move)
                attacker = PIECE_VALUES[field.at(move.from_x, move.from_y).type]
                s += 1_000_000 + victim * 10 - attacker
                if move.is_promotion:
                    s += PIECE_VALUES[move.promotion]
            else:
                if move == killers[0]:
                    s += 900_000
                elif move == killers[1]:
                    s += 800_000
                else:
                    s += self.__history.get(
                        (move.from_x, move.from_y, move.to_x, move.to_y), 0)
            return s

        return sorted(moves, key=score, reverse=True)

    def __add_killer(self, ply: int, move: Move):
        '''Запомнить тихий ход, вызвавший отсечение, на этой глубине'''
        k0, k1 = self.__killers.get(ply, (None, None))
        if move == k0:
            return
        self.__killers[ply] = (move, k0)

    def __bump_history(self, move: Move, depth: int):
        '''History-эвристика: глубже отсечение — больше вес тихого хода'''
        key = (move.from_x, move.from_y, move.to_x, move.to_y)
        self.__history[key] = self.__history.get(key, 0) + depth * depth

    # -- TT --

    def __tt_probe(self, field: Field, side: SideType, rights: R.CastlingRights,
                   ep: Point, halfmove: int, depth: int, ply: int,
                   alpha: float, beta: float):
        '''Вернуть (tt_key, tt_move, cutoff_value_or_None)'''
        key = self.__tt_slot(R.position_key(field, side, rights, ep), halfmove, depth)
        entry = self.__tt.get(key)
        if entry is None:
            return key, None, None
        e_depth, e_flag, e_value, e_move = entry
        tt_move = e_move
        if e_depth >= depth:
            val = _mate_load(e_value, ply)
            # fail-soft: возвращаем само значение (а не beta/alpha) — точнее
            # и не «протекает» бесконечность при полном окне в корне.
            if e_flag == EXACT:
                return key, tt_move, val
            if e_flag == LOWER_BOUND and val >= beta:
                return key, tt_move, val
            if e_flag == UPPER_BOUND and val <= alpha:
                return key, tt_move, val
        return key, tt_move, None

    def __tt_store(self, key: bytes, depth: int, alpha_orig: float, beta: float,
                   best: float, best_move: Move, ply: int):
        '''Записать результат узла в TT с правильным флагом и мат-кодировкой'''
        if best <= alpha_orig:
            flag = UPPER_BOUND
            move = None     # upper-bound не несёт лучший ход
        elif best >= beta:
            flag = LOWER_BOUND
            move = best_move
        else:
            flag = EXACT
            move = best_move
        self.__tt[key] = (depth, flag, _mate_store(best, ply), move)
        if len(self.__tt) > MAX_TT_ENTRIES:
            self.__tt.clear()

    # -- Quiescence --

    def __tt_slot(self, pos_key: bytes, halfmove: int, depth: int):
        '''Ключ TT. У горизонта правила 50 ходов к ключу добавляется счётчик,
        иначе ничейная оценка с высоким halfmove читалась бы в другой ветке.
        '''
        if halfmove + max(depth, 0) >= 100:
            return (pos_key, halfmove)
        return pos_key

    def __quiesce(self, field: Field, side: SideType, rights: R.CastlingRights,
                  ep: Point, halfmove: int, ply: int, alpha: float, beta: float) -> float:
        self.__nodes += 1
        # Отмена (лимит времени/внешний стоп) проверяется по дешёвому флагу на
        # каждом узле: после отмены нельзя доигрывать оставшееся поддерево —
        # иначе лимит превышается в разы (каждый узел ещё и зовёт evaluate).
        if self.__cancelled:
            return evaluate(field, side)
        if (self.__nodes & 511) == 0 and self.__time_is_up():
            return evaluate(field, side)
        if ply >= MAX_QPLY:
            return evaluate(field, side)

        in_chk = R.in_check(field, side)
        # Правило 50 ходов. Мат важнее: под шахом ничью не возвращаем, пока
        # не ясно, что уклонение есть.
        if halfmove >= 100 and not in_chk:
            return 0.0
        if in_chk:
            # Под шахом stand-pat незаконен: ищем ВСЕ уклонения (evasions).
            # legal_moves уже отфильтрованы по «король не под шахом после хода»,
            # так что повторно in_check не проверяем.
            moves = R.legal_moves(field, side, rights, ep)
            moves = self.__order(field, moves, ply)
            best = -inf
            for move in moves:
                if self.__cancelled:
                    break
                new_half = _next_halfmove(field, move, halfmove)
                undo = R.apply_move(field, move)
                new_rights = R.update_castling_rights(rights, move)
                new_ep = R.en_passant_target(move) if move.is_double_pawn else None
                value = -self.__quiesce(field, SideType.opposite(side), new_rights,
                                        new_ep, new_half, ply + 1, -beta, -alpha)
                R.undo_move(field, undo)
                if self.__cancelled:
                    break
                if value > best:
                    best = value
                    if value > alpha:
                        alpha = value
                if alpha >= beta:
                    break
            if not moves:
                # Нет уклонений из-под шаха — это мат (pat из-под шаха не бывает)
                return -(MATE_SCORE - ply)
            if best == -inf:   # отмена до первого хода — оценка не нужна
                return evaluate(field, side)
            return best

        # Не под шахом: stand-pat + только взятия/превращения
        stand_pat = evaluate(field, side)
        if stand_pat >= beta:
            return stand_pat
        if stand_pat > alpha:
            alpha = stand_pat

        for move in self.__order(field, _capture_moves(field, side, rights, ep), ply):
            if self.__cancelled:
                break
            # Delta-отсечение: даже выиграв взятие, не перебить alpha — пропускаем
            if stand_pat + _tactic_gain(field, move) + DELTA_MARGIN < alpha:
                continue
            new_half = _next_halfmove(field, move, halfmove)
            undo = R.apply_move(field, move)
            if R.in_check(field, side):   # ход оставил своего короля под шахом
                R.undo_move(field, undo)
                continue
            new_rights = R.update_castling_rights(rights, move)
            new_ep = R.en_passant_target(move) if move.is_double_pawn else None
            value = -self.__quiesce(field, SideType.opposite(side), new_rights,
                                    new_ep, new_half, ply + 1, -beta, -alpha)
            R.undo_move(field, undo)
            if self.__cancelled:
                break
            if value >= beta:
                return value
            if value > alpha:
                alpha = value

        return alpha

    # -- Negamax --

    def __negamax(self, field: Field, side: SideType, rights: R.CastlingRights,
                  ep: Point, halfmove: int, depth: int, ply: int,
                  alpha: float, beta: float) -> float:
        self.__nodes += 1
        if self.__cancelled:
            return evaluate(field, side)
        if (self.__nodes & 511) == 0 and self.__time_is_up():
            return evaluate(field, side)
        # Ограничение ply страхует от бесконтрольного роста дерева при
        # check extensions (длинные серии шахов).
        if ply >= 64:
            return evaluate(field, side)

        # Детекция троекратного повторения прямо в поиске: считаем, сколько раз
        # эта позиция возникала в реальной партии до корня (rep_before) и на
        # текущем пути поиска (path_counter). На 3-м возникновении — ничья (0).
        # try/finally гарантирует очистку path_counter при любом возврате.
        key = R.position_key(field, side, rights, ep)
        self.__path_counter[key] += 1
        try:
            if self.__rep_before.get(key, 0) + self.__path_counter[key] >= 3:
                return 0.0

            in_chk = R.in_check(field, side)
            if halfmove >= 100 and not in_chk:
                return 0.0

            alpha_orig = alpha
            _, tt_move, cutoff = self.__tt_probe(field, side, rights, ep,
                                                 halfmove, depth, ply, alpha, beta)
            if cutoff is not None:
                return cutoff

            if depth <= 0:
                return self.__quiesce(field, side, rights, ep, halfmove, ply, alpha, beta)

            # Null-move pruning (R=2): если сторона может «пропустить» ход и всё
            # равно оценка ≥ beta, то реальный ход тем более хорош. Не делаем под
            # шахом, в эндшпиле без не-пешечного материала (защита от цугцванга) и
            # при beta=+inf (полное окно у потомков корня): окно null-move
            # (-beta, -beta+1) вырождается в (-inf, -inf) и возвращает мусор.
            if (depth >= 3 and not in_chk and beta < inf
                    and _has_non_pawn_material(field, side)):
                value = -self.__negamax(field, SideType.opposite(side), rights, None,
                                       halfmove, depth - 1 - 2, ply + 1, -beta, -beta + 1)
                if self.__cancelled:
                    return evaluate(field, side)
                if value >= beta:
                    return beta   # не возвращаем value: null-окно даёт лишь нижнюю границу

            moves = R.pseudo_legal_moves(field, side, rights, ep)
            moves = self.__order(field, moves, ply, tt_move=tt_move)
            best = -inf
            best_move = None
            legal_count = 0
            for move in moves:
                if self.__cancelled:
                    break

                new_half = _next_halfmove(field, move, halfmove)
                undo = R.apply_move(field, move)
                if R.in_check(field, side):   # нелегальный — оставляет короля под боем
                    R.undo_move(field, undo)
                    continue
                legal_count += 1
                new_rights = R.update_castling_rights(rights, move)
                new_ep = R.en_passant_target(move) if move.is_double_pawn else None
                opp = SideType.opposite(side)
                # Check extension: ход даёт шах — ищем на 1 глубже (тактическая зоркость).
                gives_check = R.in_check(field, opp)
                extension = 1 if gives_check else 0
                full_depth = depth - 1 + extension
                # Late move reductions: поздние тихие ходы (не взятие/превращение/шах,
                # не TT-ход, начиная с 4-го рассмотренного) ищем на 1 мельче; при
                # fail-high относительно alpha (включая отсечение по beta) —
                # пересматриваем на полной глубине, чтобы не принять «ложный» cutoff.
                quiet = (not _is_capture_or_promo(field, move)
                         and not gives_check and move != tt_move)
                reduce = 1 if (depth >= 3 and legal_count >= 4 and quiet) else 0
                if reduce:
                    value = -self.__negamax(field, opp, new_rights, new_ep, new_half,
                                            full_depth - 1, ply + 1, -beta, -alpha)
                    if self.__cancelled:
                        R.undo_move(field, undo)
                        break
                    if value > alpha:
                        # Reduced-поиск дал улучшение — перепроверим на полной глубине
                        value = -self.__negamax(field, opp, new_rights, new_ep, new_half,
                                                full_depth, ply + 1, -beta, -alpha)
                else:
                    value = -self.__negamax(field, opp, new_rights, new_ep, new_half,
                                            full_depth, ply + 1, -beta, -alpha)
                R.undo_move(field, undo)

                if self.__cancelled:
                    break

                if value > best:
                    best = value
                    best_move = move
                    if value > alpha:
                        alpha = value
                if alpha >= beta:
                    # Отсечение: запоминаем тихий ход как killer и в history
                    if not _is_capture_or_promo(field, move):
                        self.__add_killer(ply, move)
                        self.__bump_history(move, depth)
                    break

            if legal_count == 0:
                # Нет легальных ходов: мат (если под шахом) или пат (0)
                score = -(MATE_SCORE - ply) if in_chk else 0.0
                # Мат/пат тоже можно закэшировать (EXACT, без хода)
                self.__tt[key] = (depth, EXACT, _mate_store(score, ply), None)
                return score

            if best_move is not None and not self.__time_is_up():
                self.__tt_store(key, depth, alpha_orig, beta, best, best_move, ply)
            return best
        finally:
            c = self.__path_counter[key] - 1
            if c <= 0:
                del self.__path_counter[key]
            else:
                self.__path_counter[key] = c

    # -- Корень: итеративное углубление --

    def __search_root(self, field: Field, side: SideType,
                      rights: R.CastlingRights, ep: Point, halfmove: int, depth: int,
                      alpha: float = -inf, beta: float = inf):
        # ordering: PV-ход с прошлой итерации, иначе TT-ход; затем MVV-LVA и т.д.
        root_key = R.position_key(field, side, rights, ep)
        # Корень учитывается в повторениях потомков: если потомок возвращает
        # позицию корня, это повторение (см. детекцию в __negamax).
        self.__path_counter[root_key] += 1
        entry = self.__tt.get(self.__tt_slot(root_key, halfmove, depth))
        tt_move = entry[3] if entry else None
        hint = self.__pv_move if self.__pv_move is not None else tt_move

        moves = R.pseudo_legal_moves(field, side, rights, ep)
        moves = self.__order(field, moves, 0, tt_move=hint)

        alpha_orig = alpha
        best = -inf
        best_moves = []
        for move in moves:
            new_half = _next_halfmove(field, move, halfmove)
            undo = R.apply_move(field, move)
            if R.in_check(field, side):
                R.undo_move(field, undo)
                continue
            new_rights = R.update_castling_rights(rights, move)
            new_ep = R.en_passant_target(move) if move.is_double_pawn else None
            # Окно сужается по alpha: каждый следующий корневой ход ищется с
            # верхней границей -alpha, давая отсечения в поддереве.
            value = -self.__negamax(field, SideType.opposite(side), new_rights,
                                    new_ep, new_half, depth - 1, 1, -beta, -alpha)
            R.undo_move(field, undo)

            if self.__cancelled:
                break

            if value > best:
                best = value
                best_moves = [move]
                if value > alpha:
                    alpha = value
            elif value == best:
                best_moves.append(move)

            if alpha >= beta:
                # fail-high в корне: найден ход, превышающий верхнюю границу окна
                break

        if best_moves and not self.__cancelled:
            # Флаг записи (EXACT/LOWER/UPPER) определяется сам по alpha_orig/beta,
            # так что аспирационные окна не портят TT неверным «точным» значением.
            self.__tt_store(self.__tt_slot(root_key, halfmove, depth), depth,
                            alpha_orig, beta, best, best_moves[0], 0)
        # Очистка счётчика пути корня (балансирует push в начале __search_root).
        c = self.__path_counter[root_key] - 1
        if c <= 0:
            del self.__path_counter[root_key]
        else:
            self.__path_counter[root_key] = c
        return best, best_moves

    def search(self, field: Field, side: SideType,
               rights: R.CastlingRights, ep: Point = None,
               rep_keys: Optional[list] = None, halfmove: int = 0) -> SearchResult:
        '''Найти лучший ход: итеративное углубление от 1 до max_depth.

        rep_keys — список ключей позиции из реальной партии (включая текущий
        корень последний элементом); нужен, чтобы движок засчитывал ничью по
        троекратному повторению прямо внутри поиска, а не только на уровне Game.
        halfmove — счётчик правила 50 ходов в корне: внутри дерева тихий ход,
        доводящий его до 100, оценивается как ничья (мат при этом важнее).
        '''
        started = perf_counter()
        self.__nodes = 0
        self.__cancelled = False
        self.__killers.clear()
        self.__history.clear()
        self.__tt.clear()
        self.__pv_move = None
        self.__deadline = started + self.time_limit if self.time_limit else inf
        # Повторения до корня: всё, кроме последнего (текущего) ключа истории.
        self.__rep_before = Counter()
        if rep_keys:
            for k in rep_keys[:-1]:
                self.__rep_before[k] += 1
        self.__path_counter = Counter()

        # Быстрая проверка: есть ли хоть один легальный ход
        root_moves = R.pseudo_legal_moves(field, side, rights, ep)
        has_legal = False
        for move in root_moves:
            undo = R.apply_move(field, move)
            ok = not R.in_check(field, side)
            R.undo_move(field, undo)
            if ok:
                has_legal = True
                break
        if not has_legal:
            return SearchResult(elapsed=perf_counter() - started)

        best_move = None
        best_score = 0.0
        reached_depth = 0
        prev_score = None      # оценка прошлой итерации — для аспирационного окна

        for depth in range(1, max(1, self.max_depth) + 1):
            # Аспирационные окна: с 4-й глубины ищем в узком окне вокруг оценки
            # прошлой итерации — это даёт отсечения и в поддереве, и в самом корне.
            # При выходе за окно (fail-low/fail-high) — полный пересмотр.
            if (depth >= 4 and best_move is not None and prev_score is not None
                    and abs(prev_score) < MATE_THRESHOLD):
                window = 50.0
                a = prev_score - window
                b = prev_score + window
                score, candidates = self.__search_root(field, side, rights, ep,
                                                       halfmove, depth, a, b)
                if not self.__cancelled and (score <= a or score >= b):
                    score, candidates = self.__search_root(field, side, rights, ep,
                                                           halfmove, depth, -inf, inf)
            else:
                score, candidates = self.__search_root(field, side, rights, ep,
                                                       halfmove, depth)
            if candidates and not self.__cancelled:
                best_move = candidates[0]
                best_score = score
                reached_depth = depth
                self.__pv_move = best_move      # в следующей итерации пробуем первым
                prev_score = score
            if self.progress is not None:
                try:
                    self.progress(depth, self.max_depth, best_move, best_score)
                except Exception:
                    pass
            if self.__cancelled or depth >= self.max_depth:
                break
            if abs(score) >= MATE_THRESHOLD:
                # Найден мат — углубляться незачем
                break

        # Осмысленная случайность: на лёгких уровнях выбираем среди ходов,
        # близких к лучшему, чтобы ИИ не играл детерминированно и не слишком сильно.
        if self.noise_scale > 0 and best_move is not None and not self.__cancelled:
            scored = []
            for move in root_moves:
                new_half = _next_halfmove(field, move, halfmove)
                undo = R.apply_move(field, move)
                if R.in_check(field, side):
                    R.undo_move(field, undo)
                    continue
                new_rights = R.update_castling_rights(rights, move)
                new_ep = R.en_passant_target(move) if move.is_double_pawn else None
                value = -self.__negamax(field, SideType.opposite(side), new_rights,
                                        new_ep, new_half, max(0, reached_depth - 1), 1, -inf, inf)
                R.undo_move(field, undo)
                scored.append((value, move))
                if self.__cancelled:
                    scored = []
                    break
            if scored:
                top = max(value for value, _ in scored)
                close = [move for value, move in scored if top - value <= self.noise_scale]
                if close:
                    best_move = random.choice(close)

        # Главный вариант: идём по best-move из TT, пока запись есть и ход
        # легален. TT после поиска сохранён, поэтому достаточно проследовать по
        # нему из корня (поле восстанавливается откатом).
        pv = (self._extract_pv(field, side, rights, ep, halfmove)
              if best_move is not None else [])

        # Гарантия: если поиск прерван отменой и лучшего хода нет — вернуть
        # любой легальный. В UI это критично: ИИ не должен «замораживать» партию.
        if best_move is None and has_legal:
            for m in root_moves:
                u = R.apply_move(field, m)
                ok = not R.in_check(field, side)
                R.undo_move(field, u)
                if ok:
                    best_move = m
                    break

        return SearchResult(
            move=best_move,
            score=best_score,
            depth=reached_depth,
            nodes=self.__nodes,
            elapsed=perf_counter() - started,
            cancelled=self.__cancelled,
            pv=pv,
        )

    def __tt_pv_entry(self, pos_key: bytes, halfmove: int):
        '''Запись TT для текущего счётчика 50 ходов.

        Запись без счётчика пишется только при halfmove + depth < 100.
        Если при этом счётчике горизонт правила 50 уже близко, такая запись
        относится к другой истории ходов и в главный вариант не берётся.
        '''
        qualified = self.__tt.get((pos_key, halfmove))
        plain = self.__tt.get(pos_key)
        if qualified is not None and (plain is None or halfmove + qualified[0] >= 100):
            return qualified
        if plain is not None and halfmove + plain[0] < 100:
            return plain
        return qualified

    def _extract_pv(self, field: Field, side: SideType,
                    rights: R.CastlingRights, ep: Point, halfmove: int = 0,
                    max_plies: int = 8) -> list:
        '''Главный вариант из таблицы транспозиций (best-move-line).'''
        pv = []
        undos = []
        seen = set()
        s, r, e, hm = side, rights, ep, halfmove
        for _ in range(max_plies):
            key = R.position_key(field, s, r, e)
            if key in seen:
                break
            seen.add(key)
            entry = self.__tt_pv_entry(key, hm)
            if entry is None or entry[3] is None:
                break
            move = entry[3]
            hm = _next_halfmove(field, move, hm)
            undo = R.apply_move(field, move)
            if R.in_check(field, s):   # TT хранит легальный best-move, но подстрахуемся
                R.undo_move(field, undo)
                break
            pv.append(move)
            undos.append(undo)
            r = R.update_castling_rights(r, move)
            e = R.en_passant_target(move) if move.is_double_pawn else None
            s = SideType.opposite(s)
        for undo in reversed(undos):
            R.undo_move(field, undo)
        return pv
