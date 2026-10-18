"""DS-CNN for 1 s MFCC windows (Phase 5 architecture, ~20 KB after INT8)."""
import tensorflow as tf
from tensorflow.keras import layers

from . import features as F


def build(n_filters=32, n_blocks=4):
    inp = layers.Input((F.N_FRAMES, F.N_MFCC, 1), name="mfcc")
    x = layers.Conv2D(n_filters, (10, 4), strides=(2, 2), padding="same", use_bias=False)(inp)
    x = layers.BatchNormalization(momentum=0.9)(x)
    x = layers.ReLU()(x)
    for _ in range(n_blocks):
        x = layers.DepthwiseConv2D((3, 3), padding="same", use_bias=False)(x)
        x = layers.BatchNormalization(momentum=0.9)(x)
        x = layers.ReLU()(x)
        x = layers.Conv2D(n_filters, (1, 1), padding="same", use_bias=False)(x)
        x = layers.BatchNormalization(momentum=0.9)(x)
        x = layers.ReLU()(x)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.2)(x)
    out = layers.Dense(2, activation="softmax", name="probs")(x)
    return tf.keras.Model(inp, out, name="ds_cnn")
