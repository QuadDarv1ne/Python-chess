"""Дымовой тест движка: легальность хода из старта и мат в 1."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Консоль Windows по умолчанию в cp1251 — переключаем вывод в UTF-8, иначе
# юникодные символы (→, ≈, кириллица) роняют тест с UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8')

from chess_game.enums import PieceType, SideType
from chess_game.field import Field
from chess_game.move import Move
from chess_game.point import Point
from chess_game import rules as R
from chess_game.engine import Engine, MATE_THRESHOLD


def apply_line(field, rights, ep, moves):
    for move in moves:
        R.apply_move(field, move)
        rights = R.update_castling_rights(rights, move)
        ep = R.en_passant_target(move) if move.is_double_pawn else None
    return rights, ep


def test_eval_and_aspiration():
    print('Тест: оценка (фаза/эндшпиль/щит короля) и аспирационные окна')
    from chess_game.engine import evaluate

    # Стартовая позиция симметрична → оценка 0.
    assert evaluate(Field(), SideType.WHITE) == 0.0, 'стартовая позиция не симметрична'

    # Зеркальные позиции (только короли) тоже должны давать ровно 0: белый и
    # чёрный король на симметричных относительно центра клетках. Регрессия на
    # ошибку двойной смены знака в оценке короля (чёрный король «ценился» как белый).
    for wx, wy, bx, by in ((6, 7, 6, 0), (4, 4, 4, 3), (2, 2, 2, 5)):
        f = Field.empty()
        f.set_piece(wx, wy, PieceType.KING, SideType.WHITE)
        f.set_piece(bx, by, PieceType.KING, SideType.BLACK)
        assert evaluate(f, SideType.WHITE) == 0.0, \
            f'оценка королей не симметрична: K{(wx, wy)} vs K{(bx, by)}'

    # Проходная пешка: чем ближе к превращению, тем выше оценка; зеркальная
    # пара проходных (белая e5 vs чёрная e4) должна давать ровно 0.
    def passed(py):
        f = Field.empty()
        f.set_piece(4, 7, PieceType.KING, SideType.WHITE)
        f.set_piece(4, 0, PieceType.KING, SideType.BLACK)
        f.set_piece(3, py, PieceType.PAWN, SideType.WHITE)
        return evaluate(f, SideType.WHITE)
    vals = [passed(py) for py in (6, 5, 4, 3, 2)]
    assert all(a < b for a, b in zip(vals, vals[1:])), \
        f'продвинутая проходная должна цениться выше: {vals}'
    fm = Field.empty()
    fm.set_piece(4, 7, PieceType.KING, SideType.WHITE)
    fm.set_piece(4, 0, PieceType.KING, SideType.BLACK)
    fm.set_piece(3, 3, PieceType.PAWN, SideType.WHITE)
    fm.set_piece(3, 4, PieceType.PAWN, SideType.BLACK)
    assert evaluate(fm, SideType.WHITE) == 0.0, 'зеркальные проходные не симметричны'



    # Эндшпиль: король в центре (e6) должен оцениваться выше, чем в углу (a1).
    def eg(kx, ky):
        f = Field.empty()
        f.set_piece(kx, ky, PieceType.KING, SideType.WHITE)
        f.set_piece(4, 6, PieceType.PAWN, SideType.WHITE)
        f.set_piece(4, 0, PieceType.KING, SideType.BLACK)
        return evaluate(f, SideType.WHITE)
    assert eg(4, 2) > eg(0, 7), 'в эндшпиле король в центре должен быть лучше угла'

    # Пешечный щит в миттельшпиле: при равном материале король g1 со щитом
    # f2/g2/h2 оценивается выше, чем с теми же пешками на a2/b2/c2 (далеко).
    def mg(shield):
        f = Field.empty()
        f.set_piece(6, 7, PieceType.KING, SideType.WHITE)   # g1
        f.set_piece(4, 0, PieceType.KING, SideType.BLACK)
        f.set_piece(3, 0, PieceType.QUEEN, SideType.BLACK)  # фаза миттельшпиля
        f.set_piece(0, 0, PieceType.QUEEN, SideType.WHITE)  # баланс материала
        files = (5, 6, 7) if shield else (0, 1, 2)
        for fx in files:
            f.set_piece(fx, 6, PieceType.PAWN, SideType.WHITE)
        return evaluate(f, SideType.WHITE)
    assert mg(True) > mg(False), 'пешечный щит должен улучшать оценку короля'
    print('  [PASS] evaluate: симметрия старта, централизация короля, щит')

    # Аспирационные окна (depth>=4): поиск на фиксированной глубине 6 без лимита
    # времени должен завершиться, вернуть легальный ход и быть детерминированным.
    field = Field()
    rights = R.CastlingRights()
    legal = R.legal_moves(field, SideType.WHITE, rights, None)
    eng = Engine(max_depth=6, time_limit=None, noise_scale=0.0)
    r1 = eng.search(Field.copy(field), SideType.WHITE, rights, None)
    r2 = eng.search(Field.copy(field), SideType.WHITE, rights, None)
    assert r1.move in legal, 'аспирация вернула нелегальный ход'
    assert r1.move == r2.move, 'поиск должен быть детерминированным (noise=0)'
    assert r1.depth == 6, f'ожидалась глубина 6, получено {r1.depth}'
    print(f'  [PASS] аспирация: depth={r1.depth}, ход={r1.move}, '
          f'детерминирован, узлов={r1.nodes}\n')

    # Правило 50 ходов внутри поиска: K vs K, halfmove=99, глубина 1.
    # Любой ход доводит счётчик до 100, и у чёрных нет шаха — оценка 0,
    # а не позиционная разница королей.
    bare = Field.empty()
    bare.set_piece(0, 7, PieceType.KING, SideType.WHITE)
    bare.set_piece(7, 0, PieceType.KING, SideType.BLACK)
    draw_eng = Engine(max_depth=1, time_limit=None, noise_scale=0.0)
    draw_res = draw_eng.search(bare, SideType.WHITE, R.CastlingRights(False, False, False, False),
                               None, halfmove=99)
    assert draw_res.move is not None, 'при halfmove=99 ход всё ещё выбирается'
    assert draw_res.score == 0.0, f'ожидалась ничья по 50 ходам, score={draw_res.score}'
    print('  [PASS] правило 50 ходов внутри поиска: score=0')

    # PV не подставляет ход из TT-записи без счётчика, если при текущем
    # halfmove эта запись хранилась бы уже с ключом (позиция, halfmove).
    rights0 = R.CastlingRights(False, False, False, False)
    key = R.position_key(bare, SideType.WHITE, rights0, None)
    plain_move = Move.normal(0, 7, 1, 7)   # a1-b1, depth 5 → слот без счётчика только при hm < 95
    clock_move = Move.normal(0, 7, 0, 6)   # a1-a2
    draw_eng._Engine__tt[key] = (5, 0, 10.0, plain_move)
    draw_eng._Engine__tt[(key, 99)] = (2, 0, 0.0, clock_move)
    pv_hi = draw_eng._extract_pv(bare, SideType.WHITE, rights0, None, halfmove=99)
    pv_lo = draw_eng._extract_pv(bare, SideType.WHITE, rights0, None, halfmove=0)
    assert pv_hi and pv_hi[0] == clock_move, pv_hi
    assert pv_lo and pv_lo[0] == plain_move, pv_lo
    print('  [PASS] PV не берёт ход из чужого счётчика 50 ходов')


def main():
    print('=== Дымовой тест движка ===\n')

    # 1. Из стартовой позиции — легальный ход за разумное время
    field = Field()
    rights = R.CastlingRights()
    ep = None
    legal = R.legal_moves(field, SideType.WHITE, rights, ep)
    engine = Engine(max_depth=3, time_limit=2.0, noise_scale=0.0)
    t0 = time.perf_counter()
    res = engine.search(field, SideType.WHITE, rights, ep)
    dt = time.perf_counter() - t0
    print(f'Старт: ход={res.move}, оценка={res.score:.0f}, глубина={res.depth}, '
          f'узлов={res.nodes}, время={dt:.2f}s')
    assert res.move in legal, 'движок вернул нелегальный ход!'
    assert dt < 5.0, f'слишком медленно: {dt:.2f}s'
    print('  [PASS] ход легален и найден быстро\n')

    # 2. Мат в 1: позиция детского мата перед 4.Qxf7# (ход белых)
    field = Field()
    rights = R.CastlingRights()
    moves = [
        Move.double_pawn(4, 6, 4, 4),   # 1.e4
        Move.double_pawn(4, 1, 4, 3),   # 1...e5
        Move.normal(5, 7, 2, 4),        # 2.Bc4
        Move.normal(1, 0, 2, 2),        # 2...Nc6
        Move.normal(3, 7, 7, 3),        # 3.Qh5
        Move.normal(6, 0, 5, 2),        # 3...Nf6  (ход белых сейчас)
    ]
    rights, ep = apply_line(field, rights, None, moves)
    # Белые могут поставить мат 4.Qxf7#
    engine = Engine(max_depth=3, time_limit=3.0, noise_scale=0.0)
    res = engine.search(field, SideType.WHITE, rights, ep)
    print(f'Мат-в-1: ход={res.move}, оценка={res.score:.0f}, глубина={res.depth}')
    # Применим ход и проверим, что это мат
    R.apply_move(field, res.move)
    status = R.game_status(field, SideType.BLACK,
                           R.update_castling_rights(rights, res.move), None)
    print(f'  статус чёрных после хода: {status}')
    assert status == 'checkmate', f'движок не нашёл мат в 1 (статус={status}, ход={res.move})'
    print('  [PASS] движок находит мат в 1\n')

    # 3. Мат в 2: две ладьи-лесенка. Белые Ra1, Rb1, Kg1; чёрный Ke8 (один).
    #    Форсированный мат в 2: 1.Ra7 (или Rb7) Kd8/Kf8 2.Rb8# (или Ra8#).
    #    Проверяем устойчиво: движок находит мат-оценку, и после его хода
    #    на КАЖДЫЙ ответ чёрных у белых есть мат в 1.
    field = Field.empty()
    field.set_piece(0, 7, PieceType.ROOK, SideType.WHITE)    # Ra1
    field.set_piece(1, 7, PieceType.ROOK, SideType.WHITE)    # Rb1
    field.set_piece(6, 7, PieceType.KING, SideType.WHITE)    # Kg1
    field.set_piece(4, 0, PieceType.KING, SideType.BLACK)    # Ke8
    rights = R.CastlingRights(wk=False, wq=False, bk=False, bq=False)
    ep = None
    engine = Engine(max_depth=4, time_limit=5.0, noise_scale=0.0)
    res = engine.search(field, SideType.WHITE, rights, ep)
    print(f'Мат-в-2: ход={res.move}, оценка={res.score:.0f}, глубина={res.depth}')
    assert res.score >= MATE_THRESHOLD, \
        f'движок не нашёл мат (оценка={res.score}, ход={res.move})'

    # Применим найденный ход и проверим форсированность
    u = R.apply_move(field, res.move)
    r_rights = R.update_castling_rights(rights, res.move)
    r_ep = R.en_passant_target(res.move) if res.move.is_double_pawn else None
    black_replies = R.legal_moves(field, SideType.BLACK, r_rights, r_ep)
    assert black_replies, 'после хода белых чёрные не должны быть уже заматованы (мат в 2, не в 1)'
    all_forced = True
    for reply in black_replies:
        ub = R.apply_move(field, reply)
        b_rights = R.update_castling_rights(r_rights, reply)
        b_ep = R.en_passant_target(reply) if reply.is_double_pawn else None
        # Есть ли у белых мат в 1?
        has_mate1 = False
        for wm in R.legal_moves(field, SideType.WHITE, b_rights, b_ep):
            uw = R.apply_move(field, wm)
            status = R.game_status(field, SideType.BLACK,
                                   R.update_castling_rights(b_rights, wm),
                                   R.en_passant_target(wm) if wm.is_double_pawn else None)
            R.undo_move(field, uw)
            if status == 'checkmate':
                has_mate1 = True
                break
        R.undo_move(field, ub)
        if not has_mate1:
            all_forced = False
            print(f'  нет мат-в-1 после ответа {reply}')
            break
    R.undo_move(field, u)
    assert all_forced, 'мат не форсирован (не на все ответы есть мат в 1)'
    print('  [PASS] движок находит форсированный мат в 2\n')

    test_eval_and_aspiration()

    print('=== Все дымовые тесты движка пройдены ===')


if __name__ == '__main__':
    main()
