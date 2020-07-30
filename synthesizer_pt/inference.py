import torch
from synthesizer_pt.utils import hparams as hp
from synthesizer_pt.utils.text.symbols import symbols
from synthesizer_pt.utils.paths import Paths
from synthesizer_pt.models.tacotron import Tacotron
from synthesizer_pt.utils.text import text_to_sequence
from synthesizer_pt.utils.display import save_attention, simple_table

from synthesizer_pt import audio
from pathlib import Path
from typing import Union, List
import numpy as np
import librosa

hp.configure("synthesizer_pt/hparams.py")

class Synthesizer:
    sample_rate = hp.sample_rate
    
    def __init__(self, model_fpath: Path, verbose=True, low_mem=False):
        """
        Creates a synthesizer ready for inference. The actual model isn't loaded in memory until
        needed or until load() is called.
        
        :param model_fpath: path to the trained model file
        """
        self.verbose = verbose
        self.model_fpath = model_fpath
 
        # Check for GPU
        if torch.cuda.is_available():
            device = torch.device('cuda')
        else:
            device = torch.device('cpu')
        if self.verbose:
            print('Synthesizer using device:', device)
        
        # Instantiate Tacotron Model
        self._model = Tacotron(embed_dims=hp.tts_embed_dims,
                               num_chars=len(symbols),
                               encoder_dims=hp.tts_encoder_dims,
                               decoder_dims=hp.tts_decoder_dims + hp.tts_speaker_embedding_size,
                               n_mels=hp.num_mels,
                               fft_bins=hp.num_mels,
                               postnet_dims=hp.tts_postnet_dims,
                               encoder_K=hp.tts_encoder_K,
                               lstm_dims=hp.tts_lstm_dims,
                               postnet_K=hp.tts_postnet_K,
                               num_highways=hp.tts_num_highways,
                               dropout=hp.tts_dropout,
                               stop_threshold=hp.tts_stop_threshold).to(device)    
        self._model.load(model_fpath)
        self._model.eval()

        if verbose:
            print("Loaded synthesizer \"%s\" trained to step %d" % (model_fpath.name, self._model.state_dict()["step"]))
     
    def is_loaded(self):
        """
        Whether the model is loaded in GPU memory.
        """
        return self._model is not None
    
    def load(self):
        """
        Effectively loads the model to GPU memory given the weights file that was passed in the
        constructor.
        """
        if self._low_mem:
            raise Exception("Cannot load the synthesizer permanently in low mem mode")

        # Check for GPU
        if torch.cuda.is_available():
            device = torch.device('cuda')
        else:
            device = torch.device('cpu')
        print('Using device:', device)
        
        # Instantiate Tacotron Model
        self._model = Tacotron(embed_dims=hp.tts_embed_dims,
                               num_chars=len(symbols),
                               encoder_dims=hp.tts_encoder_dims,
                               decoder_dims=hp.tts_decoder_dims + hp.tts_speaker_embedding_dims,
                               n_mels=hp.num_mels,
                               fft_bins=hp.num_mels,
                               postnet_dims=hp.tts_postnet_dims,
                               encoder_K=hp.tts_encoder_K,
                               lstm_dims=hp.tts_lstm_dims,
                               postnet_K=hp.tts_postnet_K,
                               num_highways=hp.tts_num_highways,
                               dropout=hp.tts_dropout,
                               stop_threshold=hp.tts_stop_threshold).to(device)    

        # Load model
        self._model.load(self.model_path)

    def synthesize_spectrograms(self, texts: List[str],
                                embeddings: Union[np.ndarray, List[np.ndarray]],
                                return_alignments=False):
        """
        Synthesizes mel spectrograms from texts and speaker embeddings.

        :param texts: a list of N text prompts to/ be synthesized
        :param embeddings: a numpy array or list of speaker embeddings of shape (N, 256) 
        :param return_alignments: if True, a matrix representing the alignments between the 
        characters
        and each decoder output step will be returned for each spectrogram
        :return: a list of N melspectrograms as numpy arrays of shape (80, Mi), where Mi is the 
        sequence length of spectrogram i, and possibly the alignments.
        """
        if self._low_mem:
            # Low memory inference mode: load the model upon every request. The model has to be 
            # loaded in a separate process to be able to release GPU memory (a simple workaround 
            # to tensorflow's intricacies) - TODO: Reimplement for pytorch if needed
            raise NotImplementedError
        else:
            # Usual inference mode: load the model on the first request and keep it loaded.
            if not self.is_loaded():
                self.load()

            inputs = [text_to_sequence(text.strip(), hp.tts_cleaner_names) for text in texts]
            if not isinstance(embeddings, list):
                embeddings = [embeddings]

            tts_k = self._model.get_step() // 1000

            simple_table([('Tacotron', str(tts_k) + 'k'),
                        ('r', tts_model.r)])

            specs = []
            for i, x in enumerate(inputs, 1):

                print(f'\n| Generating {i}/{len(inputs)}')
                _, m, attention = self._model.generate(x, speaker_embedding[i-1])
                # Fix mel spectrogram scaling to be from -1 to 1
                m = m / 4
                np.clip(m, -1, 1, out=m)
                specs.append(m)

            print('\n\nDone.\n')
            return (specs, alignments) if return_alignments else specs

    @staticmethod
    def load_preprocess_wav(fpath):
        """
        Loads and preprocesses an audio file under the same conditions the audio files were used to
        train the synthesizer. 
        """
        wav = librosa.load(str(fpath), hparams.sample_rate)[0]
        if hparams.rescale:
            wav = wav / np.abs(wav).max() * hparams.rescaling_max
        return wav

    @staticmethod
    def make_spectrogram(fpath_or_wav: Union[str, Path, np.ndarray]):
        """
        Creates a mel spectrogram from an audio file in the same manner as the mel spectrograms that
        were fed to the synthesizer when training.
        """
        if isinstance(fpath_or_wav, str) or isinstance(fpath_or_wav, Path):
            wav = Synthesizer.load_preprocess_wav(fpath_or_wav)
        else:
            wav = fpath_or_wav
        
        mel_spectrogram = audio.melspectrogram(wav, hparams).astype(np.float32)
        return mel_spectrogram
    
    @staticmethod
    def griffin_lim(mel):
        """
        Inverts a mel spectrogram using Griffin-Lim. The mel spectrogram is expected to have been built
        with the same parameters present in hparams.py.
        """
        return audio.inv_mel_spectrogram(mel, hparams)
