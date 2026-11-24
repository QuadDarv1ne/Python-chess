"""Синтез и воспроизведение звука: эффекты и фоновая фортепианная музыка.

Всё работает из стандартной библиотеки, без сторонних зависимостей.
Звуки синтезируются при первом обращении и кэшируются во временном каталоге
системы. Громкость применяется к самой волне, поэтому не зависит от системного
микшера.

На Windows эффекты играет winsound, а музыка — через MCI (winmm) в отдельном
потоке: эти два механизма не прерывают друг друга.
"""
from __future__ import annotations

import array
import math
import os
import random
import sys
import tempfile
import threading
import wave
from pathlib import Path
from time import perf_counter

# Частоты дискретизации: эффекты в полном качестве, музыка легче
SAMPLE_RATE = 44100
MUSIC_SAMPLE_RATE = 22050

# Версия синтеза: при изменении алгоритмов старый кэш игнорируется
SYNTH_VERSION = 1

# Каталог кэша
CACHE_DIR = Path(tempfile.gettempdir()) / 'python-chess-audio'

# Длительность музыкального лупа (резервная синтезированная тема)
MUSIC_LOOP_SECONDS = 16.0

# Громкость эффектов (применяется к волне WAV при синтезе)
DEFAULT_VOLUME = 50
MIN_VOLUME = 10
MAX_VOLUME = 100

# Громкость музыки — независимая, применяется через MCI (диапазон 0..1000)
DEFAULT_MUSIC_VOLUME = 45
MUSIC_MIN_VOLUME = 0
MUSIC_MAX_VOLUME = 100
MCI_VOLUME_MAX = 1000.0

# --- Умное распределение (ducking) -----------------------------------------
# Когда играет эффект (ход/взятие/превращение), фоновая музыка на короткое
# время приглушается, чтобы эффект был отчётливо слышен, затем плавно
# возвращается к установленной громкости.
DUCK_FACTOR = 0.30          # множитель громкости музыки во время приглушения
DUCK_SECONDS = 0.45         # как долго держать приглушение после последнего эффекта
MUSIC_POLL = 0.04           # период пересчёта громкости в потоке музыки (сек)
FADE_STEP = 55.0            # шаг плавного фейда громкости MCI за один период

# Имена эффектов
EFFECT_NAMES = ('move', 'capture', 'promote')

# Путь к папке с пользовательской музыкой (mp3)
_ASSETS_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'music'
MP3_EXTENSIONS = ('.mp3', '.wav', '.wmv', '.m4a')


def list_music_files() -> list[Path]:
    '''Список музыкальных файлов из assets/music/, отсортированный по имени.'''
    if not _ASSETS_DIR.exists():
        return []
    files = sorted(
        (p for ext in MP3_EXTENSIONS for p in _ASSETS_DIR.glob(f'*{ext}')),
        key=lambda p: p.name.lower(),
    )
    return list(files)


# --- Утилиты синтеза --------------------------------------------------------

def _normalize(samples: list[float], peak: float) -> list[float]:
    maximum = max((abs(v) for v in samples), default=0.0)
    if maximum == 0.0:
        return samples
    scale = peak / maximum
    return [v * scale for v in samples]


def _fade(samples: list[float], edge: int) -> list[float]:
    if edge <= 0:
        return samples
    n = len(samples)
    edge = min(edge, n // 2)
    for i in range(edge):
        factor = i / edge
        samples[i] *= factor
        samples[n - 1 - i] *= factor
    return samples


def _shift(samples: list[float], seconds: float, rate: int = SAMPLE_RATE) -> list[float]:
    return [0.0] * int(rate * seconds) + samples


def _mix(*tracks: list[float]) -> list[float]:
    length = max((len(t) for t in tracks), default=0)
    result = [0.0] * length
    for track in tracks:
        for i, v in enumerate(track):
            result[i] += v
    return result


# --- Фортепиано: имитация молоточка -----------------------------------------

def _piano_key(
    freq: float,
    duration: float,
    amplitude: float = 0.25,
    decay: float = 2.5,
    rate: int = SAMPLE_RATE,
) -> list[float]:
    """Один удар молоточка по струне — фортепианный тон.

    Использует несколько гармоник с разными скоростями затухания, чтобы
    имитировать характер пианино: первые гармоники затухают быстрее.
    """
    count = int(rate * duration)
    attack_samples = max(1, int(rate * 0.002))  # очень быстрый пик
    tail_samples = max(1, int(rate * 0.04))

    # Частоты и веса гармоник (чем выше, тем быстрее затухает)
    harmonics = [
        (1.0, 1.0),
        (2.0, 0.4),
        (3.0, 0.18),
        (4.0, 0.08),
        (5.0, 0.04),
        (6.0, 0.02),
    ]
    steps = [2 * math.pi * freq * h for h, _ in harmonics]
    weights = [w for _, w in harmonics]
    # Скорость затухания каждой гармоники (1 = медленно, 8 = очень быстро)
    decay_rates = [decay, decay * 2.5, decay * 5, decay * 8, decay * 12, decay * 18]

    samples = [0.0] * count
    for i in range(count):
        t = i / rate
        # Атака
        rise = min(1.0, i / attack_samples)
        # Хвост
        fall = min(1.0, (count - i) / tail_samples)

        value = 0.0
        for step, weight, dr in zip(steps, weights, decay_rates):
            value += weight * math.sin(step * i) * math.exp(-t * dr)
        samples[i] = value * rise * fall * amplitude

    return samples


# --- Подушка (аккорды) ------------------------------------------------------

def _pad(freq: float, duration: float, amplitude: float,
         rate: int = MUSIC_SAMPLE_RATE) -> list[float]:
    """Мягкая подушка аккорда с плавным появлением и уходом."""
    count = int(rate * duration)
    attack = max(1, int(rate * 0.3))
    release = max(1, int(rate * 0.5))
    steps = [2 * math.pi * freq * i for i in (1, 2, 3)]

    samples = [0.0] * count
    for i in range(count):
        rise = min(1.0, i / attack)
        fall = min(1.0, (count - i) / release)
        value = math.sin(steps[0] * i) * 1.0 + \
                math.sin(steps[1] * i) * 0.22 + \
                math.sin(steps[2] * i) * 0.08
        samples[i] = value * rise * fall * amplitude
    return samples


# --- Звуки щелчка (дерево) --------------------------------------------------

def _click(duration: float, pitch: float, noise: float, seed: int) -> list[float]:
    """Короткий деревянный стук — фигура ставится на клетку."""
    rnd = random.Random(seed)
    count = int(SAMPLE_RATE * duration)
    step = 2 * math.pi * pitch / SAMPLE_RATE
    step_high = 2 * math.pi * pitch * 2.7 / SAMPLE_RATE

    samples = [0.0] * count
    for i in range(count):
        t = i / SAMPLE_RATE
        envelope = math.exp(-t * 40)
        body = math.sin(step * i) * 0.7 + math.sin(step_high * i) * 0.25
        grain = (rnd.random() * 2 - 1) * noise
        samples[i] = (body + grain) * envelope
    return samples


# --- Эффекты ----------------------------------------------------------------

def _effect_move() -> list[float]:
    """Тихий стук — обычный ход."""
    return _normalize(_click(0.10, 280.0, 0.4, seed=1), 0.85)


def _effect_capture() -> list[float]:
    """Громкий стук — взятие фигуры."""
    first = _click(0.12, 250.0, 0.55, seed=2)
    second = _shift(_click(0.15, 170.0, 0.5, seed=3), 0.06)
    return _normalize(_mix(first, second), 0.9)


def _effect_promote() -> list[float]:
    """Три восходящих пианинных тона — превращение пешки."""
    notes = (659.25, 783.99, 1046.50)  # C5 E5 G5
    tracks = [_shift(_piano_key(f, 0.5, 0.25, decay=3.0), i * 0.10)
              for i, f in enumerate(notes)]
    return _normalize(_mix(*tracks), 0.85)


# --- Фортепианная фоновая тема -----------------------------------------------

def _piano_loop() -> list[float]:
    """Спокойная фортепианная тема: C-мажор пентатоника, 16 сек."""
    rate = MUSIC_SAMPLE_RATE
    total = int(rate * MUSIC_LOOP_SECONDS)
    buffer = [0.0] * total

    def add(samples: list[float], start_seconds: float):
        offset = int(rate * start_seconds)
        limit = min(len(samples), total - offset)
        for i in range(limit):
            buffer[offset + i] += samples[i]

    # Аккорды: C - Am - F - G - Dm - Am - F - G
    # Каждая длится 2 секунды
    chords = (
        (0.0, (130.81, 164.81, 196.00, 261.63)),  # Cmaj7
        (2.0, (220.00, 261.63, 329.63, 440.00)),  # Am7
        (4.0, (174.61, 220.00, 261.63, 349.23)),  # Fmaj7
        (6.0, (196.00, 246.94, 293.66, 392.00)),  # G7
        (8.0, (146.83, 174.61, 220.00, 293.66)),  # Dm7
        (10.0, (220.00, 261.63, 329.63, 440.00)), # Am7
        (12.0, (174.61, 220.00, 261.63, 349.23)), # Fmaj7
        (14.0, (196.00, 246.94, 293.66, 392.00)), # G7
    )
    for start, freqs in chords:
        for f in freqs:
            add(_pad(f, 2.0, 0.12), start)

    # Мелодия — пентатоника C (C D E G A), лёгкая и спокойная
    melody = (
        (0.0, 523.25),   # C5
        (0.75, 587.33),  # D5
        (1.5, 659.25),   # E5
        (2.25, 523.25),  # C5
        (3.0, 493.88),   # B4
        (3.75, 440.00),  # A4

        (4.0, 392.00),   # G4
        (4.75, 440.00),  # A4
        (5.5, 493.88),   # B4
        (6.25, 523.25),  # C5
        (7.0, 493.88),   # B4
        (7.75, 440.00),  # A4

        (8.0, 349.23),   # F4
        (8.75, 392.00),  # G4
        (9.5, 440.00),   # A4
        (10.25, 392.00), # G4
        (11.0, 349.23),  # F4
        (11.75, 329.63), # E4

        (12.0, 392.00),  # G4
        (12.75, 440.00), # A4
        (13.5, 493.88),  # B4
        (14.25, 523.25), # C5
        (15.0, 493.88),  # B4
        (15.75, 440.00), # A4
    )
    for start, freq in melody:
        # Длительность 0.55 с с мягким затуханием — имитация пианино
        add(_piano_key(freq, 0.55, 0.08, decay=2.8, rate=rate), start)

    return _normalize(buffer, 0.5)


# --- Генераторы --------------------------------------------------------------

_GENERATORS = {
    'move': _effect_move,
    'capture': _effect_capture,
    'promote': _effect_promote,
    'music': _piano_loop,
}


# --- Кэш WAV ----------------------------------------------------------------

def _write_wav(path: Path, samples: list[float], gain: float,
               rate: int = SAMPLE_RATE, fade_ms: float = 1.5):
    """Записать сигнал в WAV (temp → replace, чтобы не было битых файлов)."""
    edge = int(rate * fade_ms / 1000) if fade_ms else 0
    samples = _fade(list(samples), edge)

    data = array.array('h', (
        int(max(-1.0, min(1.0, v * gain)) * 32767) for v in samples
    ))
    if sys.byteorder == 'big':
        data.byteswap()

    tmp = path.with_name(path.name + '.tmp')
    with wave.open(str(tmp), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(data.tobytes())
    os.replace(tmp, path)


def cached_wav(name: str, volume: int) -> Path | None:
    """Путь к готовому WAV нужной громкости (синтез при первом обращении)."""
    generator = _GENERATORS.get(name)
    if generator is None:
        return None

    rate = MUSIC_SAMPLE_RATE if name == 'music' else SAMPLE_RATE
    target = CACHE_DIR / f'{name}-v{SYNTH_VERSION}-g{int(volume)}.wav'
    if target.exists():
        return target

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _write_wav(target, generator(), int(volume) / 100,
                   rate=rate, fade_ms=0.0 if name == 'music' else 1.5)
    except (OSError, ValueError, wave.Error):
        return None
    return target


def cleanup_cache():
    """Удалить файлы прошлых версий синтеза."""
    try:
        if not CACHE_DIR.exists():
            return
        current = f'-v{SYNTH_VERSION}-'
        for p in CACHE_DIR.glob('*.wav'):
            if current not in p.name:
                try:
                    p.unlink()
                except OSError:
                    pass
    except OSError:
        pass


# --- Бэкенды воспроизведения ------------------------------------------------

class _WindowsBackend:
    """winsound для эффектов, MCI (winmm) для музыки."""
    supports_music = True

    def __init__(self):
        import ctypes
        import winsound
        self._winsound = winsound
        self._winmm = ctypes.windll.winmm
        self._buffer = ctypes.create_unicode_buffer(256)
        self._lock = threading.Lock()

    def play_effect(self, path: str):
        try:
            self._winsound.PlaySound(
                path,
                self._winsound.SND_FILENAME | self._winsound.SND_ASYNC | self._winsound.SND_NODEFAULT,
            )
        except RuntimeError:
            pass

    def mci(self, command: str) -> tuple[int, str]:
        with self._lock:
            code = self._winmm.mciSendStringW(command, self._buffer, 256, None)
            return code, self._buffer.value


def _create_backend():
    try:
        return _WindowsBackend()
    except (ImportError, AttributeError):
        return None  # звук недоступен


# --- Менеджер звука ----------------------------------------------------------

class SoundManager:
    """Единый менеджер эффектов и музыки (синглтон)."""
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._backend = _create_backend()
        self._enabled = True
        self._music_enabled = False
        self._volume = DEFAULT_VOLUME            # громкость эффектов (к волне)
        self._music_volume = DEFAULT_MUSIC_VOLUME  # громкость музыки (MCI)
        self._effect_cache: dict[tuple[str, int], Path] = {}

        self._music_thread = None
        self._music_stop = None
        # Для «умного распределения»: момент последнего эффекта (ducking)
        self._last_effect_at = 0.0
        self._music_state_lock = threading.Lock()

        cleanup_cache()

    # -- Эффекты --

    @property
    def available(self) -> bool:
        if self._backend is None:
            return False
        return bool(self._effect_path('move'))

    def _effect_path(self, name: str) -> Path | None:
        if name not in EFFECT_NAMES:
            return None
        key = (name, self._volume)
        cached = self._effect_cache.get(key)
        if cached is not None and cached.exists():
            return cached
        path = cached_wav(name, self._volume)
        if path is not None:
            self._effect_cache[key] = path
        return path

    def play(self, sound_name: str):
        """Воспроизвести эффект (не блокируя главный поток)."""
        if not self._enabled or self._backend is None:
            return
        path = self._effect_path(sound_name)
        if path is not None:
            with self._music_state_lock:
                self._last_effect_at = perf_counter()
            self._backend.play_effect(str(path))

    def toggle(self):
        if not self.available:
            return
        self._enabled = not self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled) and self.available

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def enabled_str(self) -> str:
        if not self.available:
            return "Недоступно"
        return "Вкл" if self._enabled else "Выкл"

    # -- Громкость --

    @property
    def volume(self) -> int:
        return self._volume

    def set_volume(self, volume: int):
        try:
            volume = int(volume)
        except (TypeError, ValueError):
            return
        volume = max(MIN_VOLUME, min(MAX_VOLUME, volume))
        if volume == self._volume:
            return
        self._volume = volume
        self._effect_cache.clear()
        # Пересинтезировать музыку при смене громкости эффектов (применяется к волне)

    def set_music_volume(self, volume: int):
        """Задать громкость музыки (0..100); изменение применит музыкальный поток."""
        try:
            volume = int(volume)
        except (TypeError, ValueError):
            return
        volume = max(MUSIC_MIN_VOLUME, min(MUSIC_MAX_VOLUME, volume))
        with self._music_state_lock:
            self._music_volume = volume

    # -- Музыка --

    @property
    def music_available(self) -> bool:
        if self._backend is None or not getattr(self._backend, 'supports_music', False):
            return False
        # Доступна либо пользовательская музыка (mp3), либо синтезированная тема
        return bool(list_music_files()) or 'music' in _GENERATORS

    @property
    def music_enabled(self) -> bool:
        return self._music_enabled

    @property
    def music_enabled_str(self) -> str:
        if not self.music_available:
            return "Недоступна"
        return "Вкл" if self._music_enabled else "Выкл"

    def set_music_enabled(self, enabled: bool):
        enabled = bool(enabled) and self.music_available
        if enabled == self._music_enabled:
            return
        self._music_enabled = enabled
        if enabled:
            self._start_music()
        else:
            self._stop_music()

    def toggle_music(self):
        self.set_music_enabled(not self._music_enabled)

    def _start_music(self):
        if self._music_thread is not None:
            return
        self._music_stop = threading.Event()
        self._music_thread = threading.Thread(
            target=self._music_worker,
            args=(self._music_stop, self._volume),
            daemon=True,
            name='chess-music',
        )
        self._music_thread.start()

    def _stop_music(self):
        stop = self._music_stop
        self._music_stop = None
        self._music_thread = None
        if stop is not None:
            stop.set()

    def _music_worker(self, stop: threading.Event, volume: int):
        """Фоновая музыка: плейлист mp3 из assets/music/ по кругу.

        Если пользовательских файлов нет — играет синтезированную фортепианную
        тему (WAV). Все команды MCI выполняются только в этом потоке: алиас
        принадлежит создавшему его потоку.
        """
        mci = getattr(self._backend, 'mci', None)
        if mci is None:
            self._music_enabled = False
            return

        alias = f'chess_music_{os.getpid()}'
        current_mci_volume = None

        def apply_music_volume():
            nonlocal current_mci_volume
            with self._music_state_lock:
                music_volume = self._music_volume
                last_effect_at = self._last_effect_at
            target = music_volume * MCI_VOLUME_MAX / MUSIC_MAX_VOLUME
            if last_effect_at and perf_counter() - last_effect_at < DUCK_SECONDS:
                target *= DUCK_FACTOR

            if current_mci_volume is None:
                current_mci_volume = target
            elif current_mci_volume < target:
                current_mci_volume = min(current_mci_volume + FADE_STEP, target)
            elif current_mci_volume > target:
                current_mci_volume = max(current_mci_volume - FADE_STEP, target)
            mci(f'setaudio {alias} volume to {int(current_mci_volume)}')

        def open_play(path: Path, mpeg: bool) -> bool:
            """Переоткрыть алиас на новый файл и запустить воспроизведение."""
            mci(f'close {alias}')
            type_part = ' type mpegvideo' if mpeg else ' type waveaudio'
            code, _ = mci(f'open "{path}"{type_part} alias {alias}')
            if code != 0:
                return False
            apply_music_volume()
            return mci(f'play {alias} from 0')[0] == 0

        playlist = list_music_files()
        if playlist:
            # Пользовательская музыка: прокручиваем треки по кругу
            idx = 0
            if not open_play(playlist[idx], mpeg=True):
                self._music_enabled = False
                return
            while not stop.wait(MUSIC_POLL):
                apply_music_volume()
                code, mode = mci(f'status {alias} mode')
                if code != 0:
                    break
                if mode.strip() == 'stopped':
                    idx = (idx + 1) % len(playlist)
                    if not open_play(playlist[idx], mpeg=True):
                        break
            mci(f'stop {alias}')
            mci(f'close {alias}')
            return

        # Резерв: синтезированная фортепианная тема (WAV, зацикленный вручную)
        path = cached_wav('music', volume)
        if path is None or not open_play(path, mpeg=False):
            self._music_enabled = False
            return
        while not stop.wait(MUSIC_POLL):
            apply_music_volume()
            code, mode = mci(f'status {alias} mode')
            if code != 0:
                break
            if mode.strip() == 'stopped':
                if not open_play(path, mpeg=False):
                    break
