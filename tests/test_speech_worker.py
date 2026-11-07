"""Verify concrete IndexTTS controls without importing Torch or using the GPU."""
from array import array
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import wave


path=Path(__file__).parents[1]/'integrations/comfyui_manju_speech/worker.py'
spec=importlib.util.spec_from_file_location('manju_speech_worker_under_test',path)
worker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_quality_reaches_actual_cfm_step_argument():
    calls=[]
    def original(*args,**kwargs):calls.append((args,kwargs));return 'decoded'
    engine=SimpleNamespace(s2mel=SimpleNamespace(models={'cfm':SimpleNamespace(inference=original)}))
    assert worker.configure_quality(engine,'studio')==40
    assert engine.s2mel.models['cfm'].inference('mu','lens','prompt','style',None,25,inference_cfg_rate=.7)=='decoded'
    assert calls[0][0][5]==40 and calls[0][1]['inference_cfg_rate']==.7


def test_emotion_modes_map_to_real_indextts_arguments():
    base={'reference':'voice.wav','language':'zh','emotion':'sad','intensity':.35,'speed':1,'temperature':.75,'interval_silence':400}
    preset=worker.synthesis_arguments(base)
    assert preset['emo_vector']==[0,0,.35,0,0,0,0,0] and preset['emo_alpha']==1
    audio=worker.synthesis_arguments({**base,'emotion_reference':'emotion.wav'})
    assert audio['emo_audio_prompt']=='emotion.wav' and audio['emo_vector'] is None and audio['emo_alpha']==.35
    text=worker.synthesis_arguments({**base,'use_emo_text':True,'emo_text':'温暖、克制'})
    assert text['use_emo_text'] is True and text['emo_text']=='温暖、克制' and text['emo_vector'] is None
    assert text['spk_audio_prompt']=='voice.wav' and text['temperature']==.75 and text['duration_factor']==1


def test_explicit_sentence_split_preserves_phonemes_and_decimal_numbers():
    assert worker.sentence_segments('妈，<妈妈|MA1 MA5>。我回来了！\n灯还亮着。')==['妈，<妈妈|MA1 MA5>。','我回来了！','灯还亮着。']
    assert worker.sentence_segments('The value is 1.5. <minute|M IH1 . N AH0 T>.')==['The value is 1.5.','<minute|M IH1 . N AH0 T>.']


def test_sentence_pause_is_real_pcm_silence_and_preserves_dynamic_range(tmp_path):
    paths=[]
    for index,amplitude in enumerate((1200,6200)):
        path=tmp_path/f'{index}.wav';paths.append(path)
        with wave.open(str(path),'wb') as output:
            output.setparams((1,2,8000,0,'NONE','not compressed'))
            output.writeframes(array('h',[amplitude]*400).tobytes())
    combined=tmp_path/'joined.wav'
    worker.concatenate_sentences(paths,combined,125)
    with wave.open(str(combined),'rb') as result:
        assert result.getnframes()==1800
        samples=array('h',result.readframes(result.getnframes()))
    assert list(samples[:400])==[1200]*400
    assert list(samples[400:1400])==[0]*1000
    assert list(samples[1400:])==[6200]*400
