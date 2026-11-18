"""Константы шахматной партии.

Перекрывает checkers/constants.py: размеры поля те же (8×8), цвета доски
оставлены близкими к оригиналу, но добавлены подсветка последнего хода,
подсветка короля под шахом и стоимость фигур.
"""
from chess_game.enums import PieceType, SideType, DifficultyType
from chess_game.point import Point

# Сторона игрока по умолчанию
PLAYER_SIDE = SideType.WHITE

# Уровень сложности по умолчанию
DEFAULT_DIFFICULTY = DifficultyType.MEDIUM

# Размер поля
BOARD_SIZE = 8
X_SIZE = Y_SIZE = BOARD_SIZE

# Размер ячейки (в пикселях)
CELL_SIZE = 72

# Скорость анимации перемещения фигуры (больше = быстрее)
ANIMATION_SPEED = 6

# Максимальное количество ходов в истории (для отмены)
MAX_HISTORY = 200

# Ширина рамки вокруг доски
BORDER_WIDTH = 4

# Цвета игровой доски (светлая / тёмная клетка)
FIELD_COLORS = ['#E7CFA9', '#927456']

# Подсветка наведения и выделения клетки
HOVER_BORDER_COLOR = '#54b346'
SELECT_BORDER_COLOR = '#944444'

# Подсветка последнего хода
LAST_MOVE_COLOR = '#d9b34a'

# Подсветка короля, стоящего под шахом
CHECK_COLOR = '#c83232'

# Точки возможных ходов: кольцо для тихого хода, диск для хода со взятием
LEGAL_MOVE_COLOR = '#3a6ea5'
LEGAL_CAPTURE_COLOR = '#b23b3b'

# Стоимость фигур в сотых пешки (как в шахматных движках: пешка = 100)
PIECE_VALUES = {
    PieceType.NONE: 0,
    PieceType.PAWN: 100,
    PieceType.KNIGHT: 320,
    PieceType.BISHOP: 330,
    PieceType.ROOK: 500,
    PieceType.QUEEN: 900,
    PieceType.KING: 20000,
}

# Уровни сложности как список (для меню)
DIFFICULTY_ORDER = [
    DifficultyType.EASY,
    DifficultyType.MEDIUM,
    DifficultyType.HARD,
    DifficultyType.GRANDMASTER,
]

# Направления хода скользящих фигур (лучи): [(dx, dy), ...]
BISHOP_DIRS = [Point(-1, -1), Point(1, -1), Point(-1, 1), Point(1, 1)]
ROOK_DIRS = [Point(-1, 0), Point(1, 0), Point(0, -1), Point(0, 1)]
QUEEN_DIRS = BISHOP_DIRS + ROOK_DIRS

# Ходы коня: все 8 «Г»-образных смещений
KNIGHT_OFFSETS = [
    Point(-2, -1), Point(-2, 1), Point(2, -1), Point(2, 1),
    Point(-1, -2), Point(1, -2), Point(-1, 2), Point(1, 2),
]

# Ходы короля: 8 соседних клеток
KING_OFFSETS = [
    Point(-1, -1), Point(0, -1), Point(1, -1),
    Point(-1, 0),            Point(1, 0),
    Point(-1, 1),  Point(0, 1),  Point(1, 1),
]

# Юникод-глифы фигур. Белые — контурные, чёрные — залитые; так различимы
# даже на тёмной клетке и не требуют раскрашивания глифа.
PIECE_GLYPHS = {
    (SideType.WHITE, PieceType.KING):   '\u2654',
    (SideType.WHITE, PieceType.QUEEN):  '\u2655',
    (SideType.WHITE, PieceType.ROOK):   '\u2656',
    (SideType.WHITE, PieceType.BISHOP): '\u2657',
    (SideType.WHITE, PieceType.KNIGHT): '\u2658',
    (SideType.WHITE, PieceType.PAWN):   '\u2659',
    (SideType.BLACK, PieceType.KING):   '\u265a',
    (SideType.BLACK, PieceType.QUEEN):  '\u265b',
    (SideType.BLACK, PieceType.ROOK):   '\u265c',
    (SideType.BLACK, PieceType.BISHOP): '\u265d',
    (SideType.BLACK, PieceType.KNIGHT): '\u265e',
    (SideType.BLACK, PieceType.PAWN):   '\u265f',
}
