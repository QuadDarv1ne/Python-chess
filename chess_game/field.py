from chess_game.enums import PieceType, SideType
from chess_game.piece import Piece
from chess_game.constants import BOARD_SIZE, PIECE_VALUES


# Задний ряд фигур слева направо (a..h): ладья, конь, слон, ферзь, король, ...
BACK_RANK = [
    PieceType.ROOK, PieceType.KNIGHT, PieceType.BISHOP, PieceType.QUEEN,
    PieceType.KING, PieceType.BISHOP, PieceType.KNIGHT, PieceType.ROOK,
]


class Field:
    '''Доска 8×8 из объектов Piece.

    Координаты: x = 0..7 — файлы a..h, y = 0..7 — горизонтали 8..1
    (то есть y=0 — это 8-я горизонталь, чёрный задний ряд; y=7 — 1-я, белый).
    Белые фигуры идут снизу вверх (увеличение y), как и пешки вперёд.
    '''

    def __init__(self, x_size: int = BOARD_SIZE, y_size: int = BOARD_SIZE):
        self.__x_size = x_size
        self.__y_size = y_size
        self.__generate()

    @property
    def x_size(self) -> int:
        return self.__x_size

    @property
    def y_size(self) -> int:
        return self.__y_size

    @property
    def size(self) -> int:
        return max(self.x_size, self.y_size)

    @classmethod
    def copy(cls, field_instance):
        '''Независимая копия поля.

        Копируем тип+цвет напрямую, минуя __generate: иначе доска строится
        заново на каждой ветке поиска — слишком дорого для минимакса.
        '''
        field_copy = cls.__new__(cls)
        field_copy._Field__x_size = field_instance.x_size
        field_copy._Field__y_size = field_instance.y_size
        grid = []
        for y in range(field_instance.y_size):
            row = []
            for x in range(field_instance.x_size):
                src = field_instance.at(x, y)
                row.append(Piece(src.type, src.color))
            grid.append(row)
        field_copy._Field__grid = grid
        return field_copy

    @classmethod
    def empty(cls, x_size: int = BOARD_SIZE, y_size: int = BOARD_SIZE):
        '''Пустая доска — для расстановки произвольных позиций в тестах'''
        field_copy = cls.__new__(cls)
        field_copy._Field__x_size = x_size
        field_copy._Field__y_size = y_size
        field_copy._Field__grid = [[Piece() for _ in range(x_size)] for _ in range(y_size)]
        return field_copy

    def __generate(self):
        '''Стандартная расстановка шахматной партии'''
        self.__grid = [[Piece() for _ in range(self.x_size)] for _ in range(self.y_size)]

        # Чёрные: верхние две горизонтали
        for x, piece_type in enumerate(BACK_RANK):
            self.__grid[0][x].set(piece_type, SideType.BLACK)
        for x in range(self.x_size):
            self.__grid[1][x].set(PieceType.PAWN, SideType.BLACK)

        # Белые: нижние две горизонтали
        for x in range(self.x_size):
            self.__grid[self.y_size - 2][x].set(PieceType.PAWN, SideType.WHITE)
        for x, piece_type in enumerate(BACK_RANK):
            self.__grid[self.y_size - 1][x].set(piece_type, SideType.WHITE)

    def type_at(self, x: int, y: int) -> PieceType:
        '''Тип фигуры на клетке'''
        return self.__grid[y][x].type

    def color_at(self, x: int, y: int) -> SideType:
        '''Цвет фигуры на клетке (имеет смысл только если клетка не пуста)'''
        return self.__grid[y][x].color

    def at(self, x: int, y: int) -> Piece:
        '''Объект Piece на клетке (возможно пустой)'''
        return self.__grid[y][x]

    def set_piece(self, x: int, y: int, type: PieceType, color: SideType):
        '''Поставить фигуру на клетку'''
        self.__grid[y][x].set(type, color)

    def clear_at(self, x: int, y: int):
        '''Очистить клетку'''
        self.__grid[y][x].clear()

    def is_within(self, x: int, y: int) -> bool:
        '''Лежит ли точка в пределах поля'''
        return 0 <= x < self.x_size and 0 <= y < self.y_size

    def pieces(self, side: SideType = None):
        '''Итератор по (x, y, piece) для фигур указанной стороны (или всех)'''
        for y in range(self.y_size):
            for x in range(self.x_size):
                piece = self.__grid[y][x]
                if piece.is_empty:
                    continue
                if side is None or piece.color == side:
                    yield x, y, piece

    def king_position(self, side: SideType):
        '''Координаты короля стороны (x, y) или None'''
        for y in range(self.y_size):
            for x in range(self.x_size):
                piece = self.__grid[y][x]
                if piece.type == PieceType.KING and piece.color == side:
                    return (x, y)
        return None

    def material(self, side: SideType) -> int:
        '''Суммарная стоимость фигур стороны (без короля, в сотых пешки)'''
        total = 0
        for _, _, piece in self.pieces(side):
            if piece.type in (PieceType.NONE, PieceType.KING):
                continue
            total += PIECE_VALUES[piece.type]
        return total

    def piece_count(self, side: SideType) -> int:
        '''Количество фигур стороны (включая короля и пешки)'''
        return sum(1 for _, _, p in self.pieces(side))

    def get_score(self, side: SideType) -> int:
        '''Материал стороны (для совместимости с checkers.Field.get_score)'''
        return self.material(side)
