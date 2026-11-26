"""Дымовой тест game.py: ходы, статус, история, отмены, ничьи, нотация SAN."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Консоль Windows по умолчанию в cp1251 — переключаем вывод в UTF-8, иначе
# юникодные символы (→, ≈, кириллица) роняют тест с UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8')

from chess_game.enums import PieceType, SideType, DifficultyType
from chess_game.field import Field
from chess_game.move import Move
from chess_game.point import Point
from chess_game import rules as R
from chess_game.game import Game, square_name


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


def fools_mate_moves():
    return [
        Move.normal(5, 6, 5, 5),            # 1. f3
        Move.double_pawn(4, 1, 4, 3),       # 1... e5
        Move.double_pawn(6, 6, 6, 4),       # 2. g4
        Move.normal(3, 0, 7, 4),            # 2... Qh4#
    ]


def test_fools_mate_via_game():
    print('Тест: мат дурака через Game')
    g = Game(player_side=SideType.WHITE, difficulty=DifficultyType.EASY)
    for mv in fools_mate_moves():
        ok = g.make_move(mv)
        assert ok, f'ход {mv} не применён'
    check('статус = checkmate', g.status == 'checkmate', g.status)
    check('is_game_over', g.is_game_over)
    check('SAN последнего хода содержит #', g.history[-1].san.endswith('#'),
          g.history[-1].san)
    check('SAN Qh4#', g.history[-1].san == 'Qh4#', g.history[-1].san)
    check('итог: победа чёрных', 'чёрн' in g.result_ru().lower(), g.result_ru())
    # Панель истории: первая строка «1. f3 e5»
    lines = g.move_list_text()
    check('первая строка истории', lines and lines[0].startswith('1. f3 e5'),
          lines[0] if lines else 'пусто')


def test_undo_to_start():
    print('Тест: отмена ходов до стартовой позиции')
    g = Game()
    for mv in fools_mate_moves():
        g.make_move(mv)
    for _ in range(len(fools_mate_moves())):
        g.undo()
    check('история пуста', len(g.history) == 0)
    check('ход белых', g.side_to_move == SideType.WHITE)
    check('статус normal', g.status == 'normal')
    check('fullmove = 1', g.fullmove_number == 1)
    check('halfmove = 0', g.halfmove_clock == 0)


def test_insufficient_material():
    print('Тест: недостаточный материал — ничья')
    field = Field.empty()
    field.set_piece(4, 7, PieceType.KING, SideType.WHITE)   # e1
    field.set_piece(4, 0, PieceType.KING, SideType.BLACK)   # e8
    g = Game.from_position(field, side=SideType.WHITE)
    check('голые короли → draw_insufficient', g.status == 'draw_insufficient', g.status)

    # K + слон vs K — тоже ничья
    field.set_piece(2, 4, PieceType.BISHOP, SideType.WHITE)
    g2 = Game.from_position(field, side=SideType.WHITE)
    check('K+B vs K → draw_insufficient', g2.status == 'draw_insufficient', g2.status)

    # Добавим пешку — мата достаточно, игра идёт
    field.set_piece(4, 6, PieceType.PAWN, SideType.WHITE)
    g3 = Game.from_position(field, side=SideType.WHITE)
    check('есть пешка → normal', g3.status == 'normal', g3.status)


def test_50_move_rule():
    print('Тест: правило 50 ходов')
    field = Field.empty()
    field.set_piece(4, 7, PieceType.KING, SideType.WHITE)
    field.set_piece(4, 0, PieceType.KING, SideType.BLACK)
    field.set_piece(0, 7, PieceType.ROOK, SideType.WHITE)   # ладья, чтобы мата «хватило»
    g = Game.from_position(field, side=SideType.WHITE, halfmove=100)
    check('halfmove=100 → draw_50', g.status == 'draw_50', g.status)

    g2 = Game.from_position(field, side=SideType.WHITE, halfmove=99)
    check('halfmove=99 → normal', g2.status == 'normal', g2.status)


def test_threefold_repetition():
    print('Тест: троекратное повторение (перетасовка коней)')
    g = Game()
    seq = [
        Move.normal(6, 7, 5, 5),   # Nf3
        Move.normal(6, 0, 5, 2),   # Nf6
        Move.normal(5, 5, 6, 7),   # Ng1
        Move.normal(5, 2, 6, 0),   # Ng8
        Move.normal(6, 7, 5, 5),   # Nf3
        Move.normal(6, 0, 5, 2),   # Nf6
        Move.normal(5, 5, 6, 7),   # Ng1
        Move.normal(5, 2, 6, 0),   # Ng8  → позиция старта 3-й раз
    ]
    for mv in seq:
        ok = g.make_move(mv)
        assert ok, f'ход {mv} не применён'
    check('после возврата коней ×3 → draw_repetition',
          g.status == 'draw_repetition', g.status)


def test_repetition_irrelevant_ep():
    print('Тест: троекратное повторение с неактуальной клеткой en passant')
    # FIDE ст. 9.2: две позиции равны для повторения, даже если клетка ep задана,
    # но ни одна пешка не может ею воспользоваться. Здесь первое повторение
    # стартовой расстановки возникает СРАЗУ после ...e7-e5 (ep=e6 задано, но у
    # белых нет пешек на d5/f5 → неактуально). Без учёта этого правила ключи
    # первого и второго повторений различались бы и ничья не фиксировалась.
    field = Field.empty()
    field.set_piece(0, 7, PieceType.KING, SideType.WHITE)
    field.set_piece(2, 5, PieceType.KNIGHT, SideType.WHITE)   # c3
    field.set_piece(7, 0, PieceType.KING, SideType.BLACK)
    field.set_piece(4, 1, PieceType.PAWN, SideType.BLACK)     # e7
    rights = R.CastlingRights(wk=False, wq=False, bk=False, bq=False)
    g = Game.from_position(field, SideType.BLACK, rights)
    seq = [
        Move.double_pawn(4, 1, 4, 3),   # ...e5   → S1: белый ход, ep=e6 неактуально
        Move.normal(2, 5, 1, 7),        # Nc3-b1
        Move.normal(7, 0, 7, 1),        # Kh8-h7
        Move.normal(1, 7, 2, 5),        # Nb1-c3  → S4: белый ход, ep=None
        Move.normal(7, 1, 7, 0),        # Kh7-h8
        Move.normal(2, 5, 1, 7),        # Nc3-b1
        Move.normal(7, 0, 7, 1),        # Kh8-h7
        Move.normal(1, 7, 2, 5),        # Nb1-c3  → S7: белый ход, ep=None
        Move.normal(7, 1, 7, 0),        # Kh7-h8
    ]
    for mv in seq:
        ok = g.make_move(mv)
        assert ok, f'ход {mv} не применён'
        if g.is_game_over:
            break
    check('неактуальная ep не мешает зафиксировать троекратное повторение',
          g.status == 'draw_repetition', g.status)

    # Пешка e5 геометрически бьёт d6, но связана ладьёй e8 с королём e1.
    # Такое взятие нелегально, поэтому клетка ep не входит в ключ позиции.
    pinned = Field.empty()
    pinned.set_piece(4, 7, PieceType.KING, SideType.WHITE)    # e1
    pinned.set_piece(4, 3, PieceType.PAWN, SideType.WHITE)    # e5
    pinned.set_piece(3, 3, PieceType.PAWN, SideType.BLACK)    # d5
    pinned.set_piece(4, 0, PieceType.ROOK, SideType.BLACK)    # e8
    pinned.set_piece(6, 0, PieceType.KING, SideType.BLACK)    # g8
    ep_sq = Point(3, 2)   # d6
    no_rights = R.CastlingRights(False, False, False, False)
    key_ep = R.position_key(pinned, SideType.WHITE, no_rights, ep_sq)
    key_no = R.position_key(pinned, SideType.WHITE, no_rights, None)
    check('связанная пешка не делает ep частью ключа', key_ep == key_no)

    free = Field.empty()
    free.set_piece(4, 7, PieceType.KING, SideType.WHITE)
    free.set_piece(4, 3, PieceType.PAWN, SideType.WHITE)
    free.set_piece(3, 3, PieceType.PAWN, SideType.BLACK)
    free.set_piece(6, 0, PieceType.KING, SideType.BLACK)
    key_free = R.position_key(free, SideType.WHITE, no_rights, ep_sq)
    key_free_no = R.position_key(free, SideType.WHITE, no_rights, None)
    check('легальный ep входит в ключ позиции', key_free != key_free_no)


def test_san_disambiguation():
    print('Тест: SAN-разыменование (Rad1 vs Rhd1)')
    field = Field.empty()
    field.set_piece(4, 4, PieceType.KING, SideType.WHITE)   # белый король e4 (не мешает)
    field.set_piece(0, 7, PieceType.ROOK, SideType.WHITE)   # ладья a1
    field.set_piece(7, 7, PieceType.ROOK, SideType.WHITE)   # ладья h1
    field.set_piece(4, 0, PieceType.KING, SideType.BLACK)   # чёрный король e8
    g = Game.from_position(field, side=SideType.WHITE,
                           rights=R.CastlingRights(wk=False, wq=False, bk=False, bq=False))
    # Обе ладьи могут встать на d1
    rad1 = Move.normal(0, 7, 3, 7)
    rhd1 = Move.normal(7, 7, 3, 7)
    check('Rad1 легален', rad1 in g.legal_moves())
    check('Rhd1 легален', rhd1 in g.legal_moves())
    check('SAN a1→d1 = Rad1', g.to_san(rad1) == 'Rad1', g.to_san(rad1))
    check('SAN h1→d1 = Rhd1', g.to_san(rhd1) == 'Rhd1', g.to_san(rhd1))


def test_fen_pgn():
    print('Тест: FEN и PGN')
    g = Game()
    check('FEN стартовой позиции',
          g.fen() == 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', g.fen())

    # 1.e4: открывается e3 для en passant, сторона чёрных, счётчик 0
    g.make_move(Move.double_pawn(4, 6, 4, 4))
    check('FEN после 1.e4',
          g.fen() == 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1', g.fen())

    # 1...c5: ep-цель c6 (чёрная пешка прошла двойным), ход белых, fullmove 2
    g.make_move(Move.double_pawn(2, 1, 2, 3))
    check('FEN после 1.e4 c5',
          g.fen() == 'rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2', g.fen())

    # PGN содержит ходы и результат '*' (партия не окончена)
    pgn = g.pgn()
    check('PGN содержит 1. e4', '1. e4 c5' in pgn, pgn)
    check('PGN результат *', '[Result "*"]' in pgn and pgn.rstrip().endswith('*'), pgn)

    # Рокировка снимает права: белая короткая — теряем только K
    g2 = Game()
    # Расчистим f1/g1 и подведём ладью/короля к рокировке через прямой ход
    # проще — сразу из позиции с пустыми f1,g1 и правом O-O
    field = Field.empty()
    field.set_piece(4, 7, PieceType.KING, SideType.WHITE)
    field.set_piece(7, 7, PieceType.ROOK, SideType.WHITE)
    field.set_piece(4, 0, PieceType.KING, SideType.BLACK)
    g3 = Game.from_position(field, side=SideType.WHITE,
                            rights=R.CastlingRights(wk=True, wq=False, bk=False, bq=False))
    check('FEN прав до рокировки: только K', g3.fen().split(' ')[2] == 'K', g3.fen())
    castle = Move.castle(4, 7, 6, 7, 'K')
    assert g3.make_move(castle)
    check('FEN после O-O: прав нет (-)', g3.fen().split(' ')[2] == '-', g3.fen())
    check('PGN после O-O содержит O-O', 'O-O' in g3.pgn())


def test_from_fen():
    print('Тест: загрузка позиции из FEN')
    start = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    g = Game.from_fen(start)
    check('from_fen стартовой: round-trip', g.fen() == start, g.fen())
    check('from_fen стартовой: сторона белых', g.side_to_move == SideType.WHITE)
    check('from_fen стартовой: 20 легальных ходов', len(g.legal_moves()) == 20)

    # Kiwipete: round-trip + 48 легальных ходов (канон)
    kiwi = 'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1'
    gk = Game.from_fen(kiwi)
    check('from_fen Kiwipete: round-trip', gk.fen() == kiwi, gk.fen())
    check('from_fen Kiwipete: 48 ходов', len(gk.legal_moves()) == 48, len(gk.legal_moves()))

    # en passant-цель читается
    after_e4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'
    ge = Game.from_fen(after_e4)
    check('from_fen: ep-цель e3 читается', ge.en_passant_target is not None
          and square_name(ge.en_passant_target.x, ge.en_passant_target.y) == 'e3', ge.fen())

    # Статус вычисляется: детский мат (белые заматованы)
    fool = 'rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3'
    gf = Game.from_fen(fool)
    check('from_fen: статус матовой позиции = checkmate', gf.status == 'checkmate', gf.status)

    # Неверный FEN вызывает ValueError
    raised = False
    try:
        Game.from_fen('not a fen')
    except ValueError:
        raised = True
    check('from_fen: неверный FEN → ValueError', raised)

    # Пешка на крайней горизонтали — невозможна (только превращение)
    raised = False
    try:
        Game.from_fen('P3k3/8/8/8/8/8/8/4K3 w - - 0 1')
    except ValueError:
        raised = True
    check('from_fen: пешка на a8 → ValueError', raised)

    # Сторона без хода под шахом — нелегальная позиция
    raised = False
    try:
        # белый ферзь e5 шахует чёрного короля e8, но ход белых
        Game.from_fen('4k3/8/8/4Q3/8/8/8/4K3 w - - 0 1')
    except ValueError:
        raised = True
    check('from_fen: сторона без хода под шахом → ValueError', raised)

    raised = False
    try:
        Game.from_fen('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBN w KQkq - 0 1')
    except ValueError:
        raised = True
    check('from_fen: короткая горизонталь → ValueError', raised)

    raised = False
    try:
        Game.from_fen('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq e3 0 1')
    except ValueError:
        raised = True
    check('from_fen: en passant без пешки двойного хода → ValueError', raised)

    raised = False
    try:
        Game.from_fen('4k3/8/8/8/8/8/8/4K3 w K - 0 1')
    except ValueError:
        raised = True
    check('from_fen: рокировка K без ладьи → ValueError', raised)

    raised = False
    try:
        Game.from_fen('4k3/8/8/8/8/8/8/4K3 w - - -1 1')
    except ValueError:
        raised = True
    check('from_fen: отрицательный счётчик полуходов → ValueError', raised)

    raised = False
    try:
        Game.from_fen('4k3/8/8/8/8/8/8/4K3 w - - 0 0')
    except ValueError:
        raised = True
    check('from_fen: номер хода 0 → ValueError', raised)

    promo = Game.from_fen('k7/4P3/8/8/8/8/8/4K3 w - - 0 1')
    q1 = promo.from_san('e8Q')
    q2 = promo.from_san('e8=Q')
    check('from_san: e8Q без знака =', q1.is_promotion and q1.promotion == PieceType.QUEEN)
    check('from_san: e8Q совпадает с e8=Q', q1 == q2)

    bare = Field.empty()
    bare.set_piece(7, 7, PieceType.ROOK, SideType.WHITE)
    bare.set_piece(3, 7, PieceType.KING, SideType.WHITE)
    bare.set_piece(4, 0, PieceType.KING, SideType.BLACK)
    castles = [m for m in R.pseudo_legal_moves(bare, SideType.WHITE, R.CastlingRights())
               if m.is_castle]
    check('рокировка без короля на e1 не генерируется', castles == [])


def test_from_pgn():
    print('Тест: загрузка партии из PGN (from_san / from_pgn)')
    # 1. Round-trip: сыграем координатами, экспорт PGN, импорт, сравним FEN и SAN
    g = Game()
    seq = ['e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1b5', 'a7a6', 'b5a4', 'g8f6', 'e1g1']
    for uci in seq:
        fx, fy = ord(uci[0]) - 97, 8 - int(uci[1])
        tx, ty = ord(uci[2]) - 97, 8 - int(uci[3])
        cand = [m for m in g.legal_moves()
                if m.from_x == fx and m.from_y == fy and m.to_x == tx and m.to_y == ty]
        assert cand, uci
        g.make_move(cand[0])
    g2 = Game.from_pgn(g.pgn())
    check('from_pgn round-trip: FEN равны', g.fen() == g2.fen(), g2.fen())
    check('from_pgn round-trip: SAN равны',
          [h.san for h in g.history] == [h.san for h in g2.history],
          [h.san for h in g2.history])
    check('from_pgn: рокировка O-O в истории', 'O-O' in [h.san for h in g2.history])

    # 2. Детский мат по PGN → checkmate, последний SAN Qh4#
    fool = '[Event "x"]\n[White "A"]\n[Black "B"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1'
    gf = Game.from_pgn(fool)
    check('from_pgn: детский мат = checkmate', gf.status == 'checkmate', gf.status)
    check('from_pgn: последний SAN Qh4#', gf.history[-1].san == 'Qh4#', gf.history[-1].san)

    # 3. Комментарии, вложенный вариант, NAG, слитный номер хода
    pgn3 = '1. e4 {отлично} e5 2. Nf3 (2. Bc4 Nc6) Nc6 $1 3.Bb5 a6 1-0'
    g3 = Game.from_pgn(pgn3)
    check('from_pgn: комментарии/варианты/NAG игнорируются',
          [h.san for h in g3.history] == ['e4', 'e5', 'Nf3', 'Nc6', 'Bb5', 'a6'],
          [h.san for h in g3.history])

    # 4. from_san поштучно
    gs = Game()
    check('from_san: e4', gs.from_san('e4').to_x == 4 and gs.from_san('e4').to_y == 4)
    check('from_san: NAG «e4$1» не мешает разбору',
          gs.from_san('e4$1') == gs.from_san('e4'))
    gs.make_move(gs.from_san('e4'))
    gs.make_move(gs.from_san('e5'))
    check('from_san: Nf3 (рыцарский прыжок)', gs.from_san('Nf3').to_x == 5 and gs.from_san('Nf3').to_y == 5)

    amb = Game.from_fen('8/8/2N1N3/8/8/8/8/4K2k w - - 0 1')
    raised_amb = False
    try:
        amb.from_san('Nd4')
    except ValueError as e:
        raised_amb = 'неоднозначен' in str(e)
    check('from_san: неоднозначный Nd4 → ValueError', raised_amb)

    # 5. Нелегальный ход в PGN → ValueError с номером хода
    raised = False
    try:
        Game.from_pgn('1. e4 e5 2. Nxg8')
    except ValueError:
        raised = True
    check('from_pgn: нелегальный ход → ValueError', raised)

    # 6. Заголовок [FEN] — старт не со стандартной позиции
    pgn_fen = ('[FEN "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"]\n'
               '\n1... Nf6 2. Nc3')   # нечётный ход чёрных
    gfn = Game.from_pgn(pgn_fen)
    check('from_pgn: старт по [FEN]', gfn.history[0].san == 'Nf6', gfn.history[0].san)
    check('from_pgn: после [FEN] 2 полухода', len(gfn.history) == 2, len(gfn.history))
    check('история: первый ход чёрных — «3...», не ход белых',
          gfn.move_list_text() == ['3... Nf6', '4. Nc3'], gfn.move_list_text())
    exported = gfn.pgn()
    check('PGN нестандартного старта содержит [FEN]', '[FEN "' in exported, exported)
    gfn2 = Game.from_pgn(exported)
    check('PGN нестандартного старта: round-trip FEN', gfn2.fen() == gfn.fen(), gfn2.fen())

    pgn_semi = '1. e4 e5; учебник\n2. Nf3 Nc6 *'
    gsemi = Game.from_pgn(pgn_semi)
    check('from_pgn: комментарий «;» до конца строки игнорируется',
          [h.san for h in gsemi.history] == ['e4', 'e5', 'Nf3', 'Nc6'],
          [h.san for h in gsemi.history])

    two = '[Event "a"]\n\n1. e4 e5 1-0\n\n[Event "b"]\n\n1. d4 d5 *\n'
    gtwo = Game.from_pgn(two)
    check('from_pgn: из файла берётся только первая партия',
          [h.san for h in gtwo.history] == ['e4', 'e5'],
          [h.san for h in gtwo.history])

    raised_setup = False
    try:
        Game.from_pgn('[SetUp "1"]\n\n1. e4 *')
    except ValueError as e:
        raised_setup = 'FEN' in str(e)
    check('from_pgn: [SetUp "1"] без [FEN] → ValueError', raised_setup)

    from chess_game.game import decode_pgn_bytes
    raw = '1. e4 {привет} e5 *'.encode('cp1251')
    genc = Game.from_pgn(decode_pgn_bytes(raw))
    check('PGN в cp1251 читается',
          [h.san for h in genc.history] == ['e4', 'e5'],
          [h.san for h in genc.history])
    gbom = Game.from_pgn('\ufeff[Event "a"]\n\n1. e4 *')
    check('from_pgn: BOM в начале файла не ломает разбор',
          [h.san for h in gbom.history] == ['e4'],
          [h.san for h in gbom.history])

    drawn = Field.empty()
    drawn.set_piece(0, 7, PieceType.KING, SideType.WHITE)
    drawn.set_piece(7, 0, PieceType.KING, SideType.BLACK)
    gd = Game.from_position(drawn, halfmove=100,
                            rights=R.CastlingRights(False, False, False, False))
    quiet = Move.normal(0, 7, 0, 6)
    check('после ничьей по 50 ходам make_move не продолжает партию',
          gd.status == 'draw_50' and not gd.make_move(quiet) and len(gd.history) == 0,
          f'status={gd.status} history={len(gd.history)}')


def test_captured_pieces():
    print('Тест: captured_pieces — реальные взятия из истории')

    # Превращение пешки: пешка превращается, а не берётся — не должна в captured
    g = Game.from_fen('8/1P6/8/8/8/8/6k1/4K3 w - - 0 1')
    mv = next(m for m in g.legal_moves() if m.is_promotion)
    g.make_move(mv)  # b8=Q
    check('превращение пешки → нет взятий', len(g.captured_pieces()) == 0,
          g.captured_pieces())

    # Взятие: 1. e4 d5 2. exd5 — белая пешка бьёт чёрную
    g = Game()
    g.make_move(Move.double_pawn(4, 6, 4, 4))   # 1. e4
    g.make_move(Move.double_pawn(3, 1, 3, 3))   # 1... d5
    check('до взятия — 0', len(g.captured_pieces()) == 0, g.captured_pieces())
    g.make_move(Move.normal(4, 4, 3, 3))        # 2. exd5
    cp = g.captured_pieces()
    check('1 взятие: белые взяли чёрную пешку',
          cp == [(SideType.BLACK, PieceType.PAWN)], cp)

    # Отмена возвращает список взятий к прежнему состоянию
    g.undo()
    check('после отмены взятия — 0', len(g.captured_pieces()) == 0, g.captured_pieces())

    # Позиция из FEN без истории — взятий не показываем
    g2 = Game.from_fen('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
    check('позиция из FEN → нет взятий', len(g2.captured_pieces()) == 0)

    # Взятие на проходе: белая пешка d5 бьёт чёрную c5 (только что c7-c5)
    g4 = Game.from_fen('4k3/8/8/2pP4/8/8/8/4K3 w - c6 0 1')
    g4.make_move(Move.en_passant(3, 3, 2, 2))  # dxc6 e.p.
    cp4 = g4.captured_pieces()
    check('en passant — 1 взятие чёрной пешки',
          cp4 == [(SideType.BLACK, PieceType.PAWN)], cp4)


def main():
    print('=== Дымовой тест game.py ===\n')
    test_fools_mate_via_game()
    print()
    test_undo_to_start()
    print()
    test_insufficient_material()
    print()
    test_50_move_rule()
    print()
    test_threefold_repetition()
    print()
    test_repetition_irrelevant_ep()
    print()
    test_san_disambiguation()
    print()
    test_fen_pgn()
    print()
    test_from_fen()
    print()
    test_from_pgn()
    print()
    test_captured_pieces()
    print(f'\n=== Итог: PASS={PASS}, FAIL={FAIL} ===')
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == '__main__':
    main()
