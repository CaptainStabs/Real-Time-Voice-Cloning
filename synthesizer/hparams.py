import ast
import pprint

class HParams(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def __repr__(self):
        return pprint.pformat(self.__dict__)

    def parse(self, string):
        # Overrides hparams from a comma-separated string of name=value pairs
        if len(string) > 0:
            overrides = [s.split("=") for s in string.split(",")]
            keys, values = zip(*overrides)
            for k in keys:
                self.__dict__[k] = ast.literal_eval(values[keys.index(k)])

        return self


hparams = HParams(
        # DSP --------------------------------------------------------------------------------------------------------------#

        # Settings for all models
        sample_rate = 16000,
        n_fft = 800,
        num_mels = 80,
        hop_size = 200,                      # For 16000 Hz, 200 = 12.5ms - in line with Tacotron 2 paper
        win_size = 800,                      # For 16000 Hz, 800 = 50ms - same reason as above
        fmin = 55,
        min_level_db = -100,
        ref_level_db = 20,
        max_abs_value = 4.,                  # Gradient explodes if too big, premature convergence if too small.
        preemphasis = 0.97,                  # filter coefficient to use if preemphasize is True
        preemphasize = True,


        # TACOTRON/TTS -----------------------------------------------------------------------------------------------------#


        # Model Hparams
        tts_embed_dims = 512,                # embedding dimension for the graphemes/phoneme inputs
        tts_encoder_dims = 128,
        tts_decoder_dims = 256,
        tts_postnet_dims = 128,
        tts_encoder_K = 16,
        tts_lstm_dims = 1024,
        tts_postnet_K = 8,
        tts_num_highways = 4,
        tts_dropout = 0.5,
        tts_cleaner_names = ["english_cleaners"],
        tts_stop_threshold = -3.4,           # Value below which audio generation ends.
                                             # For example, for a range of [-4, 4], this
                                             # will terminate the sequence at the first
                                             # frame that has all values < -3.4

        # Training
        tts_schedule = [(7,  1e-3,  20_000,  16),   # progressive training schedule
                        (6,  3e-4,  50_000,  16),   # (r, lr, step, batch_size)
                        (5,  3e-4, 100_000,  10),
                        (4,  3e-4, 200_000,  8),
                        (3,  3e-4, 300_000,  6),
                        (2,  3e-4, 500_000,  6)],

        tts_clip_grad_norm = 1.0,            # clips the gradient norm to prevent explosion - set to None if not needed
        tts_eval_interval = 2000,            # Number of steps between model evaluation (sample generation)
                                             # Set to -1 to generate after completing epoch, or 0 to disable

        tts_eval_num_samples = 1,            # Makes this number of samples

        # Data Preprocessing
        max_mel_frames = 900,                # if you have a couple of extremely long spectrograms you might want to use this
        rescale = True,
        rescaling_max = 0.9,
        synthesis_batch_size = 32,           # For vocoder preprocessing only.
                                             # Batch size can be larger that of training
                                             # since not keeping track of gradients

        # Mel visualization and Griffin-Lim
        signal_normalization = True,
        power = 1.5,
        griffin_lim_iters = 60,
        # ------------------------------------------------------------------------------------------------------------------#

        ### SV2TTS
        speaker_embedding_size = 256,            # embedding dimension for the speaker embedding
        silence_min_duration_split = 0.4,        # Duration in seconds of a silence for an utterance to be split
        utterance_min_duration = 1.6,            # Duration in seconds below which utterances are discarded

        ### Audio processing options
        fmax = 7600,                             # Set to sample_rate // 2
        allow_clipping_in_normalization = True,  # Used when signal_normalization = True
        clip_mels_length = True,                 # Used with max_mel_frames
        use_lws = False,                         # "Fast spectrogram phase recovery using local weighted sums"
        symmetric_mels = True,                   # Sets mel range to [-max_abs_value, max_abs_value] if True,
                                                 #               and [0, max_abs_value] if False
        )

def hparams_debug_string(hparams=hparams):
    return str(hparams)
