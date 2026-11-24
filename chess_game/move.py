from chess_game.enums import PieceType


class Move:
    '''Ход фигуры.

    Базовые координаты как в checkers.move.Move, плюс шахматные флаги:
    превращение пешки, рокировка (со стороной), взятие на проходе и двойной
    шаг пешки (он нужен, чтобы знать, какую клетку открыли для en passant).
    '''

    __slots__ = (
        '__from_x', '__from_y', '__to_x', '__to_y',
        '__promotion', '__is_castle', '__castle_side',
        '__is_en_passant', '__is_double_pawn',
    )

    def __init__(self, from_x: int = -1, from_y: int = -1, to_x: int = -1, to_y: int = -1,
                 promotion: PieceType = PieceType.NONE, is_castle: bool = False,
                 castle_side: str = None, is_en_passant: bool = False,
                 is_double_pawn: bool = False):
        self.__from_x = from_x
        self.__from_y = from_y
        self.__to_x = to_x
        self.__to_y = to_y
        self.__promotion = promotion
        self.__is_castle = is_castle
        self.__castle_side = castle_side
        self.__is_en_passant = is_en_passant
        self.__is_double_pawn = is_double_pawn

    # -- Конструкторы удобства --

    @classmethod
    def normal(cls, from_x, from_y, to_x, to_y):
        return cls(from_x, from_y, to_x, to_y)

    @classmethod
    def double_pawn(cls, from_x, from_y, to_x, to_y):
        return cls(from_x, from_y, to_x, to_y, is_double_pawn=True)

    @classmethod
    def en_passant(cls, from_x, from_y, to_x, to_y):
        return cls(from_x, from_y, to_x, to_y, is_en_passant=True)

    @classmethod
    def castle(cls, from_x, from_y, to_x, to_y, side):
        # side: 'K' — короткая (в сторону королевского фланга), 'Q' — длинная
        return cls(from_x, from_y, to_x, to_y, is_castle=True, castle_side=side)

    @classmethod
    def promoting(cls, from_x, from_y, to_x, to_y, piece: PieceType):
        '''Ход с превращением пешки. Имя отличается от свойства `promotion`,
        чтобы класс-метод и свойство не перекрывали друг друга.'''
        return cls(from_x, from_y, to_x, to_y, promotion=piece)

    # -- Свойства --

    @property
    def from_x(self):
        return self.__from_x

    @property
    def from_y(self):
        return self.__from_y

    @property
    def to_x(self):
        return self.__to_x

    @property
    def to_y(self):
        return self.__to_y

    @property
    def promotion(self):
        return self.__promotion

    @property
    def is_castle(self):
        return self.__is_castle

    @property
    def castle_side(self):
        return self.__castle_side

    @property
    def is_en_passant(self):
        return self.__is_en_passant

    @property
    def is_double_pawn(self):
        return self.__is_double_pawn

    @property
    def is_promotion(self):
        return self.__promotion != PieceType.NONE

    def __eq__(self, other):
        if isinstance(other, Move):
            return (
                self.from_x == other.from_x and self.from_y == other.from_y and
                self.to_x == other.to_x and self.to_y == other.to_y and
                self.promotion == other.promotion and
                self.is_castle == other.is_castle and
                self.castle_side == other.castle_side and
                self.is_en_passant == other.is_en_passant and
                self.is_double_pawn == other.is_double_pawn
            )
        return NotImplemented

    def __hash__(self):
        return hash((
            self.from_x, self.from_y, self.to_x, self.to_y,
            self.promotion, self.is_castle, self.castle_side,
            self.is_en_passant, self.is_double_pawn,
        ))

    def __ne__(self, other):
        if isinstance(other, Move):
            return not self.__eq__(other)
        return NotImplemented

    def __repr__(self):
        if self.is_castle:
            side = 'O-O' if self.castle_side == 'K' else 'O-O-O'
            return f'Move({side})'
        promo = f'={self.promotion.letter or "?"}' if self.is_promotion else ''
        flags = []
        if self.is_en_passant:
            flags.append('e.p.')
        extra = f' [{",".join(flags)}]' if flags else ''
        return f'Move({self.from_x},{self.from_y}->{self.to_x},{self.to_y}{promo}{extra})'
