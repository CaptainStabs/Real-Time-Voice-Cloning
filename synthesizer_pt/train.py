import torch
from torch import optim
import torch.nn.functional as F
from synthesizer_pt.utils.display import *
from synthesizer_pt.utils.dataset import get_tts_datasets
from synthesizer_pt.utils.text.symbols import symbols
from synthesizer_pt.utils.paths import Paths
from synthesizer_pt.models.tacotron import Tacotron
import argparse
from synthesizer_pt.utils import data_parallel_workaround
import os
from pathlib import Path
import time
import numpy as np
import sys
from synthesizer_pt.utils.checkpoints import save_checkpoint, restore_checkpoint
import synthesizer_pt.hparams as hp
from synthesizer_pt.utils.text import sequence_to_text
from synthesizer_pt.utils import ValueWindow, plot
from synthesizer_pt import audio
from synthesizer_pt.synthesizer_dataset import SynthesizerDataset, collate_synthesizer
from torch.utils.data import DataLoader
from datetime import datetime
from tqdm import tqdm
import numpy as np
import traceback
import time
import os


def np_now(x: torch.Tensor): return x.detach().cpu().numpy()

def time_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def train(run_id: str, syn_dir: Path, models_dir: Path, save_every: int,
         backup_every: int, force_restart:bool, train_steps:int):

    log_dir = os.path.join(models_dir, run_id)
    save_dir = os.path.join(log_dir, "taco_pretrained")
    plot_dir = os.path.join(log_dir, "plots")
    wav_dir = os.path.join(log_dir, "wavs")
    mel_output_dir = os.path.join(log_dir, "mel-spectrograms")
    eval_dir = os.path.join(log_dir, "eval-dir")
    eval_plot_dir = os.path.join(eval_dir, "plots")
    eval_wav_dir = os.path.join(eval_dir, "wavs")
    meta_folder = os.path.join(log_dir, "metas")
    os.makedirs(save_dir, exist_ok=True)
    os.makedirs(plot_dir, exist_ok=True)
    os.makedirs(wav_dir, exist_ok=True)
    os.makedirs(mel_output_dir, exist_ok=True)
    os.makedirs(eval_dir, exist_ok=True)
    os.makedirs(eval_plot_dir, exist_ok=True)
    os.makedirs(eval_wav_dir, exist_ok=True)
    os.makedirs(meta_folder, exist_ok=True)
    
    checkpoint_fpath = os.path.join(save_dir, "pretrained.pt")
    metadat_fpath = os.path.join(syn_dir, "train.txt")
    
    print("Checkpoint path: {}".format(checkpoint_fpath))
    print("Loading training data from: {}".format(metadat_fpath))
    print("Using model: Tacotron")
    
    # Embeddings metadata
    char_embedding_meta = os.path.join(meta_folder, "CharacterEmbeddings.tsv")
    if not os.path.isfile(char_embedding_meta):
        with open(char_embedding_meta, "w", encoding="utf-8") as f:
            for symbol in symbols:
                if symbol == " ":
                    symbol = "\\s"  # For visual purposes, swap space with \s
                
                f.write("{}\n".format(symbol))
    
    char_embedding_meta = char_embedding_meta.replace(log_dir, "..")
    
    # Book keeping
    step = 0
    time_window = ValueWindow(100)
    loss_window = ValueWindow(100)
    
    
    # From WaveRNN/train_tacotron.py
    if torch.cuda.is_available():
        device = torch.device('cuda')

        for session in hp.tts_schedule:
            _, _, _, batch_size = session
            if batch_size % torch.cuda.device_count() != 0:
                raise ValueError('`batch_size` must be evenly divisible by n_gpus!')
    else:
        device = torch.device('cpu')
    print('Using device:', device)

    # Instantiate Tacotron Model
    print('\nInitialising Tacotron Model...\n')
    model = Tacotron(embed_dims=hp.tts_embed_dims,
                     num_chars=len(symbols),
                     encoder_dims=hp.tts_encoder_dims,
                     decoder_dims=hp.tts_decoder_dims,
                     n_mels=hp.num_mels,
                     fft_bins=hp.num_mels,
                     postnet_dims=hp.tts_postnet_dims,
                     encoder_K=hp.tts_encoder_K,
                     lstm_dims=hp.tts_lstm_dims,
                     postnet_K=hp.tts_postnet_K,
                     num_highways=hp.tts_num_highways,
                     dropout=hp.tts_dropout,
                     stop_threshold=hp.tts_stop_threshold,
                     speaker_embedding_size=hp.tts_speaker_embedding_size).to(device)

    # Initialize the optimizer
    optimizer = optim.Adam(model.parameters())

    # Load the weights
    model_dir = models_dir.joinpath(run_id)
    model_dir.mkdir(exist_ok=True)
    weights_fpath = model_dir.joinpath(run_id + ".pt")
    if force_restart or not weights_fpath.exists():
        print("\nStarting the training of Tacotron from scratch\n")
        model.save(weights_fpath)
    else:
        print("\nLoading weights at %s" % weights_fpath)
        model.load(weights_fpath, optimizer)
        print("Tacotron weights loaded from step %d" % model.step)
    
    # Initialize the dataset
    metadata_fpath = syn_dir.joinpath("train.txt")
    mel_dir = syn_dir.joinpath("mels")
    embed_dir = syn_dir.joinpath("embeds")
    dataset = SynthesizerDataset(metadata_fpath, mel_dir, embed_dir)
    test_loader = DataLoader(dataset,
                             batch_size=1,
                             shuffle=True,
                             pin_memory=True)

    for i, session in enumerate(hp.tts_schedule):
        current_step = model.get_step()

        r, lr, max_step, batch_size = session

        training_steps = max_step - current_step

        # Do we need to change to the next session?
        if current_step >= max_step:
            # Are there no further sessions than the current one?
            if i == len(hp.tts_schedule)-1:
                # We have completed training. Breaking is same as continue
                break
            else:
                # There is a following session, go to it
                continue

        model.r = r

        # Begin the training
        simple_table([(f'Steps with r={r}', str(training_steps//1000) + 'k Steps'),
                      ('Batch Size', batch_size),
                      ('Learning Rate', lr),
                      ('Outputs/Step (r)', model.r)])

        for p in optimizer.param_groups:
            p["lr"] = lr

        data_loader = DataLoader(dataset,
                                 collate_fn=lambda batch: collate_synthesizer(batch, r),
                                 batch_size=batch_size,
                                 num_workers=2,
                                 shuffle=True,
                                 pin_memory=True)

        total_iters = len(dataset) 
        epochs = train_steps // total_iters + 1
        steps_per_epoch = np.ceil(total_iters / batch_size).astype(np.int32)

        for epoch in range(1, epochs+1):

            start = time.time()
            running_loss = 0

            # Perform 1 epoch
            for i, (x, m, e) in enumerate(data_loader, 1):

                #x = text, m = mel, e = embed
                x, m, e = x.to(device), m.to(device), e.to(device)

                # Forward pass
                # Parallelize model onto GPUS using workaround due to python bug
                if device.type == 'cuda' and torch.cuda.device_count() > 1:
                    m1_hat, m2_hat, attention = data_parallel_workaround(model, x, m, e)
                else:
                    m1_hat, m2_hat, attention = model(x, m, e)

                # Backward pass
                m1_loss = F.l1_loss(m1_hat, m)
                m2_loss = F.l1_loss(m2_hat, m)

                loss = m1_loss + m2_loss

                optimizer.zero_grad()
                loss.backward()

                if hp.tts_clip_grad_norm is not None:
                    grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), hp.tts_clip_grad_norm)
                    if np.isnan(grad_norm):
                        print('grad_norm was NaN!')

                optimizer.step()

                running_loss += loss.item()
                avg_loss = running_loss / i

                speed = i / (time.time() - start)

                step = model.get_step()
                k = step // 1000

                if backup_every != 0 and step % backup_every == 0 : 
                    backup_fpath = Path(f'{str(weights_fpath.parent)}/{run_id}_{k}k.pt')
                    model.save(backup_fpath, optimizer)

                if save_every != 0 and step % save_every == 0 : 
                    # Must save latest optimizer state to ensure that resuming training
                    # doesn't produce artifacts
                    model.save(weights_fpath, optimizer)

                if hp.tts_eval_interval > 0 and step % hp.tts_eval_interval == 0:
                    for sample_idx in range(hp.tts_eval_num_samples):
                        # At most, generate samples equal to number in the batch
                        if sample_idx + 1 <= len(x):
                            eval_model(attention=np_now(attention[sample_idx][:, :160]),
                                       mel_prediction=np_now(m2_hat[sample_idx]).T,
                                       target_spectrogram=np_now(m[sample_idx]).T,
                                       input_seq=np_now(x[sample_idx]),
                                       step=step,
                                       plot_dir=plot_dir,
                                       mel_output_dir=mel_output_dir,
                                       wav_dir=wav_dir,
                                       sample_num=sample_idx+1,
                                       loss=loss)

                msg = f'| Epoch: {epoch}/{epochs} ({i}/{steps_per_epoch}) | Loss: {avg_loss:#.4} | {speed:#.2} steps/s | Step: {k}k | '
                stream(msg)

            if hp.tts_eval_interval == 0:
                for sample_idx in range(hp.tts_eval_num_samples):
                    # At most, generate samples equal to number in the batch
                    if sample_idx + 1 <= len(x):
                        eval_model(attention=np_now(attention[sample_idx][:, :160]),
                                   mel_prediction=np_now(m2_hat[sample_idx]).T,
                                   target_spectrogram=np_now(m[sample_idx]).T,
                                   input_seq=np_now(x[sample_idx]),
                                   step=step,
                                   plot_dir=plot_dir,
                                   mel_output_dir=mel_output_dir,
                                   wav_dir=wav_dir,
                                   sample_num=sample_idx+1,
                                   loss=loss)
            print("")

def eval_model(attention, mel_prediction, target_spectrogram, input_seq, step,
               plot_dir, mel_output_dir, wav_dir, sample_num, loss):
    # Save some results for evaluation
    save_attention(attention, Path(f'{plot_dir}/attention_step_{step}_sample_{sample_num}'))

    # save predicted mel spectrogram to disk (debug)
    mel_filename = "mel-prediction-step-{}_sample_{}.npy".format(step, sample_num)
    np.save(os.path.join(mel_output_dir, mel_filename), mel_prediction,
            allow_pickle=False)

    # save griffin lim inverted wav for debug (mel -> wav)
    wav = audio.inv_mel_spectrogram(mel_prediction.T, hp)
    audio.save_wav(wav,
                   os.path.join(wav_dir, "step-{}-wave-from-mel_sample_{}.wav".format(step, sample_num)),
                   sr=hp.sample_rate)

    # save real and predicted mel-spectrogram plot to disk (control purposes)
    plot.plot_spectrogram(mel_prediction, os.path.join(plot_dir,
                                                       "step-{}-mel-spectrogram_sample_{}.png".format(
                                                           step, sample_num)),
                          title="{}, {}, step={}, loss={:.5f}".format("Tacotron",
                                                                      time_string(),
                                                                      step, loss),
                          target_spectrogram=target_spectrogram,
                          max_len=target_spectrogram.size // hp.num_mels)
    print("Input at step {}: {}".format(step, sequence_to_text(input_seq)))
