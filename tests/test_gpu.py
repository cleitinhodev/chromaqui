"""GPU (OpenCL): modo CPU é inofensivo; se houver OpenCL, saída quase idêntica à da CPU.
Para testar sem placa de vídeo: OPENCV_OPENCL_DEVICE=":CPU:" com pocl instalado."""
import os, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from chromaqui import core, gpu


def run(log=print):
    v = core.Video(os.path.join(HERE, "_out", "teste_cabelo_loiro.mp4"))
    f = v.read(12); v.release()
    P = core.KeyParams()
    st = gpu.set_mode("cpu"); assert not gpu.enabled() and not st["enabled"]
    t = time.perf_counter(); c0, a0 = core.key_frame_float(f, P); tc = time.perf_counter() - t
    log("cpu: " + gpu.describe() + f"  {tc*1000:.0f} ms")
    st = gpu.set_mode("gpu")
    log("gpu pedido -> " + gpu.describe())
    if not st["enabled"]:
        st = gpu.set_mode("auto"); assert not gpu.enabled()
        log("OpenCL indisponível: ficou na CPU (fallback ok)")
        return None
    t = time.perf_counter(); c1, a1 = core.key_frame_float(f, P); tg = time.perf_counter() - t
    da, dc = float(np.abs(a0 - a1).max()), float(np.abs(c0 - c1).mean())
    da_mean = float(np.abs(a0 - a1).mean())
    log(f"gpu vs cpu: alfa máx {da:.4f} médio {da_mean:.6f}; cor média {dc:.4f}  ({tg*1000:.0f} ms)")
    assert da_mean < 2e-3 and dc < 0.5 and da < 0.08, (da, da_mean, dc)
    gpu.set_mode("cpu")
    return da


if __name__ == "__main__":
    run(); print("OK")
