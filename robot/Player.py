# -*- coding: utf-8 -*-
import subprocess
import os
import platform
import signal
from . import utils
import _thread as thread
from robot import logging
from ctypes import CFUNCTYPE, c_char_p, c_int, cdll
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def py_error_handler(filename, line, function, err, fmt):
    pass


ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)

c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)


@contextmanager
def no_alsa_error():
    try:
        asound = cdll.LoadLibrary("libasound.so")
        asound.snd_lib_error_set_handler(c_error_handler)
        yield
        asound.snd_lib_error_set_handler(None)
    except:
        yield
        pass


def play(fname, onCompleted=None, wait=False):
    player = getPlayerByFileName(fname)
    player.play(fname, onCompleted=onCompleted, wait=wait)


def getPlayerByFileName(fname):
    foo, ext = os.path.splitext(fname)
    if ext in [".mp3", ".wav"]:
        return SoxPlayer()


class AbstractPlayer(object):
    def __init__(self, **kwargs):
        super(AbstractPlayer, self).__init__()

    def play(self):
        pass

    def play_block(self):
        pass

    def stop(self):
        pass

    def is_playing(self):
        return False


class SoxPlayer(AbstractPlayer):
    SLUG = "SoxPlayer"

    def __init__(self, **kwargs):
        super(SoxPlayer, self).__init__(**kwargs)
        self.playing = False
        self.proc = None
        self.delete = False
        self.onCompleteds = []

    def doPlay(self):
        system = platform.system()
        if system == "Darwin":
            cmd = ["afplay", str(self.src)]
        else:
            cmd = ["play", str(self.src)]
        logger.debug("Executing %s", " ".join(cmd))
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self.playing = True
        self.proc.wait()
        self.playing = False
        if self.delete:
            utils.check_and_delete(self.src)
        logger.debug("play completed")
        if self.proc and self.proc.returncode == 0:
            for onCompleted in self.onCompleteds:
                onCompleted and onCompleted()

    def play(self, src, delete=False, onCompleted=None, wait=False):
        if src and (os.path.exists(src) or src.startswith("http")):
            self.src = src
            self.delete = delete
            onCompleted and self.onCompleteds.append(onCompleted)
            if not wait:
                thread.start_new_thread(self.doPlay, ())
            else:
                self.doPlay()
        else:
            logger.critical(f"path not exists: {src}", stack_info=True)

    def preappendCompleted(self, onCompleted):
        onCompleted and self.onCompleteds.insert(0, onCompleted)

    def appendOnCompleted(self, onCompleted):
        onCompleted and self.onCompleteds.append(onCompleted)

    def play_block(self):
        self.run()

    def stop(self):
        if self.proc:
            self.onCompleteds = []
            self.proc.terminate()
            self.proc.kill()
            self.proc = None
            if self.delete:
                utils.check_and_delete(self.src)

    def is_playing(self):
        return self.playing


class MusicPlayer(SoxPlayer):
    """
    给音乐播放器插件使用的，
    在 SOXPlayer 的基础上增加了列表的支持，
    并支持暂停和恢复播放
    """

    SLUG = "MusicPlayer"

    def __init__(self, playlist, plugin, **kwargs):
        super(MusicPlayer, self).__init__(**kwargs)
        self.playlist = playlist
        self.plugin = plugin
        self.idx = 0
        self.pausing = False

    def update_playlist(self, playlist):
        super().stop()
        self.playlist = playlist
        self.idx = 0
        self.play()

    def play(self):
        logger.debug("MusicPlayer play")
        path = self.playlist[self.idx]
        super().stop()
        super().play(path, False, self.next)

    def next(self):
        logger.debug("MusicPlayer next")
        super().stop()
        self.idx = (self.idx + 1) % len(self.playlist)
        self.play()

    def prev(self):
        logger.debug("MusicPlayer prev")
        super().stop()
        self.idx = (self.idx - 1) % len(self.playlist)
        self.play()

    def pause(self):
        logger.debug("MusicPlayer pause")
        self.pausing = True
        if self.proc:
            os.kill(self.proc.pid, signal.SIGSTOP)

    def stop(self):
        if self.proc:
            logger.debug(f"MusicPlayer stop {self.proc.pid}")
            self.onCompleteds = []
            os.kill(self.proc.pid, signal.SIGSTOP)
            self.proc.terminate()
            self.proc.kill()
            self.proc = None

    def resume(self):
        logger.debug("MusicPlayer resume")
        self.pausing = False
        self.onCompleteds = [self.next]
        if self.proc:
            os.kill(self.proc.pid, signal.SIGCONT)

    def is_playing(self):
        return self.playing

    def is_pausing(self):
        return self.pausing

    def turnUp(self):
        system = platform.system()
        if system == "Darwin":
            res = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                shell=False,
                capture_output=True,
                universal_newlines=True,
            )
            volume = int(res.stdout.strip())
            volume += 20
            if volume >= 100:
                volume = 100
                self.plugin.say("音量已经最大啦", wait=True)
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {volume}"]
            )
        elif system == "Linux":
            res = subprocess.run(
                ["amixer sget Master | grep 'Mono:' | awk -F'[][]' '{ print $2 }'"],
                shell=True,
                capture_output=True,
                universal_newlines=True,
            )
            if res.stdout != "" and res.stdout.strip().endswith("%"):
                volume = int(res.stdout.strip().replace("%", ""))
                volume += 20
                if volume >= 100:
                    volume = 100
                    self.plugin.say("音量已经最大啦", wait=True)
                subprocess.run(["amixer", "set", "Master", f"{volume}%"])
            else:
                subprocess.run(["amixer", "set", "Master", "20%+"])
        else:
            self.plugin.say("当前系统不支持调节音量", wait=True)
        self.resume()

    def turnDown(self):
        system = platform.system()
        if system == "Darwin":
            res = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                shell=False,
                capture_output=True,
                universal_newlines=True,
            )
            volume = int(res.stdout.strip())
            volume -= 20
            if volume <= 20:
                volume = 20
                self.plugin.say("音量已经很小啦", wait=True)
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {volume}"]
            )
        elif system == "Linux":
            res = subprocess.run(
                ["amixer sget Master | grep 'Mono:' | awk -F'[][]' '{ print $2 }'"],
                shell=True,
                capture_output=True,
                universal_newlines=True,
            )
            if res.stdout != "" and res.stdout.endswith("%"):
                volume = int(res.stdout.replace("%", "").strip())
                volume -= 20
                if volume <= 20:
                    volume = 20
                    self.plugin.say("音量已经最小啦", wait=True)
                subprocess.run(["amixer", "set", "Master", f"{volume}%"])
            else:
                subprocess.run(["amixer", "set", "Master", "20%-"])
        else:
            self.plugin.say("当前系统不支持调节音量", wait=True)
        self.resume()
