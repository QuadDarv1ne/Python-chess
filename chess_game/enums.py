"""Перечисления: сторона, тип фигуры, уровень сложности.

SideType и DifficultyType намеренно повторяют API из проекта Python-checkers,
чтобы движок и UI выглядели и вели себя привычно для того, кто знает оригинал.
"""
from enum import Enum, auto


class SideType(Enum):
    WHITE = auto()
    BLACK = auto()

    @staticmethod
    def opposite(side):
        if side == SideType.WHITE:
            return SideType.BLACK
        elif side == SideType.BLACK:
            return SideType.WHITE
        else:
            raise ValueError(f'Неизвестная сторона: {side!r}')

    @property
    def name_ru(self):
        return 'Белые' if self == SideType.WHITE else 'Чёрные'


class PieceType(Enum):
    NONE = auto()
    PAWN = auto()
    KNIGHT = auto()
    BISHOP = auto()
    ROOK = auto()
    QUEEN = auto()
    KING = auto()

    @property
    def name_ru(self):
        return {
            PieceType.NONE: 'Пусто',
            PieceType.PAWN: 'Пешка',
            PieceType.KNIGHT: 'Конь',
            PieceType.BISHOP: 'Слон',
            PieceType.ROOK: 'Ладья',
            PieceType.QUEEN: 'Ферзь',
            PieceType.KING: 'Король',
        }[self]

    @property
    def letter(self):
        '''Буква фигуры в нотации (для пешки — пустая, как в SAN).'''
        return {
            PieceType.KNIGHT: 'N',
            PieceType.BISHOP: 'B',
            PieceType.ROOK: 'R',
            PieceType.QUEEN: 'Q',
            PieceType.KING: 'K',
            PieceType.PAWN: '',
            PieceType.NONE: '',
        }[self]


class DifficultyType(Enum):
    EASY = auto()
    MEDIUM = auto()
    HARD = auto()
    GRANDMASTER = auto()

    @property
    def depth(self):
        '''Максимальная глубина просчёта для уровня'''
        return {
            DifficultyType.EASY: 2,
            DifficultyType.MEDIUM: 3,
            DifficultyType.HARD: 5,
            DifficultyType.GRANDMASTER: 7,
        }[self]

    @property
    def time_limit(self):
        '''Лимит времени на ход в секундах (итеративное углубление)'''
        return {
            DifficultyType.EASY: 0.5,
            DifficultyType.MEDIUM: 2.0,
            DifficultyType.HARD: 5.0,
            DifficultyType.GRANDMASTER: 10.0,
        }[self]

    @property
    def noise_scale(self):
        '''Гауссов шум к оценке хода: чем больше, тем сильнее ИИ "ошибается".

        Единицы — пешки (≈100 в сотых), поэтому 30 на лёгком уровне регулярно
        допускает чуть худшие ходы, а 0 на гроссмейстере делает игру
        детерминированно сильной.
        '''
        return {
            DifficultyType.EASY: 30.0,
            DifficultyType.MEDIUM: 10.0,
            DifficultyType.HARD: 2.0,
            DifficultyType.GRANDMASTER: 0.0,
        }[self]

    @property
    def name_ru(self):
        return {
            DifficultyType.EASY: "Лёгкий",
            DifficultyType.MEDIUM: "Средний",
            DifficultyType.HARD: "Сложный",
            DifficultyType.GRANDMASTER: "Гроссмейстер",
        }[self]
