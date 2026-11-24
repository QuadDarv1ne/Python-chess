"""Состояние шахматной партии: поле, очередь хода, права, счётчики, история.

Game отвечает за всё, что rules.py намеренно не хранит: чей ход, права
рокировки, клетку en passant, счётчик полуходов для правила 50 ходов, номер
хода, историю для отмены и ключи позиций для троекратного повторения. Также
здесь живёт нотация SAN для панели истории.

Координаты — как в field.py и rules.py: x = 0..7 (a..h), y = 0..7 (8..1).
"""
import re
from collections import Counter
from dataclasses import dataclass

from chess_game import rules as R
from chess_game.enums import PieceType, SideType, DifficultyType
from chess_game.field import Field
from chess_game.move import Move
from chess_game.point import Point
from chess_game.constants import PIECE_VALUES


# --- Статус партии ----------------------------------------------------------

# Активные состояния (игра идёт)
ACTIVE = {'normal', 'check'}
# Ничьи
DRAWS = {'stalemate', 'draw_50', 'draw_repetition', 'draw_insufficient'}

_STANDARD_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

_STATUS_RU = {
    'normal': 'Игра идёт',
    'check': 'Шах!',
    'checkmate': 'Мат',
    'stalemate': 'Пат — ничья',
    'draw_50': 'Ничья (правило 50 ходов)',
    'draw_repetition': 'Ничья (троекратное повторение)',
    'draw_insufficient': 'Ничья (недостаточный материал)',
}


def _fen_counter(token: str, name: str, minimum: int) -> int:
    '''Числовое поле FEN. Неверный текст не подменяется нулём.'''
    if not token.isdigit():
        raise ValueError(f'некорректный {name} в FEN: {token!r}')
    value = int(token)
    if value < minimum:
        raise ValueError(f'{name} в FEN не может быть меньше {minimum}: {token!r}')
    return value


def square_name(x: int, y: int) -> str:
    '''Имя клетки в нотации: (0,7) → "a1", (4,0) → "e8"'''
    return f"{chr(ord('a') + x)}{8 - y}"


_FEN_PIECES = {
    'K': (PieceType.KING, SideType.WHITE), 'Q': (PieceType.QUEEN, SideType.WHITE),
    'R': (PieceType.ROOK, SideType.WHITE), 'B': (PieceType.BISHOP, SideType.WHITE),
    'N': (PieceType.KNIGHT, SideType.WHITE), 'P': (PieceType.PAWN, SideType.WHITE),
    'k': (PieceType.KING, SideType.BLACK), 'q': (PieceType.QUEEN, SideType.BLACK),
    'r': (PieceType.ROOK, SideType.BLACK), 'b': (PieceType.BISHOP, SideType.BLACK),
    'n': (PieceType.KNIGHT, SideType.BLACK), 'p': (PieceType.PAWN, SideType.BLACK),
}


def parse_fen(fen: str):
    '''Разбор FEN → (field, side, rights, ep, halfmove, fullmove).

    Поля «расстановка» и «сторона» обязательны; рокировка, en passant и
    счётчики при отсутствии принимают значения по умолчанию (прав нет, ep нет,
    0 / 1). Неверный FEN вызывает ValueError.
    '''
    parts = fen.strip().split()
    if len(parts) < 2:
        raise ValueError(f'FEN должен содержать расстановку и сторону: {fen!r}')
    placement, side_ch = parts[0], parts[1]
    if side_ch not in ('w', 'b'):
        raise ValueError(f'сторона в FEN должна быть w/b: {side_ch!r}')
    side = SideType.WHITE if side_ch == 'w' else SideType.BLACK

    cr = parts[2] if len(parts) > 2 else '-'
    rights = R.CastlingRights(
        wk='K' in cr, wq='Q' in cr, bk='k' in cr, bq='q' in cr)

    ep = None
    if len(parts) > 3 and parts[3] != '-':
        s = parts[3]
        if len(s) == 2 and 'a' <= s[0] <= 'h' and '1' <= s[1] <= '8':
            ep = Point(ord(s[0]) - ord('a'), 8 - int(s[1]))
        else:
            raise ValueError(f'некорректная клетка en passant в FEN: {s!r}')

    halfmove = _fen_counter(parts[4], 'счётчик полуходов', 0) if len(parts) > 4 else 0
    fullmove = _fen_counter(parts[5], 'номер хода', 1) if len(parts) > 5 else 1

    field = Field.empty()
    y = 0
    x = 0
    for ch in placement:
        if ch == '/':
            if x != 8:
                raise ValueError(f'горизонталь {8 - y} в FEN не из 8 клеток: {placement!r}')
            y += 1
            x = 0
            if y >= 8:
                raise ValueError(f'слишком много горизонталей в FEN: {placement!r}')
        elif ch.isdigit():
            if ch == '0':
                raise ValueError(f'нулевая пустая клетка в FEN: {placement!r}')
            x += int(ch)
            if x > 8:
                raise ValueError(f'слишком длинная горизонталь в FEN: {placement!r}')
        elif ch in _FEN_PIECES:
            if x >= 8:
                raise ValueError(f'слишком длинная горизонталь в FEN: {placement!r}')
            ptype, color = _FEN_PIECES[ch]
            field.set_piece(x, y, ptype, color)
            x += 1
        else:
            raise ValueError(f'неизвестный символ в FEN: {ch!r}')
    if x != 8:
        raise ValueError(f'горизонталь {8 - y} в FEN не из 8 клеток: {placement!r}')
    if y != 7:
        raise ValueError(f'ожидалось 8 горизонталей в FEN, получено {y + 1}')
    # У каждой стороны должен быть ровно один король — иначе позиция некорректна
    # и генерация хода/шаха поведёт себя непредсказуемо.
    wk = bk = 0
    for _, _, p in field.pieces():
        if p.type == PieceType.KING:
            if p.color == SideType.WHITE:
                wk += 1
            else:
                bk += 1
    if wk != 1 or bk != 1:
        raise ValueError(f'в FEN должно быть по одному королю у каждой стороны '
                         f'(белых: {wk}, чёрных: {bk})')
    # Пешки не могут стоять на крайних горизонталях: попасть туда можно только
    # превращением, после которого пешка сменяется на фигуру.
    for x, y, p in field.pieces():
        if p.type == PieceType.PAWN and (y == 0 or y == 7):
            raise ValueError(f'пешка не может стоять на крайней горизонтали '
                             f'({square_name(x, y)} в FEN {fen!r})')
    # Сторона, НЕ ходящая в этот ход, не может быть под шахом — иначе предыдущий
    # игрок оставил бы своего короля под боем, что незаконно.
    if R.in_check(field, SideType.opposite(side)):
        raise ValueError(f'в FEN сторона без хода под шахом — позиция нелегальна: '
                         f'{fen!r}')
    _validate_castling(field, rights)
    _validate_en_passant(field, side, ep)
    return field, side, rights, ep, halfmove, fullmove


def _validate_castling(field: Field, rights: R.CastlingRights):
    '''Права рокировки возможны только с королём и ладьёй на исходных клетках.'''
    checks = (
        (rights.wk or rights.wq, 4, 7, SideType.WHITE, 'белых'),
        (rights.bk or rights.bq, 4, 0, SideType.BLACK, 'чёрных'),
    )
    for needed, kx, ky, color, name in checks:
        if not needed:
            continue
        king = field.at(kx, ky)
        if king.type != PieceType.KING or king.color != color:
            raise ValueError(f'права рокировки {name} без короля на '
                             f'{square_name(kx, ky)}')
    rooks = (
        (rights.wk, 7, 7, SideType.WHITE, 'K'),
        (rights.wq, 0, 7, SideType.WHITE, 'Q'),
        (rights.bk, 7, 0, SideType.BLACK, 'k'),
        (rights.bq, 0, 0, SideType.BLACK, 'q'),
    )
    for flag, rx, ry, color, tag in rooks:
        if not flag:
            continue
        rook = field.at(rx, ry)
        if rook.type != PieceType.ROOK or rook.color != color:
            raise ValueError(f'право рокировки {tag} без ладьи на '
                             f'{square_name(rx, ry)}')


def _validate_en_passant(field: Field, side: SideType, ep: Point):
    '''Клетка en passant — пустая, на 3-й/6-й горизонтали, за ней пешка двойного хода.'''
    if ep is None:
        return
    if side == SideType.WHITE:
        if ep.y != 2:
            raise ValueError(f'en passant при ходе белых только на 6-й горизонтали, '
                             f'получено {square_name(ep.x, ep.y)}')
        pawn_y, pawn_color = 3, SideType.BLACK
    else:
        if ep.y != 5:
            raise ValueError(f'en passant при ходе чёрных только на 3-й горизонтали, '
                             f'получено {square_name(ep.x, ep.y)}')
        pawn_y, pawn_color = 4, SideType.WHITE
    if not field.at(ep.x, ep.y).is_empty:
        raise ValueError(f'клетка en passant {square_name(ep.x, ep.y)} занята')
    pawn = field.at(ep.x, pawn_y)
    if pawn.type != PieceType.PAWN or pawn.color != pawn_color:
        raise ValueError(f'нет пешки двойного хода за клеткой en passant '
                         f'{square_name(ep.x, ep.y)}')


# --- Разбор SAN (для импорта PGN) -------------------------------------------

_LETTER_PIECE = {
    'K': PieceType.KING, 'Q': PieceType.QUEEN, 'R': PieceType.ROOK,
    'B': PieceType.BISHOP, 'N': PieceType.KNIGHT,
}

# SAN хода: [фигура][файл/ранг разыменования][x]клетка[=превращение]
_SAN_MOVE_RE = re.compile(
    r'^(?P<piece>[NBRQK])?'
    r'(?P<ff>[a-h])?(?P<fr>[1-8])?'
    r'(?P<cap>x)?'
    r'(?P<tf>[a-h])(?P<tr>[1-8])'
    r'(?:=?(?P<promo>[NBRQ]))?$'
)


def _strip_pgn_movetext(text: str) -> str:
    '''Убрать из текста ходов комментарии {...}, «;» до конца строки, строки «%»,
    вложенные варианты (...) и оставить только верхний уровень.'''
    out = []
    depth = 0
    i, n = 0, len(text)
    line_start = True
    while i < n:
        ch = text[i]
        if depth == 0 and ch == '{':
            j = text.find('}', i)
            i = j + 1 if j != -1 else n
            line_start = False
            continue
        if depth == 0 and ch == ';':
            j = text.find('\n', i)
            i = n if j == -1 else j
            continue
        if depth == 0 and line_start and ch == '%':
            j = text.find('\n', i)
            i = n if j == -1 else j
            continue
        if ch == '(':
            depth += 1
            i += 1
            line_start = False
            continue
        if ch == ')' and depth > 0:
            depth -= 1
            i += 1
            continue
        if depth == 0:
            out.append(ch)
        if ch == '\n':
            line_start = True
        elif not ch.isspace():
            line_start = False
        i += 1
    return ''.join(out)


def _first_pgn_game(pgn_text: str) -> str:
    '''Текст только первой партии. Следующий заголовок «[» после ходов начинает новую.'''
    kept = []
    seen_body = False
    for line in pgn_text.splitlines():
        stripped = line.strip()
        if seen_body and stripped.startswith('['):
            break
        kept.append(line)
        if stripped and not stripped.startswith('['):
            seen_body = True
    return '\n'.join(kept)


def _tokenize_pgn(text: str) -> list:
    '''Список SAN-токенов из очищенного текста ходов.'''
    tokens = text.split()
    moves = []
    for tok in tokens:
        if tok in ('1-0', '0-1', '1/2-1/2', '*'):
            continue
        if tok.startswith('$'):          # NAG-аннотации
            continue
        tok = re.sub(r'^\d+\.(\.\.)?', '', tok)   # «1.»/«1...» (в т.ч. слитно: «1.e4»)
        if not tok:
            continue
        moves.append(tok)
    return moves


@dataclass
class HistoryEntry:
    '''Запись истории одного полухода для отмены и для панели ходов'''
    move: Move
    san: str            # нотация хода в позиции ДО него
    side: SideType      # кто ходил
    move_number: int    # номер хода (для белых) в момент хода
    # Снимок состояния до хода — нужен для отмены
    prev_rights: R.CastlingRights
    prev_ep: Point
    prev_halfmove: int
    prev_fullmove: int
    prev_status: str
    prev_field_undo: dict    # piece-level undo от rules.apply_move
    prev_rep_key: bytes      # ключ позиции, добавленный после этого хода


class Game:
    '''Шахматная партия: состояние, ходы, история, статус, нотация.'''

    def __init__(self, player_side: SideType = SideType.WHITE,
                 difficulty: DifficultyType = DifficultyType.MEDIUM):
        self.__player_side = player_side
        self.__difficulty = difficulty
        self.reset()

    # -- Параметры партии --

    @property
    def player_side(self):
        return self.__player_side

    @property
    def difficulty(self):
        return self.__difficulty

    def set_difficulty(self, difficulty: DifficultyType):
        self.__difficulty = difficulty

    def set_player_side(self, side: SideType):
        self.__player_side = side

    # -- Текущее состояние --

    @property
    def field(self) -> Field:
        return self.__field

    @property
    def side_to_move(self) -> SideType:
        return self.__side_to_move

    @property
    def castling_rights(self) -> R.CastlingRights:
        return self.__rights

    @property
    def en_passant_target(self):
        return self.__ep

    @property
    def halfmove_clock(self) -> int:
        return self.__halfmove

    @property
    def fullmove_number(self) -> int:
        return self.__fullmove

    @property
    def status(self) -> str:
        return self.__status

    @property
    def status_ru(self) -> str:
        return _STATUS_RU.get(self.__status, self.__status)

    @property
    def is_game_over(self) -> bool:
        return self.__status not in ACTIVE

    @property
    def history(self):
        '''Список HistoryEntry (в порядке ходов)'''
        return self.__history

    def reset(self):
        '''Новая партия с текущими player_side / difficulty'''
        self.__field = Field()
        self.__side_to_move = SideType.WHITE
        self.__rights = R.CastlingRights()
        self.__ep = None
        self.__halfmove = 0
        self.__fullmove = 1
        self.__status = 'normal'
        self.__history = []
        self.__rep_keys = []
        self.__rep_counter = Counter()
        self.__start_fen = None
        self.__record_position()

    @classmethod
    def from_position(cls, field: Field, side: SideType = SideType.WHITE,
                      rights: 'R.CastlingRights' = None, ep: Point = None,
                      halfmove: int = 0, fullmove: int = 1,
                      player_side: SideType = SideType.WHITE,
                      difficulty: DifficultyType = DifficultyType.MEDIUM) -> 'Game':
        '''Партия из заданной позиции — для тестов и будущей загрузки FEN/PGN.

        В отличие от reset(), расстановку и счётчики задаёт вызывающий.
        '''
        game = cls.__new__(cls)
        game._Game__player_side = player_side
        game._Game__difficulty = difficulty
        game._Game__field = field
        game._Game__side_to_move = side
        game._Game__rights = rights if rights is not None else R.CastlingRights()
        game._Game__ep = ep
        game._Game__halfmove = halfmove
        game._Game__fullmove = fullmove
        game._Game__history = []
        game._Game__rep_keys = []
        game._Game__rep_counter = Counter()
        game._Game__start_fen = None
        game._Game__record_position()
        game._Game__status = game._Game__compute_status()
        game._Game__start_fen = game.fen()
        return game

    @classmethod
    def from_fen(cls, fen: str, player_side: SideType = None,
                 difficulty: DifficultyType = DifficultyType.MEDIUM) -> 'Game':
        '''Партия из строки FEN.

        Формат: «расстановка сторона рокировка en_passant полуход полный_ход».
        Счётчики и сторону хода берёт из FEN; player_side — кто управляет
        фигурами в UI (по умолчанию сторона, чья очередь хода).
        '''
        field, side, rights, ep, halfmove, fullmove = parse_fen(fen)
        if player_side is None:
            player_side = side
        return cls.from_position(field, side=side, rights=rights, ep=ep,
                                 halfmove=halfmove, fullmove=fullmove,
                                 player_side=player_side, difficulty=difficulty)

    @classmethod
    def from_pgn(cls, pgn_text: str, player_side: SideType = None,
                 difficulty: DifficultyType = DifficultyType.MEDIUM) -> 'Game':
        '''Партия из текста PGN: разыграет ходы и вернёт позицию.

        Разбирает заголовки (в т.ч. [FEN] для нестандартной расстановки),
        выкидывает комментарии {...}, вложенные варианты (...), NAG ($n), номера
        ходов и результат. Каждый SAN-токен сопоставляется с легальным ходом
        через from_san. При невозможном ходе — ValueError с номером хода.
        '''
        pgn_text = _first_pgn_game(pgn_text)
        # Заголовки [Key "Value"]
        headers = dict(re.findall(r'\[(\w+)\s+"([^"]*)"\]', pgn_text))
        # Тело без строк-заголовков
        body = re.sub(r'^\[.*\]\s*$', '', pgn_text, flags=re.MULTILINE).strip()
        fen = headers.get('FEN')
        if fen:
            game = cls.from_fen(fen, player_side=player_side, difficulty=difficulty)
        else:
            game = cls(player_side=player_side or SideType.WHITE,
                       difficulty=difficulty)
        tokens = _tokenize_pgn(_strip_pgn_movetext(body))
        for i, san in enumerate(tokens, start=1):
            try:
                move = game.from_san(san)
            except ValueError as e:
                raise ValueError(f'ход {i} «{san}»: {e}')
            if not game.make_move(move):
                raise ValueError(f'ход {i} «{san}» нелегален в текущей позиции')
        return game

    # -- Повторы позиций --

    def __record_position(self):
        key = R.position_key(self.__field, self.__side_to_move, self.__rights, self.__ep)
        self.__rep_keys.append(key)
        self.__rep_counter[key] += 1

    def __repetition_count(self) -> int:
        key = R.position_key(self.__field, self.__side_to_move, self.__rights, self.__ep)
        return self.__rep_counter.get(key, 0)

    def repetition_keys(self) -> list:
        '''Ключи позиции из истории партии (включая текущую позицию последней).

        Используется движком для детекции троекратного повторения внутри поиска.
        '''
        return list(self.__rep_keys)

    # -- Ходы --

    def legal_moves(self) -> list:
        '''Легальные ходы стороны, чья очередь'''
        return R.legal_moves(self.__field, self.__side_to_move, self.__rights, self.__ep)

    def legal_moves_from(self, x: int, y: int) -> list:
        '''Легальные ходы фигуры на (x, y) — для подсветки в UI'''
        piece = self.__field.at(x, y)
        if piece.is_empty or piece.color != self.__side_to_move:
            return []
        return [m for m in self.legal_moves()
                if m.from_x == x and m.from_y == y]

    def is_legal_move(self, move: Move) -> bool:
        return move in self.legal_moves()

    def make_move(self, move: Move) -> bool:
        '''Сделать ход. Возвращает True, если ход был применён.

        Перед применением ход проверяется на легальность, чтобы UI и движок
        не могли провести нелегальный ход (движок возвращает всегда легальный,
        но проверка дешёвая и страхует от багов). После мата или ничьей
        партия не продолжается, даже если на доске ещё есть геометрические ходы.
        '''
        if self.is_game_over:
            return False
        legal = self.legal_moves()
        if move not in legal:
            # Сравнение по содержимому: найдём совпадающий, чтобы взять «канонический»
            # объект с теми же полями (на случай разных экземпляров Move)
            match = None
            for cand in legal:
                if cand == move:
                    match = cand
                    break
            if match is None:
                return False
            move = match

        san = self.to_san(move)
        side = self.__side_to_move
        move_number = self.__fullmove

        # Снимок состояния до хода
        prev_rights = self.__rights
        prev_ep = self.__ep
        prev_halfmove = self.__halfmove
        prev_fullmove = self.__fullmove
        prev_status = self.__status

        # Применяем ход к полю; запоминаем piece-level undo
        field_undo = R.apply_move(self.__field, move)

        # Сброс счётчика 50 ходов: взятие, превращение или ход пешки.
        # Тип ходившей фигуры берём из undo — после apply_move на клетке
        # назначения уже может стоять превращённая фигура.
        is_capture = (field_undo['captured'] is not None) or move.is_en_passant
        moved_was_pawn = field_undo['moved_type'] == PieceType.PAWN
        reset_clock = is_capture or move.is_promotion or moved_was_pawn

        # Обновляем права и en passant
        self.__rights = R.update_castling_rights(self.__rights, move)
        self.__ep = R.en_passant_target(move) if move.is_double_pawn else None

        # Счётчики
        self.__halfmove = 0 if reset_clock else self.__halfmove + 1
        if side == SideType.BLACK:
            self.__fullmove += 1

        # Очередь — противнику
        self.__side_to_move = SideType.opposite(side)

        # Записываем позицию в историю повторов ПЕРЕД вычислением статуса:
        # статус «троекратное повторение» смотрит на текущую позицию.
        self.__record_position()
        prev_rep_key = self.__rep_keys[-1]

        # Пересчитываем статус
        self.__status = self.__compute_status()

        entry = HistoryEntry(
            move=move, san=san, side=side, move_number=move_number,
            prev_rights=prev_rights, prev_ep=prev_ep,
            prev_halfmove=prev_halfmove, prev_fullmove=prev_fullmove,
            prev_status=prev_status, prev_field_undo=field_undo,
            prev_rep_key=prev_rep_key,
        )
        self.__history.append(entry)
        return True

    def undo(self) -> bool:
        '''Отменить последний ход. Возвращает True, если отмена была.'''
        if not self.__history:
            return False
        entry = self.__history.pop()

        # Откат piece-level
        R.undo_move(self.__field, entry.prev_field_undo)

        # Восстанов состояния
        self.__rights = entry.prev_rights
        self.__ep = entry.prev_ep
        self.__halfmove = entry.prev_halfmove
        self.__fullmove = entry.prev_fullmove
        self.__side_to_move = entry.side
        self.__status = entry.prev_status

        # Убираем ключ позиции из истории повторов
        if self.__rep_keys:
            key = self.__rep_keys.pop()
            self.__rep_counter[key] -= 1
            if self.__rep_counter[key] <= 0:
                del self.__rep_counter[key]
        return True

    # -- Статус --

    def __compute_status(self) -> str:
        '''Текущий статус: активный / мат / пат / ничья по правилам'''
        base = R.game_status(self.__field, self.__side_to_move, self.__rights, self.__ep)
        if base in ('checkmate', 'stalemate'):
            return base
        # Ничьи по правилам (поверх 'normal' / 'check')
        if self.__halfmove >= 100:
            return 'draw_50'
        if self.__repetition_count() >= 3:
            return 'draw_repetition'
        if self.__insufficient_material():
            return 'draw_insufficient'
        return base

    def __insufficient_material(self) -> bool:
        '''Недостаточный материал для мата: только короли, K+минор (конь/слон),
        K+B vs K+B со слонами на одном цвете клеток. Тяжёлая фигура или пешка
        означает, что мата достаточно.
        '''
        minors = []  # (тип, цвет_клетки)
        for x, y, piece in self.__field.pieces():
            t = piece.type
            if t in (PieceType.PAWN, PieceType.ROOK, PieceType.QUEEN):
                return False
            if t in (PieceType.BISHOP, PieceType.KNIGHT):
                minors.append((t, (x + y) % 2))
        if not minors:
            return True                       # голые короли
        if len(minors) == 1:
            return True                       # K + минор vs K
        if len(minors) == 2:
            if minors[0][0] == PieceType.BISHOP and minors[1][0] == PieceType.BISHOP \
                    and minors[0][1] == minors[1][1]:
                return True                   # одноцветные слоны
        return False

    # -- Нотация SAN --

    def to_san(self, move: Move) -> str:
        '''Стандартная алгебраическая нотация хода в текущей позиции.

        Упрощённая: разыменование коллизий по файлу/рангу, шах/мат суффиксы,
        превращение, рокировка. Без аннотаций (!?, +/−).
        '''
        if move.is_castle:
            base = 'O-O' if move.castle_side == 'K' else 'O-O-O'
            return base + self.__check_suffix(move)

        piece = self.__field.at(move.from_x, move.from_y)
        ptype = piece.type
        is_capture = (not self.__field.at(move.to_x, move.to_y).is_empty) or move.is_en_passant

        if ptype == PieceType.PAWN:
            if is_capture:
                base = f"{chr(ord('a') + move.from_x)}x{square_name(move.to_x, move.to_y)}"
            else:
                base = square_name(move.to_x, move.to_y)
            if move.is_promotion:
                base += '=' + move.promotion.letter
            return base + self.__check_suffix(move)

        # Не-пешка: буква + разыменование + взятие + клетка
        letter = ptype.letter
        disamb = self.__disambiguation(move, ptype)
        base = letter + disamb + ('x' if is_capture else '') + square_name(move.to_x, move.to_y)
        return base + self.__check_suffix(move)

    def __disambiguation(self, move: Move, ptype: PieceType) -> str:
        '''Файл/ранг/клетка, чтобы отличить от других однотипных фигур'''
        others = []
        for m in self.legal_moves():
            if m.to_x != move.to_x or m.to_y != move.to_y:
                continue
            if m.from_x == move.from_x and m.from_y == move.from_y:
                continue
            p = self.__field.at(m.from_x, m.from_y)
            if p.type == ptype and p.color == self.__side_to_move:
                others.append(m)
        if not others:
            return ''
        same_file = any(m.from_x == move.from_x for m in others)
        same_rank = any(m.from_y == move.from_y for m in others)
        if not same_file:
            return chr(ord('a') + move.from_x)
        if not same_rank:
            return str(8 - move.from_y)
        return square_name(move.from_x, move.from_y)

    def __check_suffix(self, move: Move) -> str:
        '''+' при шахе, '#' при мате после хода'''
        undo = R.apply_move(self.__field, move)
        opp = SideType.opposite(self.__side_to_move)
        suffix = ''
        if R.in_check(self.__field, opp):
            has_move = bool(R.legal_moves(
                self.__field, opp,
                R.update_castling_rights(self.__rights, move),
                R.en_passant_target(move) if move.is_double_pawn else None))
            suffix = '#' if not has_move else '+'
        R.undo_move(self.__field, undo)
        return suffix

    def from_san(self, san: str) -> Move:
        '''Найти легальный ход по строке SAN в текущей позиции.

        Поддерживает рокировку (O-O / 0-0), взятия, разыменование по файлу/рангу,
        превращение (=Q или Q), суффиксы +/#!/? и приклеенный NAG ($1). Возвращает
        единственный совпавший ход; при отсутствии или неоднозначности — ValueError.
        '''
        s = san.strip()
        s = re.sub(r'\$\d+$', '', s)   # NAG, приклеенный к ходу: «e4$1»
        s = s.rstrip('+#!?')
        # Рокировка (допускаем и «0» вместо «O»)
        if s in ('O-O', '0-0'):
            for m in self.legal_moves():
                if m.is_castle and m.castle_side == 'K':
                    return m
            raise ValueError(f'рокировка {san!r} недоступна')
        if s in ('O-O-O', '0-0-0'):
            for m in self.legal_moves():
                if m.is_castle and m.castle_side == 'Q':
                    return m
            raise ValueError(f'рокировка {san!r} недоступна')

        m = _SAN_MOVE_RE.match(s)
        if not m:
            raise ValueError(f'не удалось разобрать SAN: {san!r}')
        ptype = _LETTER_PIECE[m.group('piece')] if m.group('piece') else PieceType.PAWN
        ff = m.group('ff')
        fr = m.group('fr')
        cap = m.group('cap')
        tx = ord(m.group('tf')) - ord('a')
        ty = 8 - int(m.group('tr'))
        promo_type = _LETTER_PIECE[m.group('promo')] if m.group('promo') else None

        matches = []
        for mv in self.legal_moves():
            piece = self.__field.at(mv.from_x, mv.from_y)
            if piece.type != ptype:
                continue
            if mv.to_x != tx or mv.to_y != ty:
                continue
            if ff and mv.from_x != ord(ff) - ord('a'):
                continue
            if fr and mv.from_y != 8 - int(fr):
                continue
            if promo_type:
                if not mv.is_promotion or mv.promotion != promo_type:
                    continue
            elif mv.is_promotion:
                continue   # SAN без «=» — не превращение
            if cap:
                target = self.__field.at(mv.to_x, mv.to_y)
                if target.is_empty and not mv.is_en_passant:
                    continue
            matches.append(mv)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f'нет легального хода для SAN {san!r}')
        raise ValueError(f'SAN {san!r} неоднозначен ({len(matches)} легальных совпадений)')

    # -- Для UI: итог по партии --

    def result_ru(self) -> str:
        '''Итог партии по-русски для строки статуса'''
        st = self.__status
        if st == 'checkmate':
            winner = SideType.opposite(self.__side_to_move)
            return f'Мат. Победа {winner.name_ru.lower()}'
        if st == 'stalemate':
            return 'Пат — ничья'
        if st in DRAWS:
            return _STATUS_RU[st]
        if st == 'check':
            return f'Шах {self.__side_to_move.name_ru.lower()}'
        return f'Ход {self.__side_to_move.name_ru.lower()}'

    def move_list_text(self) -> list:
        '''Список строк «1. e4 e5» для панели истории.

        Если партия начата с хода чёрных, первая строка — «3... Nf6», а не
        «3. Nf6»: иначе ход чёрных выглядит ходом белых.
        '''
        lines = []
        hist = self.__history
        i = 0
        if hist and hist[0].side == SideType.BLACK:
            lines.append(f'{hist[0].move_number}... {hist[0].san}')
            i = 1
        while i < len(hist):
            num = hist[i].move_number
            white = hist[i].san
            if i + 1 < len(hist) and hist[i + 1].side == SideType.BLACK:
                lines.append(f'{num}. {white} {hist[i + 1].san}')
                i += 2
            else:
                lines.append(f'{num}. {white}')
                i += 1
        return lines

    # -- Сериализация позиции и партии --

    _FEN_PIECE = {
        (SideType.WHITE, PieceType.KING): 'K', (SideType.WHITE, PieceType.QUEEN): 'Q',
        (SideType.WHITE, PieceType.ROOK): 'R', (SideType.WHITE, PieceType.BISHOP): 'B',
        (SideType.WHITE, PieceType.KNIGHT): 'N', (SideType.WHITE, PieceType.PAWN): 'P',
        (SideType.BLACK, PieceType.KING): 'k', (SideType.BLACK, PieceType.QUEEN): 'q',
        (SideType.BLACK, PieceType.ROOK): 'r', (SideType.BLACK, PieceType.BISHOP): 'b',
        (SideType.BLACK, PieceType.KNIGHT): 'n', (SideType.BLACK, PieceType.PAWN): 'p',
    }

    def fen(self) -> str:
        '''FEN текущей позиции: расстановка, сторона, рокировка, en passant,
        полуходовый счётчик, номер хода.'''
        rows = []
        for y in range(self.__field.y_size):          # с 8-й горизонтали (y=0)
            row = ''
            empty = 0
            for x in range(self.__field.x_size):
                piece = self.__field.at(x, y)
                if piece.is_empty:
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += self._FEN_PIECE[(piece.color, piece.type)]
            if empty:
                row += str(empty)
            rows.append(row)
        placement = '/'.join(rows)
        side = 'w' if self.__side_to_move == SideType.WHITE else 'b'
        cr = ''
        if self.__rights.wk: cr += 'K'
        if self.__rights.wq: cr += 'Q'
        if self.__rights.bk: cr += 'k'
        if self.__rights.bq: cr += 'q'
        if not cr:
            cr = '-'
        ep = square_name(self.__ep.x, self.__ep.y) if self.__ep else '-'
        return f'{placement} {side} {cr} {ep} {self.__halfmove} {self.__fullmove}'

    def result_pgn(self) -> str:
        '''Результат партии в нотации PGN: «1-0», «0-1», «1/2-1/2» или «*».'''
        st = self.__status
        if st == 'checkmate':
            return '1-0' if SideType.opposite(self.__side_to_move) == SideType.WHITE else '0-1'
        if st in DRAWS:
            return '1/2-1/2'
        return '*'

    def pgn(self) -> str:
        '''Партия в формате PGN: заголовки + текст ходов + результат.'''
        white_name = 'Игрок' if self.__player_side == SideType.WHITE else f'ИИ ({self.__difficulty.name_ru})'
        black_name = 'Игрок' if self.__player_side == SideType.BLACK else f'ИИ ({self.__difficulty.name_ru})'
        from datetime import date
        headers = [
            '[Event "Шахматы (Python)"]',
            '[Site "?"]',
            f'[Date "{date.today().strftime("%Y.%m.%d")}"]',
            f'[White "{white_name}"]',
            f'[Black "{black_name}"]',
            f'[Result "{self.result_pgn()}"]',
        ]
        if self.__start_fen and self.__start_fen != _STANDARD_FEN:
            headers.append('[SetUp "1"]')
            headers.append(f'[FEN "{self.__start_fen}"]')
        # Текст ходов: «1. e4 e5 2. Nf3 ...» с переносами для читаемости
        movetext = '  '.join(self.move_list_text())
        if not movetext:
            movetext = ''
        result = self.result_pgn()
        body = movetext + (' ' + result if movetext else result)
        return '\n'.join(headers) + '\n\n' + body + '\n'
