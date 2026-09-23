import numpy as np
import pytest
from pydantic import ValidationError
from server.audio import AudioWindow
from server.noise import ClassificationFilter, classify_views, processing_status
from server.app import Settings
from server.runtime import Runtime
from server.recording import Recorder


def test_lowcut_attenuates_rumble_and_keeps_higher_frequency_signal():
    t = np.arange(32000) / 16000
    x = 0.1 * np.sin(2 * np.pi * 20 * t) + 0.05 * np.sin(2 * np.pi * 1000 * t)
    original = x.copy()
    y = ClassificationFilter().process(x)
    # Ignore startup transient; compare actual tone amplitudes after one second.
    amplitude = lambda a, hz: abs(2 * np.mean(a[16000:] * np.exp(-2j * np.pi * hz * t[16000:])))
    assert amplitude(y, 20) / amplitude(x, 20) < 0.08
    assert amplitude(y, 1000) / amplitude(x, 1000) > 0.99
    assert np.array_equal(x, original)


def test_filter_state_is_continuous_and_explicitly_resettable():
    x = np.random.default_rng(4).normal(0, 0.1, 16000)
    whole = ClassificationFilter().process(x)
    filt = ClassificationFilter()
    chunks = np.concatenate([filt.process(chunk) for chunk in np.array_split(x, 20)])
    assert np.allclose(chunks, whole, atol=1e-7)
    filt.reset()
    assert np.array_equal(filt.process(x), whole)


def test_processing_leaves_reference_pcm_and_classification_window_untouched():
    x = np.random.default_rng(5).normal(0, 0.1, (1600, 2)).astype(np.float32)
    before = x.copy()
    reference, experiment = AudioWindow(), AudioWindow()
    for i in range(10):
        reference.append(x, 16000, "camera", i * 0.1)
        experiment.append(x, 16000, "camera", i * 0.1, "lowcut_80hz")
    assert np.array_equal(x, before)
    assert np.array_equal(experiment.samples, reference.samples)
    assert experiment.processed_samples.shape == experiment.samples.shape
    assert not np.array_equal(experiment.samples, experiment.processed_samples)
    experiment.append(x, 16000, "camera", 1, "off")
    assert len(experiment.samples) == 1600 and len(experiment.processed_samples) == 0
    experiment.append(x, 16000, "camera", 3, "lowcut_80hz")
    fresh = AudioWindow()
    fresh.append(x, 16000, "camera", 3, "lowcut_80hz")
    assert np.array_equal(experiment.processed_samples, fresh.processed_samples)


def test_classification_preserves_baseline_when_filtered_view_suppresses_horn():
    class Model:
        def infer(self, x):
            return {"horn": 0.9, "bell": 0.1} if x[0] == 0 else {"horn": 0.1, "bell": 0.8}

    result = classify_views(Model(), np.zeros(1), np.ones(1))
    assert result["scores"] == {"horn": 0.9, "bell": 0.8}
    assert result["reference_scores"]["horn"] == 0.9
    assert result["processed_scores"]["horn"] == 0.1


def test_extra_view_failure_falls_back_to_baseline():
    class Model:
        def infer(self, x):
            if x[0]:
                raise RuntimeError("extra inference failed")
            return {"horn": 0.8}

    result = classify_views(Model(), np.zeros(1), np.ones(1))
    assert result["scores"] == {"horn": 0.8} and result["processed_scores"] is None
    assert result["error"] == "extra inference failed"


def test_exact_camera_profile_is_separate_from_local_processing():
    cfg = Settings(audio_profile="wind_reduction_strong", camera_microphone="builtin")
    state = processing_status(cfg.model_dump(), "camera")
    assert state["camera_profile_label"] == "智能降风噪-强"
    assert state["local_mode"] == "off" and not state["baseline_guard"]
    assert not state["localization_uses_local_filter"]
    assert not processing_status(cfg.model_dump(), "microphone")["camera_profile_applies"]
    with pytest.raises(ValidationError):
        Settings(audio_preprocessing="strong")


def test_replay_uses_recorded_audio_settings_and_old_recordings_stay_unknown():
    r = Runtime()
    r.config.update(audio_profile="wind_reduction_strong", audio_preprocessing="lowcut_80hz")
    assert r.audio_config["audio_profile"] == "wind_reduction_strong"
    r.mode = "replay"
    state = processing_status(r.audio_config, "camera")
    assert state["camera_profile"] == "unknown" and state["local_mode"] == "off"
    r.replay_audio_config = dict(audio_profile="stereo", audio_preprocessing="lowcut_80hz")
    assert r.audio_config["audio_profile"] == "stereo"


def test_runtime_experiment_keeps_recorded_pcm_and_publishes_both_views(tmp_path):
    import asyncio
    import time

    class Model:
        def __init__(self):
            self.inputs = []

        def infer(self, x):
            self.inputs.append(x.copy())
            return dict(horn=0.9, siren=0.0, bell=0.0, shout=0.0, speech=0.0)

    async def run():
        r = Runtime()
        r.mode = "live"
        r.config["audio_preprocessing"] = "lowcut_80hz"
        r.classifier = Model()
        r.recorder = Recorder(tmp_path)
        session = r.recorder.start({"config": r.config})
        t = np.arange(16000) / 16000
        pcm = np.column_stack([0.1 * np.sin(2 * np.pi * 20 * t)] * 2).astype(np.float32)
        r.audio_queue.put_nowait(
            (pcm.copy(), 16000, "camera", time.perf_counter(), r.generation, None)
        )
        worker = asyncio.create_task(r.audio_worker())
        try:
            for _ in range(100):
                if r.audio_comparison:
                    break
                await asyncio.sleep(0.01)
            assert r.audio_comparison["processed_scores"]["horn"] == 0.9
            assert len(r.classifier.inputs) == 2
            assert (
                np.sqrt(np.mean(r.classifier.inputs[1] ** 2))
                < np.sqrt(np.mean(r.classifier.inputs[0] ** 2)) * 0.1
            )
            assert r.signal.snapshot(time.perf_counter())["channel_rms"][0] > 0.06
            assert np.array_equal(np.load(tmp_path / session / "00000001.npy"), pcm)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            r.recorder.stop()

    asyncio.run(run())
