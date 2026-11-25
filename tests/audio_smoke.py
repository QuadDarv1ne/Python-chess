"""Smoke test for effect-driven music ducking."""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


if __name__ == '__main__':
    test_effect_ducks_and_restores_music()
    test_playlist_navigation_and_shuffle()
    test_synthesized_track_name()
    test_synthesized_audio_quality()
