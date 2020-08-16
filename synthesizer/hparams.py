# DSP --------------------------------------------------------------------------------------------------------------#

# Settings for all models
sample_rate = 16000
n_fft = 800
fft_bins = n_fft // 2 + 1
num_mels = 80
hop_length = 200                    # For 16000 Hz, 200 = 12.5ms - in line with Tacotron 2 paper
win_length = 800                    # For 16000 Hz, 800 = 50ms - same reason as above
fmin = 55
max_abs_value = 4.                  # Gradient explodes if too big, premature convergence if too small.
min_level_db = -100
ref_level_db = 20
bits = 9                            # bit depth of signal
mu_law = True                       # Recommended to suppress noise if using raw bits in hp.voc_mode below


# TACOTRON/TTS -----------------------------------------------------------------------------------------------------#


# Model Hparams
tts_embed_dims = 512                # embedding dimension for the graphemes/phoneme inputs
tts_encoder_dims = 128
tts_decoder_dims = 256
tts_postnet_dims = 128
tts_encoder_K = 16
tts_lstm_dims = 1024
tts_postnet_K = 8
tts_num_highways = 4
tts_dropout = 0.5
tts_cleaner_names = ["english_cleaners"]
tts_stop_threshold = -3.4           # Value below which audio generation ends.
                                    # For example, for a range of [-4, 4], this
                                    # will terminate the sequence at the first
                                    # frame that has all values < -3.4

# Training
tts_schedule = [(7,  1e-3,  20_000,  16),   # progressive training schedule
                (6,  3e-4,  50_000,  16),   # (r, lr, step, batch_size)
                (5,  3e-4, 100_000,  10),
                (4,  3e-4, 200_000,  8),
                (3,  3e-4, 300_000,  6),
                (2,  3e-4, 500_000,  6)]

tts_clip_grad_norm = 1.0            # clips the gradient norm to prevent explosion - set to None if not needed
tts_eval_interval = 2000            # evaluates the model every X steps:
                                    #     if X = 0, evaluates every epoch
                                    #     if X < 0, never evaluates
tts_eval_num_samples = 1            # makes this number of samples

# Data Preprocessing
max_mel_frames = 900                # if you have a couple of extremely long spectrograms you might want to use this
rescale = True
rescaling_max = 0.9
preemphasize = True                  
preemphasis = 0.97                  # filter coefficient to use if preemphasize is True

synthesis_batch_size = 32           # For vocoder preprocessing only.
                                    # Batch size can be larger that of training
                                    # since not keeping track of gradients

# Mel visualization and Griffin-Lim
signal_normalization = True           
power = 1.5
griffin_lim_iters = 60
# ------------------------------------------------------------------------------------------------------------------#

### SV2TTS
speaker_embedding_size = 256    # embedding dimension for the speaker embedding
silence_min_duration_split = 0.4  # Duration in seconds of a silence for an utterance to be split
utterance_min_duration = 1.6      # Duration in seconds below which utterances are discarded
