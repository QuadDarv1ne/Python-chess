"""Smoke test for effect-driven music ducking."""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Консоль Windows по умолчанию в cp1251 — переключаем вывод в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8')

from chess_game import audio


class FakeBackend:
    def __init__(self):
        self.commands = []
        self.effects = []

    def mci(self, command):
        self.commands.append(command)
        if command.startswith('status '):
            return 0, 'playing'
        return 0, ''

    def play_effect(self, path):
        self.effects.append(path)


class FakeStop:
    def __init__(self, manager, clock):
        self.manager = manager
        self.clock = clock
        self.waits = 0

    def wait(self, _timeout):
        self.waits += 1
        if self.waits == 1:
            self.manager.play('move')
            return False
        if self.waits == 3:
            self.clock[0] += audio.DUCK_SECONDS + 0.01
            return False
        return self.waits >= 4


class FakeTrackStop:
    def __init__(self, manager):
        self.manager = manager
        self.tracks = []
        self.waits = 0

    def wait(self, _timeout):
        self.waits += 1
        self.tracks.append(self.manager.current_track)
        if self.waits == 1:
            self.manager.next_track()
            return False
        if self.waits == 2:
            self.manager.previous_track()
            return False
        return self.waits >= 3


class ImmediateStop:
    def __init__(self, manager):
        self.manager = manager
        self.track = None

    def wait(self, _timeout):
        self.track = self.manager.current_track
        return True


def test_effect_ducks_and_restores_music():
    manager = audio.SoundManager()
    backend = FakeBackend()
    manager._backend = backend
    manager._enabled = True
    manager._effect_path = lambda _name: Path('effect.wav')
    manager._music_thread = object()

    manager.set_music_volume(70)
    assert manager._music_volume == 70
    assert backend.commands == []
    manager._music_thread = None

    clock = [100.0]
    with patch.object(audio, 'perf_counter', side_effect=lambda: clock[0]):
        with patch.object(audio, 'list_music_files', return_value=[Path('track.mp3')]):
            manager._music_worker(FakeStop(manager, clock), 50, 'chess_music_test')

    levels = [
        int(command.rsplit(' ', 1)[1])
        for command in backend.commands
        if command.startswith('setaudio ')
    ]
    assert backend.effects == ['effect.wav']
    assert levels[:4] == [700, 645, 590, 645], levels
    print('[PASS] music fades down on an effect and restores afterward')


def test_playlist_navigation_and_shuffle():
    manager = audio.SoundManager()
    backend = FakeBackend()
    manager._backend = backend
    manager._music_enabled = True
    manager._music_thread = None
    manager.set_shuffle_music(True)
    manager._music_rng.shuffle = lambda paths: paths.reverse()
    stop = FakeTrackStop(manager)

    with patch.object(
        audio, 'list_music_files',
        return_value=[Path('a.mp3'), Path('b.mp3'), Path('c.mp3')],
    ):
        manager._music_worker(stop, 50, 'chess_music_test')

    opened = [
        command.split('"', 2)[1]
        for command in backend.commands
        if command.startswith('open "')
    ]
    assert stop.tracks == ['c', 'b', 'c'], stop.tracks
    assert opened == ['c.mp3', 'b.mp3', 'c.mp3'], opened
    assert manager.current_track is None
    print('[PASS] shuffle order and previous/next navigation')


def test_synthesized_track_name():
    manager = audio.SoundManager()
    backend = FakeBackend()
    manager._backend = backend
    stop = ImmediateStop(manager)

    with patch.object(audio, 'list_music_files', return_value=[]):
        with patch.object(audio, 'cached_wav', return_value=Path('fallback.wav')):
            manager._music_worker(stop, 50, 'chess_music_test')

    assert stop.track == 'Фортепианная тема', stop.track
    assert manager.current_track is None
    print('[PASS] synthesized fallback has a readable current-track title')


def test_synthesized_audio_quality():
    click = audio._click(0.1, 280, 0.4, seed=1)
    differences = [click[i] - click[i - 1] for i in range(1, len(click))]
    roughness = (sum(value * value for value in differences) / len(differences)) ** 0.5
    assert roughness < 0.05, roughness

    for name in audio.EFFECT_NAMES:
        peak = max(abs(value) for value in audio._GENERATORS[name]())
        assert 0.25 <= peak <= 0.35, (name, peak)

    loop = audio._fade(
        audio._piano_loop(),
        int(audio.MUSIC_SAMPLE_RATE * 0.03),
    )
    edge_slope = abs((loop[1] - loop[0]) - (loop[-1] - loop[-2]))
    assert edge_slope < 1e-4, edge_slope
    print('[PASS] filtered effects, safe peaks and smooth piano loop edges')


def test_custom_sfx_bit_depths():
    """Пользовательский WAV читается при 8/16/32-бит и любом числе каналов.

    Раньше 8-битные WAV (беззнаковые, длина не кратна 4) не загружались:
    array('i').frombytes() кидал ValueError, и эффект молча отключался.
    """
    import struct
    import tempfile
    import wave

    tmp = Path(tempfile.mkdtemp())
    saved_dir = audio._CUSTOM_SFX_DIR
    audio._CUSTOM_SFX_DIR = tmp
    try:
        def write(name, channels, sampwidth, payload):
            with wave.open(str(tmp / f'{name}.wav'), 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sampwidth)
                wf.setframerate(8000)
                wf.writeframes(payload)

        # 8-бит моно, 5 фреймов (нечётная длина — раньше падало)
        write('move', 1, 1, bytes([128, 200, 100, 30, 250]))
        # 8-бит стерео, 3 фрейма
        write('capture', 2, 1, bytes([128, 128, 200, 150, 100, 80]))
        # 16-бит моно
        write('promote', 1, 2, struct.pack('<5h', 0, 1000, -1000, 500, -500))

        for name in ('move', 'capture', 'promote'):
            samples = audio._custom_effect_samples(name)
            assert samples, f'{name}: WAV не прочитан'
            assert all(-1.0 <= v <= 1.0 for v in samples), name
            assert max(abs(v) for v in samples) > 0.0, f'{name}: тишина'
        print('[PASS] custom WAV: 8/16-бит, моно/стерео читаются')
    finally:
        audio._CUSTOM_SFX_DIR = saved_dir


if __name__ == '__main__':
    test_effect_ducks_and_restores_music()
    test_playlist_navigation_and_shuffle()
    test_synthesized_track_name()
    test_synthesized_audio_quality()
    test_custom_sfx_bit_depths()
