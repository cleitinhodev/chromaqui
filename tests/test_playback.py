"""Testa a lógica de reprodução (sem interface), com relógio simulado."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from chromaqui import core as chroma

OUT = os.path.join(HERE, "_out")
VID = os.path.join(OUT, "teste_bordas_suaves.mp4")   # 24 quadros, 24 fps
if not os.path.exists(VID):
    import make_soft_video; make_soft_video.main()


class Clock:
    t = 0.0
    def __call__(self): return self.t


class CapSpy:
    """Conta quantas vezes o vídeo foi reposicionado (seek) e lido."""
    def __init__(self, cap): self.cap, self.sets, self.reads, self.grabs = cap, 0, 0, 0
    def set(self, *a): self.sets += 1; return self.cap.set(*a)
    def read(self): self.reads += 1; return self.cap.read()
    def grab(self): self.grabs += 1; return self.cap.grab()
    def release(self): self.cap.release()


def play(fps, work, n_max, loop=False, seek_at=None, start=0):
    clk = Clock(); v = chroma.Video(VID); spy = CapSpy(v.cap); v.cap = spy
    pb = chroma.Playback(v, start, fps, loop, clock=clk)
    shown = []
    while len(shown) < n_max:
        if seek_at and len(shown) == seek_at[0]:
            pb.seek(seek_at[1])
        r = pb.next_frame()
        if r is None:
            break
        clk.t += work                 # tempo de processamento (recorte) do quadro
        clk.t += pb.wait_time()       # espera até a hora certa
        pb.mark_shown(); shown.append(r[0])
    pb.release()
    return pb, spy, shown


# 1) processamento rápido: todos os quadros, em ordem, sem seek extra, ~24 fps
pb, spy, shown = play(24, 0.005, 100)
assert shown == list(range(24)), shown
assert pb.dropped == 0 and spy.sets == 1 and spy.reads == 24, (pb.dropped, spy.sets)
assert abs(pb.actual_fps - 24) < 0.5, pb.actual_fps
print(f"rápido: {len(shown)} quadros, {pb.actual_fps:.1f} fps real, 0 descartados, 1 seek")

# 2) processamento lento (100 ms/quadro com alvo 24 fps): descarta quadros, mantém o tempo real
pb, spy, shown = play(24, 0.100, 100)
assert all(b > a for a, b in zip(shown, shown[1:])), "ordem"
assert pb.dropped > 0 and spy.sets == 1, "devia descartar sem seek"
assert shown[-1] >= 20 and 8 <= pb.actual_fps <= 11, (shown[-1], pb.actual_fps)
assert spy.reads + spy.grabs <= 24
print(f"lento: {len(shown)} mostrados, {pb.dropped} descartados (pulados com grab, sem recorte), "
      f"{pb.actual_fps:.1f} fps real, {spy.sets} seek")

# 3) repetir: volta ao início (1 seek por volta)
pb, spy, shown = play(24, 0.005, 60, loop=True)
assert shown[:24] == list(range(24)) and shown[24] == 0 and len(shown) == 60
assert spy.sets == 3, spy.sets
print(f"repetir: 60 quadros, voltou ao início 2x, {spy.sets} seeks")

# 4) pular durante a reprodução (clique na linha do tempo)
pb, spy, shown = play(24, 0.005, 10, seek_at=(3, 15))
assert shown[:3] == [0, 1, 2] and shown[3] == 15 and shown[4] == 16, shown
print("pular: 0,1,2 -> 15,16,... ok")

# 5) FPS diferente do vídeo (12 fps): tempo total dobra
clk = Clock(); pb = chroma.Playback(VID, 0, 12, False, clock=clk)
while (r := pb.next_frame()) is not None:
    clk.t += pb.wait_time(); pb.mark_shown()
assert pb.shown == 24 and abs(clk.t - 2.0) < 0.01, clk.t
pb.release()
print(f"12 fps: 24 quadros em {clk.t:.2f} s")
print("OK")
