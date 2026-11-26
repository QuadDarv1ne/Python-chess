"""
Tkinter-интерфейс шахмат на основе chess_game.

Зеркальная по ролям замена checkers/main.py: канвасная доска 8×8 с глифами
фигур, подсветка выбора и возможных ходов, анимация хода (скольжение),
диалог превращения пешки, поиск хода ИИ в отдельном потоке (с отменой),
подсказка лучшего хода со стрелкой и оценкой, панель статуса и истории,
горячие клавиши, экспорт PGN и FEN.

Запуск:
    python main.py
(или под бездисплейным окружением: xvfb-run -a python main.py)
"""

import threading
import queue
import sys
from pathlib import Path
from time import perf_counter

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

# Корень пакета — на случай запуска из другой директории
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chess_game.constants import (
    BOARD_SIZE, CELL_SIZE, BORDER_WIDTH, FIELD_COLORS,
    HOVER_BORDER_COLOR, SELECT_BORDER_COLOR, LAST_MOVE_COLOR, CHECK_COLOR,
    LEGAL_MOVE_COLOR, LEGAL_CAPTURE_COLOR, PIECE_GLYPHS, DIFFICULTY_ORDER,
    PIECE_VALUES,
)
from chess_game.enums import PieceType, SideType, DifficultyType
from chess_game.field import Field
from chess_game.move import Move
from chess_game.game import Game, decode_pgn_bytes
from chess_game.engine import Engine
from chess_game.audio import SoundManager

MARGIN = 22            # поле под координаты
PIECE_FONT_SIZE = int(CELL_SIZE * 0.78)
LABEL_FONT_SIZE = 12

ANIM_DURATION = 0.14   # секунды на слайд фигуры
ANIM_STEP_MS = 14      # период кадров анимации
HINT_COLOR = '#2e8b57' # цвет стрелки подсказки


class ChessApp:
    '''Главное окно приложения.'''

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title('Шахматы')
        root.resizable(False, False)

        self.player_side = SideType.WHITE
        self.difficulty = DifficultyType.MEDIUM
        self.game = Game(player_side=self.player_side, difficulty=self.difficulty)

        # Звук: эффекты хода и фоновая фортепианная музыка (синтез на лету).
        # Менеджер — синглтон на процесс: состояние переживает новые партии.
        self.sound = SoundManager()
        self._sound_var = tk.BooleanVar(value=self.sound.enabled)
        self._music_var = tk.BooleanVar(value=self.sound.music_enabled)
        self._volume_var = tk.IntVar(value=self.sound.volume)
        self._music_volume_var = tk.IntVar(value=self.sound.music_volume)
        self._shuffle_var = tk.BooleanVar(value=self.sound.shuffle_music)

        self.selected = None          # (x, y) выбранной фигуры
        self._hover = None
        self.flipped = (self.player_side == SideType.BLACK)
        self.last_move = None         # Move для подсветки
        self.thinking = False
        self.ai_cancel = None
        self.ai_thread = None
        # Очередь результатов из потока ИИ + поллер на главном потоке:
        # Tkinter не потокобезопасен, поэтому поток не вызывает root.after
        # напрямую, а кладёт результат в очередь; поллер, запущенный через
        # root.after, забирает его и применяет в главном потоке.
        self._result_queue = queue.Queue()
        self._poller_scheduled = False
        # Анимация хода: {from_cx, from_cy, to_cx, to_cy, glyph, outline, fill,
        # skip:(x,y), start, after}. None — анимации нет.
        self._anim = None
        # Подсказка: Move, подсвечивается стрелкой; сбрасывается при любом ходе.
        self._hint_move = None
        # Оценка со стороны белых (сотые пешки) или None.
        self._eval_white = None
        # Текущий прогресс поиска ИИ: (глубина, макс.глубина, оценка, сторона).
        # Заполняется из progress-колбэка движка через очередь результатов.
        self._search_progress = None

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()
        self.render()
        self.update_status()
        self.update_history()

        root.protocol('WM_DELETE_WINDOW', self._on_close)

        # Если игрок играет чёрными — первым ходит ИИ (белыми)
        self.root.after(100, self.maybe_ai_move)

    # -- Разметка --

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m_game = tk.Menu(menubar, tearoff=0)
        m_game.add_command(label='Новая игра\tCtrl+N', command=self.new_game)
        m_game.add_command(label='Отменить ход\tCtrl+Z', command=self.undo)
        m_game.add_command(label='Подсказка\tCtrl+H', command=self.show_hint)
        m_game.add_separator()
        m_game.add_command(label='Сохранить PGN…', command=self.save_pgn)
        m_game.add_command(label='Загрузить PGN…', command=self.load_pgn)
        m_game.add_command(label='Скопировать FEN', command=self.copy_fen)
        m_game.add_command(label='Загрузить FEN…', command=self.load_fen)
        m_game.add_separator()
        m_game.add_command(label='Выйти', command=self._on_close)
        menubar.add_cascade(label='Игра', menu=m_game)

        self._side_var = tk.StringVar(value=self.player_side.name)
        m_side = tk.Menu(menubar, tearoff=0)
        for side, name in ((SideType.WHITE, 'За белых'),
                           (SideType.BLACK, 'За чёрных')):
            m_side.add_radiobutton(label=name, value=side.name,
                                   var=self._side_var, command=self.on_side_change)
        menubar.add_cascade(label='Сторона', menu=m_side)

        self._diff_var = tk.StringVar(value=self.difficulty.name)
        m_diff = tk.Menu(menubar, tearoff=0)
        for d in DIFFICULTY_ORDER:
            m_diff.add_radiobutton(label=d.name_ru, value=d.name,
                                   var=self._diff_var, command=self.on_difficulty_change)
        menubar.add_cascade(label='Сложность', menu=m_diff)

        m_view = tk.Menu(menubar, tearoff=0)
        m_view.add_command(label='Перевернуть доску\tCtrl+F', command=self.toggle_flip)
        menubar.add_cascade(label='Вид', menu=m_view)

        m_sound = tk.Menu(menubar, tearoff=0)
        m_sound.add_checkbutton(label='Звуковые эффекты\tCtrl+S',
                                variable=self._sound_var, command=self.on_sound_toggle)
        m_sound.add_checkbutton(label='Фоновая музыка\tCtrl+M',
                                variable=self._music_var, command=self.on_music_toggle)
        m_sound.add_separator()
        self._previous_track_index = m_sound.index('end') + 1
        m_sound.add_command(label='Предыдущий трек', command=self.sound.previous_track)
        self._next_track_index = m_sound.index('end') + 1
        m_sound.add_command(label='Следующий трек', command=self.sound.next_track)
        self._current_track_index = m_sound.index('end') + 1
        m_sound.add_command(label='Сейчас играет: —', state=tk.DISABLED)
        m_sound.add_checkbutton(label='Перемешивать плейлист',
                                variable=self._shuffle_var, command=self.on_shuffle_toggle)
        m_sound.add_separator()

        m_vol = tk.Menu(m_sound, tearoff=0)
        for vol, label in ((30, 'Низкая'), (50, 'Средняя'), (75, 'Высокая'), (100, 'Максимальная')):
            m_vol.add_radiobutton(label=label, value=vol, variable=self._volume_var,
                                  command=self.on_volume_change)
        m_sound.add_cascade(label='Громкость эффектов', menu=m_vol)

        m_music_vol = tk.Menu(m_sound, tearoff=0)
        for vol, label in ((0, 'Без звука'), (25, 'Низкая'), (45, 'Средняя'),
                           (70, 'Высокая'), (100, 'Максимальная')):
            m_music_vol.add_radiobutton(label=label, value=vol, variable=self._music_volume_var,
                                        command=self.on_music_volume_change)
        m_sound.add_cascade(label='Громкость музыки', menu=m_music_vol)
        self._sound_menu = m_sound
        menubar.add_cascade(label='Звук', menu=m_sound)

        # Последние применённые значения пунктов меню трека. Поллер переконфигурирует
        # их только при реальном изменении: на Windows entryconfigure перерисовывает
        # меню (а смена длины названия трека ещё и меняет его ширину), из-за чего при
        # безусловном обновлении каждые 500 мс открытое меню мерцает и «прыгает».
        self._last_track_label = None
        self._last_nav_state = None

        self.root.config(menu=menubar)
        self.root.after(500, self._refresh_music_menu)

    def _build_layout(self):
        frame = tk.Frame(self.root)
        frame.pack(padx=8, pady=8)

        total = MARGIN * 2 + BORDER_WIDTH * 2 + BOARD_SIZE * CELL_SIZE
        self.canvas = tk.Canvas(frame, width=total, height=total,
                                highlightthickness=0, bg='#3a2a1a')
        self.canvas.pack(side=tk.LEFT)
        self.canvas.bind('<Button-1>', self.on_click)
        self.canvas.bind('<Motion>', self.on_motion)
        self.canvas.bind('<Leave>', lambda e: self._set_hover(None))

        side = tk.Frame(frame)
        side.pack(side=tk.LEFT, padx=(12, 0), fill=tk.Y)

        tk.Label(side, text='Шахматы', font=('DejaVu Sans', 16, 'bold')).pack(anchor='w')
        self.status_var = tk.StringVar(value='')
        self.status_label = tk.Label(side, textvariable=self.status_var,
                                     font=('DejaVu Sans', 12), wraplength=220, justify=tk.LEFT)
        self.status_label.pack(anchor='w', pady=(6, 4))

        # Панель взятых фигур и материального баланса
        self.material_var = tk.StringVar(value='')
        tk.Label(side, textvariable=self.material_var,
                 font=('DejaVu Sans', 11), wraplength=220, justify=tk.LEFT,
                 fg='#3a2a1a').pack(anchor='w', pady=(0, 2))
        # Строка главного варианта (PV) из подсказки
        self.pv_var = tk.StringVar(value='')
        self.pv_label = tk.Label(side, textvariable=self.pv_var,
                                 font=('DejaVu Sans Mono', 9), wraplength=220,
                                 justify=tk.LEFT, fg='#1e3a5f')
        self.pv_label.pack(anchor='w', pady=(0, 8))

        tk.Label(side, text='Ходы:', font=('DejaVu Sans', 10, 'bold')).pack(anchor='w')
        self.history_box = tk.Listbox(side, width=24, height=24, font=('DejaVu Sans Mono', 10))
        self.history_box.pack(anchor='w', fill=tk.Y, expand=True)

        btns = tk.Frame(side)
        btns.pack(anchor='w', pady=(8, 0))
        tk.Button(btns, text='Новая', width=8, command=self.new_game).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(btns, text='Отмена', width=8, command=self.undo).pack(side=tk.LEFT)
        tk.Button(btns, text='Подсказка', width=10, command=self.show_hint).pack(side=tk.LEFT, padx=(4, 0))
        btns2 = tk.Frame(side)
        btns2.pack(anchor='w', pady=(4, 0))
        tk.Button(btns2, text='Перевернуть', width=10, command=self.toggle_flip).pack(side=tk.LEFT)
        tk.Button(btns2, text='PGN', width=6, command=self.save_pgn).pack(side=tk.LEFT, padx=(4, 0))
        tk.Button(btns2, text='FEN', width=6, command=self.copy_fen).pack(side=tk.LEFT, padx=(4, 0))

    def _bind_shortcuts(self):
        self.root.bind('<Control-n>', lambda e: self.new_game())
        self.root.bind('<Control-N>', lambda e: self.new_game())
        self.root.bind('<Control-z>', lambda e: self.undo())
        self.root.bind('<Control-Z>', lambda e: self.undo())
        self.root.bind('<Control-h>', lambda e: self.show_hint())
        self.root.bind('<Control-H>', lambda e: self.show_hint())
        self.root.bind('<Control-f>', lambda e: self.toggle_flip())
        self.root.bind('<Control-F>', lambda e: self.toggle_flip())
        self.root.bind('<Escape>', lambda e: self._clear_selection())
        self.root.bind('<Control-s>', lambda e: self._toggle_sound())
        self.root.bind('<Control-S>', lambda e: self._toggle_sound())
        self.root.bind('<Control-m>', lambda e: self._toggle_music())
        self.root.bind('<Control-M>', lambda e: self._toggle_music())

    # -- Координаты --

    def board_to_screen(self, x: int, y: int):
        '''Верхний-левый угол клетки (x, y) в пикселях'''
        if self.flipped:
            x = BOARD_SIZE - 1 - x
            y = BOARD_SIZE - 1 - y
        ox = MARGIN + BORDER_WIDTH
        return ox + x * CELL_SIZE, ox + y * CELL_SIZE

    def _center_of(self, x: int, y: int):
        sx, sy = self.board_to_screen(x, y)
        return sx + CELL_SIZE // 2, sy + CELL_SIZE // 2

    def screen_to_board(self, px: int, py: int):
        ox = MARGIN + BORDER_WIDTH
        bx = (px - ox) // CELL_SIZE
        by = (py - ox) // CELL_SIZE
        if not (0 <= bx < BOARD_SIZE and 0 <= by < BOARD_SIZE):
            return None
        if self.flipped:
            bx = BOARD_SIZE - 1 - bx
            by = BOARD_SIZE - 1 - by
        return bx, by

    # -- Отрисовка --

    def render(self):
        c = self.canvas
        c.delete('all')
        total = MARGIN * 2 + BORDER_WIDTH * 2 + BOARD_SIZE * CELL_SIZE
        c.create_rectangle(0, 0, total, total, fill='#3a2a1a', outline='')

        # Клетки
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                sx, sy = self.board_to_screen(x, y)
                color = FIELD_COLORS[(x + y) % 2]
                c.create_rectangle(sx, sy, sx + CELL_SIZE, sy + CELL_SIZE,
                                   fill=color, outline='')

        # Подсветка последнего хода
        if self.last_move is not None:
            for (lx, ly) in ((self.last_move.from_x, self.last_move.from_y),
                             (self.last_move.to_x, self.last_move.to_y)):
                sx, sy = self.board_to_screen(lx, ly)
                self._draw_thick_outline(sx, sy, LAST_MOVE_COLOR, 4)

        # Подсветка короля под шахом и в мате
        if self.game.status in ('check', 'checkmate'):
            kpos = self.game.field.king_position(self.game.side_to_move)
            if kpos:
                sx, sy = self.board_to_screen(kpos[0], kpos[1])
                c.create_rectangle(sx + 2, sy + 2, sx + CELL_SIZE - 2, sy + CELL_SIZE - 2,
                                   fill='', outline=CHECK_COLOR, width=4)

        # Подсветка выбора + возможных ходов
        if self.selected is not None:
            sx, sy = self.board_to_screen(*self.selected)
            self._draw_thick_outline(sx, sy, SELECT_BORDER_COLOR, 4)
            for mv in self.game.legal_moves_from(*self.selected):
                tx, ty = self.board_to_screen(mv.to_x, mv.to_y)
                cx, cy = tx + CELL_SIZE // 2, ty + CELL_SIZE // 2
                target = self.game.field.at(mv.to_x, mv.to_y)
                if target.is_empty and not mv.is_en_passant:
                    c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8,
                                  fill=LEGAL_MOVE_COLOR, outline='')
                else:
                    c.create_oval(cx - CELL_SIZE // 2 + 4, cy - CELL_SIZE // 2 + 4,
                                  cx + CELL_SIZE // 2 - 4, cy + CELL_SIZE // 2 - 4,
                                  fill='', outline=LEGAL_CAPTURE_COLOR, width=4)

        # Стрелка подсказки
        if self._hint_move is not None:
            fx, fy = self._center_of(self._hint_move.from_x, self._hint_move.from_y)
            tx, ty = self._center_of(self._hint_move.to_x, self._hint_move.to_y)
            c.create_line(fx, fy, tx, ty, fill=HINT_COLOR, width=6,
                          arrow='last', arrowshape=(14, 16, 7),
                          capstyle='round', tag='hint')

        # Подсветка наведения
        if self._hover is not None:
            sx, sy = self.board_to_screen(*self._hover)
            self._draw_thick_outline(sx, sy, HOVER_BORDER_COLOR, 2)

        # Фигуры (пропускаем клетки, которые сейчас «везёт» анимация)
        skip = self._anim['skip'] if self._anim else ()
        for x, y, piece in self.game.field.pieces():
            if (x, y) in skip:
                continue
            self._draw_piece(x, y, piece)

        # Анимируемые фигуры (король и, при рокировке, ладья)
        if self._anim is not None:
            a = self._anim
            t = a['t']
            for part in a['parts']:
                cx = part['from_cx'] + (part['to_cx'] - part['from_cx']) * t
                cy = part['from_cy'] + (part['to_cy'] - part['from_cy']) * t
                self._draw_glyph(cx, cy, part['glyph'], part['outline'], part['fill'])

        # Координаты. board_to_screen уже учитывает переворот доски, поэтому
        # подпись ставится под столбец/строку доски i и не должна переворачиваться
        # повторно: иначе при игре за чёрных буквы и цифры шли бы в обратном порядке.
        for i in range(BOARD_SIZE):
            file_char = chr(ord('a') + i)
            rank_digit = str(BOARD_SIZE - i)
            sx, _ = self.board_to_screen(i, 0)
            c.create_text(sx + CELL_SIZE // 2, total - MARGIN // 2,
                          text=file_char, font=('DejaVu Sans', LABEL_FONT_SIZE), fill='#e7cfa9')
            _, sy = self.board_to_screen(0, i)
            c.create_text(MARGIN // 2, sy + CELL_SIZE // 2,
                          text=rank_digit, font=('DejaVu Sans', LABEL_FONT_SIZE), fill='#e7cfa9')

    def _draw_piece(self, x, y, piece):
        glyph = PIECE_GLYPHS.get((piece.color, piece.type))
        if not glyph:
            return
        cx, cy = self._center_of(x, y)
        if piece.color == SideType.WHITE:
            outline_c, fill_c = '#1a1a1a', '#f6f3ee'
        else:
            outline_c, fill_c = '#d8d8d8', '#161616'
        self._draw_glyph(cx, cy, glyph, outline_c, fill_c)

    def _draw_glyph(self, cx, cy, glyph, outline_c, fill_c):
        '''Фигура с гало: 4 смещения контрастным цветом, затем основная заливка'''
        c = self.canvas
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            c.create_text(cx + dx, cy + dy, text=glyph,
                          font=('DejaVu Sans', PIECE_FONT_SIZE), fill=outline_c)
        c.create_text(cx, cy, text=glyph,
                      font=('DejaVu Sans', PIECE_FONT_SIZE), fill=fill_c)

    def _draw_thick_outline(self, sx, sy, color, width):
        self.canvas.create_rectangle(sx, sy, sx + CELL_SIZE, sy + CELL_SIZE,
                                     fill='', outline=color, width=width)

    # -- Анимация хода --

    def _start_anim(self, move: Move, after):
        '''Запустить слайд фигуры из move.from в move.to, по завершении вызвать after().

        Ход уже применён к game.field, поэтому «доходная» фигура берётся с клетки
        назначения (для превращения это уже новая фигура — поэтому подменяем
        глиф на пешку, чтобы анимировался именно пешечный ход).
        '''
        landed = self.game.field.at(move.to_x, move.to_y)
        color = landed.color
        ptype = PieceType.PAWN if move.is_promotion else landed.type
        parts = [self._anim_part(move.from_x, move.from_y, move.to_x, move.to_y,
                                 color, ptype)]
        skip = {(move.to_x, move.to_y)}
        if move.is_castle:
            y = move.from_y
            if move.castle_side == 'K':
                rfrom, rto = (7, y), (5, y)
            else:
                rfrom, rto = (0, y), (3, y)
            rook = self.game.field.at(*rto)
            parts.append(self._anim_part(rfrom[0], rfrom[1], rto[0], rto[1],
                                         rook.color, PieceType.ROOK))
            skip.add(rto)
        self._anim = {
            'parts': parts,
            'skip': skip,
            't': 0.0, 'start': perf_counter(), 'after': after,
        }
        self._anim_step()

    def _anim_part(self, fx, fy, tx, ty, color, ptype):
        scx, scy = self._center_of(fx, fy)
        tcx, tcy = self._center_of(tx, ty)
        if color == SideType.WHITE:
            outline_c, fill_c = '#1a1a1a', '#f6f3ee'
        else:
            outline_c, fill_c = '#d8d8d8', '#161616'
        return {
            'from_cx': scx, 'from_cy': scy, 'to_cx': tcx, 'to_cy': tcy,
            'glyph': PIECE_GLYPHS.get((color, ptype), ''),
            'outline': outline_c, 'fill': fill_c,
        }

    def _anim_step(self):
        if self._anim is None:
            return
        elapsed = perf_counter() - self._anim['start']
        t = min(1.0, elapsed / ANIM_DURATION)
        # ease-out: к концу замедляется
        self._anim['t'] = 1.0 - (1.0 - t) ** 2
        self.render()
        if t >= 1.0:
            after = self._anim['after']
            self._anim = None
            after()
        else:
            self.root.after(ANIM_STEP_MS, self._anim_step)

    # -- Взаимодействие --

    def _set_hover(self, pos):
        if self._anim is not None:
            return
        if pos != self._hover:
            self._hover = pos
            self.render()

    def on_motion(self, event):
        pos = self.screen_to_board(event.x, event.y)
        self._set_hover(pos)

    def _clear_selection(self):
        if self.selected is None or self._anim is not None:
            return
        self.selected = None
        self.render()

    def on_click(self, event):
        if self.thinking or self._anim is not None or self.game.is_game_over:
            return
        if self.game.side_to_move != self.player_side:
            return
        pos = self.screen_to_board(event.x, event.y)
        if pos is None:
            return
        x, y = pos
        piece = self.game.field.at(x, y)

        if self.selected is None:
            if not piece.is_empty and piece.color == self.player_side:
                self.selected = (x, y)
                self._hint_move = None
                self.render()
            return

        sx, sy = self.selected
        if (x, y) == (sx, sy):
            self.selected = None
            self.render()
            return
        if not piece.is_empty and piece.color == self.player_side:
            self.selected = (x, y)
            self.render()
            return

        # Пытаемся сходить в (x, y)
        candidates = [m for m in self.game.legal_moves_from(sx, sy)
                      if m.to_x == x and m.to_y == y]
        if not candidates:
            self.selected = None
            self.render()
            return
        if any(m.is_promotion for m in candidates):
            self._choose_promotion(sx, sy, x, y)
        else:
            self._do_move(candidates[0])

    def _choose_promotion(self, fx, fy, tx, ty):
        '''Диалог выбора фигуры превращения (модальный)'''
        win = tk.Toplevel(self.root)
        win.title('Превращение пешки')
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text='Выберите фигуру:', font=('DejaVu Sans', 11)).pack(padx=10, pady=8)

        chosen = {'piece': None}

        def pick(ptype):
            chosen['piece'] = ptype
            win.destroy()

        for ptype in (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT):
            glyph = PIECE_GLYPHS[(self.player_side, ptype)]
            b = tk.Button(win, text=glyph, font=('DejaVu Sans', 28),
                          width=3, command=lambda p=ptype: pick(p))
            b.pack(side=tk.LEFT, padx=4, pady=6)

        self.root.wait_window(win)
        if chosen['piece'] is not None:
            self._do_move(Move.promoting(fx, fy, tx, ty, chosen['piece']))

    def _do_move(self, move: Move):
        kind = self._move_sound_kind(move)   # определяем ДО применения хода
        if not self.game.make_move(move):
            return
        self.sound.play(kind)
        self.last_move = move
        self.selected = None
        self._hint_move = None
        self._eval_white = None
        self.pv_var.set('')   # устаревший вариант подсказки убираем при ходе
        # Анимация, а по её завершении — статус/история/возможно ход ИИ
        self._start_anim(move, self._after_move)

    def _after_move(self):
        self.render()
        self.update_status()
        self.update_history()
        self.update_material()
        self.maybe_ai_move()

    # -- ИИ --

    def maybe_ai_move(self):
        if self.game.is_game_over:
            return
        if self.game.side_to_move == self.player_side:
            return
        if self.thinking:
            return
        self.thinking = True
        self._search_progress = None
        self.update_status()

        cancel = threading.Event()
        self.ai_cancel = cancel
        diff = self.game.difficulty
        field_copy = Field.copy(self.game.field)
        side = self.game.side_to_move
        rights = self.game.castling_rights
        ep = self.game.en_passant_target

        def progress(depth, max_depth, best_move, best_score):
            # Вызывается из потока ИИ: только кладём в очередь, Tk не трогаем
            self._result_queue.put(('progress', depth, max_depth, best_score, side, cancel))

        engine = Engine(max_depth=diff.depth, time_limit=diff.time_limit,
                        noise_scale=diff.noise_scale, cancel=cancel,
                        progress=progress)

        def work():
            res = engine.search(field_copy, side, rights, ep,
                                rep_keys=self.game.repetition_keys(),
                                halfmove=self.game.halfmove_clock)
            # Не трогаем Tk из потока — только кладём результат в очередь
            self._result_queue.put((res, cancel, side))

        t = threading.Thread(target=work, daemon=True)
        self.ai_thread = t
        t.start()
        self._ensure_poller()

    def _ensure_poller(self):
        '''Запустить (если ещё не идёт) поллер очереди результатов на главном потоке'''
        if self._poller_scheduled:
            return
        self._poller_scheduled = True
        self.root.after(50, self._poll_ai)

    def _poll_ai(self):
        '''Забрать готовые результаты ИИ/подсказки и применить их (главный поток)'''
        try:
            while True:
                item = self._result_queue.get_nowait()
                tag = item[0] if isinstance(item, tuple) and item else None
                if tag == 'progress':
                    _, depth, max_depth, score, side, token = item
                    if token is self.ai_cancel:
                        self._search_progress = (depth, max_depth, score, side)
                        self.update_status()
                elif tag == 'hint':
                    _, res, token, side = item
                    if token is self.ai_cancel:
                        self._on_hint_done(res, side)
                else:
                    res, token, side = item
                    self._on_ai_done(res, token, side)
        except queue.Empty:
            pass
        # Пока ИИ думает — продолжаем опрашивать; иначе поллер останавливается
        if self.thinking:
            self.root.after(50, self._poll_ai)
        else:
            self._poller_scheduled = False

    def _on_ai_done(self, res, token, side):
        # Игнорируем устаревший результат (новая игра / отмена во время поиска)
        if token is not self.ai_cancel:
            return
        self.thinking = False
        self._search_progress = None
        if res.move is None or self.game.is_game_over or self.game.side_to_move != side:
            self.update_status()
            return
        # Оценка ИИ — со стороны ходившей стороны; переведём к белым
        self._eval_white = res.score if side == SideType.WHITE else -res.score
        kind = self._move_sound_kind(res.move)   # ДО применения хода
        self.game.make_move(res.move)
        self.sound.play(kind)
        self.last_move = res.move
        self._hint_move = None
        self.pv_var.set('')   # устаревший вариант подсказки убираем при ходе ИИ
        # Анимация хода ИИ, по завершении — финальный рендер и статус
        self._start_anim(res.move, self._after_move)

    # -- Подсказка --

    def show_hint(self):
        '''Запустить движок за игрока и подсветить лучший ход стрелкой.'''
        if self.thinking or self._anim is not None or self.game.is_game_over:
            return
        if self.game.side_to_move != self.player_side:
            return
        self.thinking = True
        self._search_progress = None
        self.update_status()

        cancel = threading.Event()
        self.ai_cancel = cancel
        # Подсказку считаем на фиксированной умеренной глубине, независимо от
        # уровня сложности: цель — показать разумный ход, а не «сдать» партию.
        diff = self.game.difficulty
        depth = max(3, min(5, diff.depth))
        field_copy = Field.copy(self.game.field)
        side = self.game.side_to_move
        rights = self.game.castling_rights
        ep = self.game.en_passant_target

        def progress(depth_now, max_depth, best_move, best_score):
            self._result_queue.put(('progress', depth_now, max_depth, best_score, side, cancel))

        engine = Engine(max_depth=depth, time_limit=3.0, noise_scale=0.0,
                        cancel=cancel, progress=progress)

        def work():
            res = engine.search(field_copy, side, rights, ep,
                                rep_keys=self.game.repetition_keys(),
                                halfmove=self.game.halfmove_clock)
            self._result_queue.put(('hint', res, cancel, side))

        threading.Thread(target=work, daemon=True).start()
        self._ensure_poller()

    def _on_hint_done(self, res, side):
        self.thinking = False
        self._search_progress = None
        if res.move is not None and self.game.side_to_move == side and not self.game.is_game_over:
            self._hint_move = res.move
            self._eval_white = res.score if side == SideType.WHITE else -res.score
            # Главный вариант из TT (первые ~6 полуходов)
            pv_moves = (res.pv or [])[:6]
            if pv_moves:
                self.pv_var.set('Вариант: ' + ' '.join(self._move_text(m) for m in pv_moves))
            else:
                self.pv_var.set('')
        self.render()
        self.update_status()

    # -- Управление партией --

    def new_game(self):
        self._cancel_ai()
        self._anim = None
        self.game = Game(player_side=self.player_side, difficulty=self.difficulty)
        self.selected = None
        self.last_move = None
        self._hint_move = None
        self._eval_white = None
        self.pv_var.set('')
        self.flipped = (self.player_side == SideType.BLACK)
        self.render()
        self.update_status()
        self.update_history()
        self.update_material()
        self.maybe_ai_move()

    def undo(self):
        if self._anim is not None:
            return
        self._cancel_ai()
        # В партии с ИИ отменяем ход ИИ + ход игрока, чтобы вернуться к ходу игрока
        if self.game.history:
            self.game.undo()
        if self.game.history and self.game.side_to_move != self.player_side:
            self.game.undo()
        self.selected = None
        self._hint_move = None
        self._eval_white = None
        self.pv_var.set('')
        self.last_move = self.game.history[-1].move if self.game.history else None
        self.render()
        self.update_status()
        self.update_history()
        self.update_material()
        self.maybe_ai_move()

    def on_difficulty_change(self):
        try:
            d = DifficultyType[self._diff_var.get()]
        except KeyError:
            return
        self.difficulty = d
        self.game.set_difficulty(d)
        self.update_status()

    def on_side_change(self):
        try:
            side = SideType[self._side_var.get()]
        except KeyError:
            return
        if side == self.player_side:
            return
        self.player_side = side
        # Смена стороны — новая партия, чтобы не нарушать очерёдность
        self.new_game()

    # -- Звук --

    def _move_sound_kind(self, move: Move) -> str:
        '''Тип эффекта для хода: превращение > взятие > обычный ход.

        Вызывать ДО применения хода — состояние поля нужно для проверки взятия.
        '''
        if move.is_promotion:
            return 'promote'
        target = self.game.field.at(move.to_x, move.to_y)
        if not target.is_empty or move.is_en_passant:
            return 'capture'
        return 'move'

    def on_sound_toggle(self):
        self.sound.set_enabled(self._sound_var.get())
        # Если звук недоступен на платформе — вернуть галку в снятое состояние
        self._sound_var.set(self.sound.enabled)

    def on_music_toggle(self):
        self.sound.set_music_enabled(self._music_var.get())
        # Если платформа не поддерживает музыку — вернуть галку в снятое состояние
        self._music_var.set(self.sound.music_enabled)

    def _toggle_sound(self):
        '''Горячая клавиша: переключить эффекты и синхронизировать галку меню.'''
        self.sound.toggle()
        self._sound_var.set(self.sound.enabled)

    def _toggle_music(self):
        '''Горячая клавиша: переключить музыку и синхронизировать галку меню.'''
        self.sound.toggle_music()
        self._music_var.set(self.sound.music_enabled)

    def on_shuffle_toggle(self):
        self.sound.set_shuffle_music(self._shuffle_var.get())

    def on_volume_change(self):
        self.sound.set_volume(self._volume_var.get())

    def on_music_volume_change(self):
        self.sound.set_music_volume(self._music_volume_var.get())

    def _refresh_music_menu(self):
        track = self.sound.current_track or '—'
        self._music_var.set(self.sound.music_enabled)
        # Обновляем пункты только при изменении — иначе каждые 500 мс переконфигурация
        # перерисовывает меню и оно мерцает/прыгает (особенно когда открыто).
        track_label = f'Сейчас играет: {track}'
        if track_label != self._last_track_label:
            self._last_track_label = track_label
            self._sound_menu.entryconfigure(
                self._current_track_index, label=track_label)
        nav_state = (
            tk.NORMAL
            if self.sound.music_enabled and self.sound.music_track_navigation_available
            else tk.DISABLED
        )
        if nav_state != self._last_nav_state:
            self._last_nav_state = nav_state
            self._sound_menu.entryconfigure(self._previous_track_index, state=nav_state)
            self._sound_menu.entryconfigure(self._next_track_index, state=nav_state)
        self.root.after(500, self._refresh_music_menu)

    def toggle_flip(self):
        self.flipped = not self.flipped
        self.render()

    def _cancel_ai(self):
        if self.ai_cancel is not None:
            self.ai_cancel.set()
        self.ai_cancel = None
        self.thinking = False
        self._search_progress = None

    # -- PGN / FEN --

    def save_pgn(self):
        '''Сохранить партию в PGN-файл.'''
        try:
            text = self.game.pgn()
        except Exception as e:
            messagebox.showerror('PGN', f'Не удалось сформировать PGN: {e}')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.pgn',
            filetypes=[('PGN', '*.pgn'), ('Все файлы', '*.*')],
            initialfile='game.pgn',
            title='Сохранить партию как PGN')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            messagebox.showinfo('PGN', f'Партия сохранена:\n{path}')
        except OSError as e:
            messagebox.showerror('PGN', f'Ошибка записи: {e}')

    def copy_fen(self):
        '''Скопировать FEN текущей позиции в буфер обмена.'''
        try:
            fen = self.game.fen()
        except Exception as e:
            messagebox.showerror('FEN', f'Не удалось сформировать FEN: {e}')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(fen)
        messagebox.showinfo('FEN', f'FEN скопирован в буфер обмена:\n{fen}')

    def load_fen(self):
        '''Загрузить позицию из FEN (вставка для анализа/доигровки).'''
        fen = simpledialog.askstring(
            'Загрузить FEN',
            'Введите FEN позиции:',
            initialvalue=self.game.fen(),
            parent=self.root)
        if not fen:
            return
        fen = fen.strip()
        try:
            game = Game.from_fen(fen, player_side=None, difficulty=self.difficulty)
        except ValueError as e:
            messagebox.showerror('FEN', f'Неверный FEN:\n{e}')
            return
        self._cancel_ai()
        self._anim = None
        self.game = game
        # Игрок берёт сторону, чья очередь хода; доска разворачивается соответственно
        self.player_side = game.side_to_move
        self._side_var.set(self.player_side.name)
        self.flipped = (self.player_side == SideType.BLACK)
        self.selected = None
        self.last_move = None
        self._hint_move = None
        self._eval_white = None
        self.pv_var.set('')
        self.render()
        self.update_status()
        self.update_history()
        self.update_material()
        self.maybe_ai_move()

    def load_pgn(self):
        '''Загрузить партию из PGN-файла и разыграть ходы до текущей позиции.'''
        path = filedialog.askopenfilename(
            defaultextension='.pgn',
            filetypes=[('PGN', '*.pgn'), ('Все файлы', '*.*')],
            title='Открыть партию PGN')
        if not path:
            return
        try:
            text = decode_pgn_bytes(Path(path).read_bytes())
        except OSError as e:
            messagebox.showerror('PGN', f'Не удалось прочитать файл:\n{e}')
            return
        try:
            game = Game.from_pgn(text, player_side=None, difficulty=self.difficulty)
        except ValueError as e:
            messagebox.showerror('PGN', f'Ошибка разбора PGN:\n{e}')
            return
        self._cancel_ai()
        self._anim = None
        self.game = game
        # Игрок продолжает стороной, чья очередь хода; доска разворачивается
        self.player_side = game.side_to_move
        self._side_var.set(self.player_side.name)
        self.flipped = (self.player_side == SideType.BLACK)
        self.selected = None
        self.last_move = game.history[-1].move if game.history else None
        self._hint_move = None
        self._eval_white = None
        self.pv_var.set('')
        self.render()
        self.update_status()
        self.update_history()
        self.update_material()
        self.maybe_ai_move()

    # -- Панели --

    def update_status(self):
        if self.thinking:
            text = f'ИИ думает… ({self.game.difficulty.name_ru})'
            if self._search_progress is not None:
                depth, max_depth, score, side = self._search_progress
                white = score if side == SideType.WHITE else -score
                sign = '+' if white >= 0 else ''
                text += f'  гл.{depth}/{max_depth}  {sign}{white / 100:.2f}'
        else:
            text = self.game.result_ru()
            if self._eval_white is not None and not self.game.is_game_over:
                sign = '+' if self._eval_white >= 0 else ''
                text += f'   оценка {sign}{self._eval_white / 100:.2f}'
        self.status_var.set(text)

    def update_history(self):
        self.history_box.delete(0, tk.END)
        for line in self.game.move_list_text():
            self.history_box.insert(tk.END, line)
        if self.history_box.size() > 0:
            self.history_box.see(tk.END)

    def update_material(self):
        '''Панель взятых фигур и материального баланса (со стороны белых).

        Взятые фигуры берутся из реальной истории ходов (game.captured_pieces),
        поэтому панель корректна и при превращениях пешек, и для позиций из FEN.
        Баланс — из фактического материала на доске (тоже верен при превращениях).
        '''
        order = (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP,
                 PieceType.KNIGHT, PieceType.PAWN)
        rank = {t: i for i, t in enumerate(order)}
        # Сортируем взятые по старшинству фигур для стабильного вида
        captured = sorted(self.game.captured_pieces(),
                          key=lambda ct: (ct[0] != SideType.BLACK, rank[ct[1]]))
        cap_w = [t for c, t in captured if c == SideType.BLACK]   # взяли белые
        cap_b = [t for c, t in captured if c == SideType.WHITE]   # взяли чёрные
        val_w = val_b = 0
        for _, _, p in self.game.field.pieces():
            if p.is_empty or p.type == PieceType.KING:
                continue
            v = PIECE_VALUES[p.type]
            if p.color == SideType.WHITE:
                val_w += v
            else:
                val_b += v
        gw = ''.join(PIECE_GLYPHS[(SideType.BLACK, t)] for t in cap_w)
        gb = ''.join(PIECE_GLYPHS[(SideType.WHITE, t)] for t in cap_b)
        bal = (val_w - val_b) / 100.0
        self.material_var.set(
            f'Белые взяли: {gw or "—"}   Чёрные взяли: {gb or "—"}   баланс {bal:+.1f}')

    @staticmethod
    def _move_text(move: Move) -> str:
        '''Координатная нотация хода (UCI-подобная) для строки варианта.'''
        from chess_game.game import square_name
        if move.is_castle:
            return 'O-O' if move.castle_side == 'K' else 'O-O-O'
        s = square_name(move.from_x, move.from_y) + square_name(move.to_x, move.to_y)
        if move.is_promotion:
            s += move.promotion.letter.lower()
        return s

    def _on_close(self):
        self._cancel_ai()
        self.sound.set_music_enabled(False)
        self.root.destroy()


def main():
    root = tk.Tk()
    app = ChessApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
