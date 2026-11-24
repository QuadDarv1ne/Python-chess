"""Пакет шахматной игры на основе структуры Python-checkers.

Модули повторяют роли из checkers/:
  enums     — SideType, PieceType, DifficultyType
  constants — размеры, цвета, стоимости фигур, направления
  point     — клетка доски
  move      — ход (с флагами рокировки / en passant / превращения)
  piece     — фигура (тип + цвет)
  field     — доска 8×8 и расстановка
  rules     — генерация ходов, атака клетки, шах/мат/пат, apply/undo
  engine    — поиск лучшего хода (negamax + alpha-beta + quiescence)
  game      — состояние партии, история, статус, нотация
  audio     — синтез эффектов и фоновой фортепианной музыки
"""

__all__ = [
    'enums', 'constants', 'point', 'move', 'piece',
    'field', 'rules', 'engine', 'game', 'audio',
]
