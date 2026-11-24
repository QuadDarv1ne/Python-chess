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
            manager._music_worker(FakeStop(manager, clock), 50)

    levels = [
        int(command.rsplit(' ', 1)[1])
        for command in backend.commands
        if command.startswith('setaudio ')
    ]
    assert backend.effects == ['effect.wav']
    assert levels[:4] == [700, 645, 590, 645], levels
    print('[PASS] music fades down on an effect and restores afterward')


if __name__ == '__main__':
    test_effect_ducks_and_restores_music()
