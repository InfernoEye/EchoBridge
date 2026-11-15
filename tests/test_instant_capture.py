"""Exercise Recorder with a fake PortAudio stream (no physical microphone)."""
import ast
from pathlib import Path
from types import SimpleNamespace
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_recorder():
    code = (ROOT / 'echobridge_runtime.py').read_text(encoding='utf-8')
    tree = ast.parse(code)
    recorder = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Recorder')
    module = ast.Module(body=[recorder], type_ignores=[])
    class FakeStream:
        def __init__(self, cb, started):
            self.cb, self.active = cb, started
            self.start_calls = 0
            self.stop_calls = 0
            self.close_calls = 0
        def start(self):
            self.active = True
            self.start_calls += 1
        def stop(self):
            self.active = False
            self.stop_calls += 1
        def abort(self):
            self.active = False
        def close(self):
            self.close_calls += 1
    opened=[]
    def open_stream(sd, index, device, callback, start=True):
        s=FakeStream(callback, start)
        opened.append(s)
        return s, 1, 16000
    env = {
        'open_capture_stream': open_stream,
        'resolve_input': lambda sd, selected: (0, {'name':'Fake microphone'}),
        'sd': object(),
        'np': np,
        'tempfile': __import__('tempfile'),
        'os': __import__('os'),
        'wave': __import__('wave'),
        'pcm16_from_float': lambda x: np.asarray(x[:,0]*32767, dtype=np.int16),
        'validate_pcm16': lambda audio, hz: SimpleNamespace(seconds=len(audio)/hz),
    }
    exec(compile(module, str(ROOT/'echobridge_runtime.py'), 'exec'), env)
    return env['Recorder'], opened


def test_instant_mode_keeps_stream_running_and_discard_idle_audio():
    Recorder, streams = load_recorder()
    r=Recorder(instant_capture=True)
    r.prepare('default')
    stream=streams[0]
    assert stream.active
    assert r.frames == []
    stream.cb(np.ones((800,1), dtype='float32'), 800, None, None)
    assert r.frames == [] and r.samples == 0
    r.start('default')
    assert stream.start_calls == 0, 'F8 must not call driver start in instant mode'
    stream.cb(np.ones((800,1),dtype='float32'),800,None,None)
    assert r.samples == 800
    r.recording=False
    stream.cb(np.ones((800,1),dtype='float32'),800,None,None)
    assert r.samples == 800, 'must not save audio after key release'
    r.release()
    assert stream.close_calls == 1


def test_normal_mode_keeps_prepared_stream_stopped():
    Recorder, streams = load_recorder()
    r=Recorder(instant_capture=False)
    r.prepare('default')
    stream=streams[0]
    assert not stream.active
    r.start('default')
    assert stream.start_calls == 1
    r.recording=False
    r.release()
    assert stream.close_calls == 1


def test_recording_path_precedes_heavy_ui_and_model_checks():
    code=(ROOT/'echobridge_runtime.py').read_text(encoding='utf-8')
    tree=ast.parse(code)
    runtime=next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='EchoBridgeRuntime')
    method=next(n for n in runtime.body if isinstance(n, ast.FunctionDef) and n.name=='on_pressed')
    s=ast.get_source_segment(code, method)
    assert s.index('self.recorder.start(') < s.index('ready_error()')
    listening_calls = [
        n for n in ast.walk(method)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "set_status"
        and any(
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and "listening" in arg.value.lower()
            for arg in n.args
        )
    ]

    recording_calls = [
        n for n in ast.walk(method)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "start"
        and isinstance(n.func.value, ast.Attribute)
        and n.func.value.attr == "recorder"
    ]

    assert recording_calls and listening_calls
    assert min(n.lineno for n in recording_calls) < min(
        n.lineno for n in listening_calls
    )
    assert s.index('self.recorder.start(') < s.index('self.start_preload()')
