"""Triangular Probability Density Function (TPDF) audio dithering."""

import numpy as np


def apply_tpdf_dither(data: np.ndarray, bit_depth: int = 16) -> np.ndarray:
    """Apply TPDF dither to normalized float32 audio data [-1.0, 1.0].

    Args:
        data: Float32 numpy array with values in range [-1.0, 1.0]
        bit_depth: Target bit depth (16, 24, or 32)

    Returns:
        np.ndarray: Dithered and quantized Float32 array in range [-1.0, 1.0]
    """
    if bit_depth >= 32:
        return data

    data = np.asarray(data, dtype=np.float32)
    max_val = float((1 << (bit_depth - 1)) - 1)
    lsb = 1.0 / max_val

    # Generate two uniform random distributions [-0.5, 0.5]
    shape = data.shape
    r1 = np.random.uniform(-0.5, 0.5, size=shape).astype(np.float32)
    r2 = np.random.uniform(-0.5, 0.5, size=shape).astype(np.float32)
    tpdf_noise = (r1 + r2) * lsb

    # Add noise before quantization
    dithered = data + tpdf_noise
    quantized = np.round(dithered * max_val) / max_val
    return np.clip(quantized, -1.0, 1.0)
