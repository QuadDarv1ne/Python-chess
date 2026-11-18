from chess_game.enums import PieceType, SideType


class Piece:
    '''Фигура. __slots__ ради памяти и скорости: объект создаётся на каждой клетке.

    В отличие от checkers.checker.Checker, где цвет и «дамка» зашиты в один
    CheckerType, здесь тип и цвет разделены: 6 типов фигур × 2 цвета.
    Пустая клетка — это Piece(PieceType.NONE), цвет в этом случае неважен.
    '''

    __slots__ = ('__type', '__color')

    def __init__(self, type: PieceType = PieceType.NONE, color: SideType = SideType.WHITE):
        self.__type = type
        self.__color = color

    @property
    def type(self):
        return self.__type

    @property
    def color(self):
        return self.__color

    def change_type(self, type: PieceType):
        '''Изменение типа фигуры'''
        self.__type = type

    def set(self, type: PieceType, color: SideType):
        '''Полная замена фигуры (тип + цвет)'''
        self.__type = type
        self.__color = color

    def clear(self):
        '''Очистка клетки'''
        self.__type = PieceType.NONE
        self.__color = SideType.WHITE

    @property
    def is_empty(self):
        return self.__type == PieceType.NONE

    def __repr__(self):
        if self.is_empty:
            return 'Piece(empty)'
        return f'Piece({self.__color.name_ru} {self.__type.name_ru})'
