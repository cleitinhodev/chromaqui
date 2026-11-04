"""Recursos da 3.2 (beta): retoque com pincel, sombra/brilho, recorte que segue o objeto e por
quadros-chave, sprite sheet + JSON, remoção de fundo por IA (download + inferência), verificação
de atualizações. Uso: python tests/test_features.py [all]"""
import json, os, shutil, sys
import cv2, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "_out")
os.environ["CHROMAQUI_MODELS_DIR"] = os.path.join(OUT, "models")  # nunca a pasta real do usuário
from chromaqui import ai, core, exporters as ex, updates
from chromaqui.retouch import Retouch
from PIL import Image

VID = os.path.join(OUT, "teste_verde.mp4")
DEST = os.path.join(OUT, "recursos")


def _frame(i=10):
    v = core.Video(VID); f = v.read(i); v.release(); return f


def test_retouch():
    f = _frame(10)
    p = core.KeyParams()
    base = core.compute_alpha(f, p)
    rt = Retouch(640, 360)
    assert rt.is_empty()
    # remover a bola (centro x=60+9*10=150, y=180) e manter um pedaço do fundo (500, 80)
    rt.begin_stroke(None)
    for x in range(120, 181, 10):
        rt.dab(x, 180, 30, hardness=0.8, mode="remove")
    rt.begin_stroke(None)
    rt.dab(500, 80, 20, hardness=1.0, mode="keep")
    p.retouch = rt
    a = core.compute_alpha(f, p)
    assert base[180, 150] > 0.95 and a[180, 150] < 0.05, (base[180, 150], a[180, 150])
    assert base[80, 500] < 0.05 and a[80, 500] > 0.95, (base[80, 500], a[80, 500])
    assert abs(float(a[300, 400]) - float(base[300, 400])) < 1e-6        # longe do pincel: igual
    # dureza: borda macia tem valores intermediários
    soft = Retouch(640, 360); soft.dab(320, 180, 40, hardness=0.0, mode="keep")
    m = soft.mask(0); assert 0.05 < m[180, 320 + 30] < 0.95 and m[180, 320] > 0.9
    # borracha volta a 0
    soft.dab(320, 180, 60, hardness=1.0, mode="erase"); assert np.abs(soft.mask(0)).max() < 0.02
    # só no quadro atual
    rt2 = Retouch(640, 360); rt2.dab(500, 80, 20, hardness=1.0, mode="keep", frame=10)
    p2 = core.KeyParams(); p2.retouch = rt2
    p2.frame_idx = 10; assert core.compute_alpha(f, p2)[80, 500] > 0.95
    p2.frame_idx = 11; assert core.compute_alpha(f, p2)[80, 500] < 0.05
    # deepcopy é barato (compartilha camadas) e copy-on-write protege o trabalho já enviado
    import copy
    snap = copy.deepcopy(p2)
    old = snap.retouch.frames[10]
    rt2.begin_stroke(10); rt2.dab(500, 80, 20, hardness=1.0, mode="remove", frame=10)
    assert snap.retouch.frames[10] is old and old[int(80 * rt2.k), int(500 * rt2.k)] > 100
    # exportação recortada usa o mesmo retoque (frame_box)
    o = core.ExportOptions(start=10, end=10, fmt="png", crop=(100, 100, 200, 120))
    out = os.path.join(DEST, "retoque")
    ex.export(VID, out, p, o)
    img = cv2.imdecode(np.fromfile(os.path.join(out, "frame_00001.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    assert img[80, 50, 3] < 15, img[80, 50]      # (150,180) no original -> (50,80) no recorte
    # meia escala
    o.scale = 0.5; ex.export(VID, out + "_05", p, o)
    img = cv2.imdecode(np.fromfile(os.path.join(out + "_05", "frame_00001.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    assert img[40, 25, 3] < 15
    print("RETOQUE OK (manter/remover, dureza, borracha, por quadro, recorte/escala)")


def test_glow():
    f = _frame(10)
    p = core.KeyParams()
    c0, a0 = core.key_frame_float(f, p)
    p.glow = dict(core.GLOW_DEFAULTS, on=True, color=[255, 0, 0], blur=4, dx=20, dy=0, opacity=80)
    c1, a1 = core.key_frame_float(f, p)
    # à direita da bola (x=150+70+10) havia fundo transparente; agora há a sombra vermelha
    y, x = 180, 150 + 70 + 12
    assert a0[y, x] < 0.05 and a1[y, x] > 0.5, (a0[y, x], a1[y, x])
    assert c1[y, x, 2] > 200 and c1[y, x, 0] < 40, c1[y, x]
    assert np.allclose(a1[180, 150], a0[180, 150], atol=1e-4)            # objeto intacto
    # neon (sem deslocamento): contorno
    p.glow = dict(core.GLOW_DEFAULTS, on=True, mode="neon", color=[0, 255, 0], blur=6, dx=0, dy=0, opacity=90, spread=3)
    c2, a2 = core.key_frame_float(f, p)
    assert a2[180, 150 - 70 - 4] > 0.3 and a2[180, 150 + 70 + 4] > 0.3
    # prévia (render_view) e exportação opcional
    view = core.render_view(f, p, "Resultado", "branco")
    assert view[180, 150 + 70 + 4, 1] > view[180, 150 + 70 + 4, 2] + 30
    for on in (True, False):
        p.glow["export"] = on
        out = os.path.join(DEST, f"glow_{on}")
        ex.export(VID, out, p, core.ExportOptions(start=10, end=10, fmt="png"))
        img = cv2.imdecode(np.fromfile(os.path.join(out, "frame_00001.png"), np.uint8), cv2.IMREAD_UNCHANGED)
        assert (img[180, 150 + 70 + 4, 3] > 70) == on, (on, img[180, 150 + 70 + 4])
    # preset salva/carrega o efeito
    pp = os.path.join(DEST, "glow.json"); core.save_preset(pp, p)
    q = core.load_preset(pp); assert q.glow["mode"] == "neon" and q.glow["color"] == [0, 255, 0]
    print("SOMBRA/BRILHO OK (prévia, exportação opcional, preset)")


def test_tracking():
    p = core.KeyParams(); p.values["crop_top"] = 16       # tira o número do quadro (canto)
    o = core.ExportOptions(start=0, end=40, step=2, fmt="png", crop_motion="follow", track_margin=10, track_smooth=5)
    path = core.motion_path(VID, p, o)
    assert path and sorted(path) == list(range(0, 41, 2))
    sizes = {r[2:] for r in path.values()}
    assert len(sizes) == 1, sizes
    cw, ch = sizes.pop()
    assert 150 <= cw <= 200 and 220 <= ch <= 260, (cw, ch)
    xs = [path[i][0] for i in sorted(path)]
    assert xs[-1] - xs[0] > 250 and all(b >= a for a, b in zip(xs, xs[1:])), xs       # segue a bola →
    for i, r in path.items():           # o objeto (bola + retângulo) fica dentro do recorte
        cx = 60 + 9 * i
        assert r[0] <= max(0, cx - 70) and r[0] + r[2] >= min(640, cx + 70), (i, r)
    out = os.path.join(DEST, "seguir")
    shutil.rmtree(out, ignore_errors=True)
    stages = []
    r = ex.export(VID, out, p, o, stage=stages.append)
    assert r["count"] == 21 and stages == ["track", "export"], (r, stages)
    ims = [Image.open(os.path.join(out, n)) for n in sorted(os.listdir(out))]
    assert {im.size for im in ims} == {(cw, ch)}
    # bola sempre perto do centro horizontal
    for k, im in enumerate(ims):
        a = np.asarray(im)[..., 3]
        cols = np.nonzero(a[180 - path[2 * k][1]] > 128)[0]
        mid = (cols.min() + cols.max()) / 2
        assert abs(mid - cw / 2) < 25, (k, mid, cw)
    # webm: pares
    o2 = core.ExportOptions(**{**o.__dict__, "fmt": "webm"})
    path2 = core.motion_path(VID, p, o2)
    w2, h2 = next(iter(path2.values()))[2:]
    assert w2 % 2 == 0 and h2 % 2 == 0
    # quadros-chave: interpolação linear do centro, tamanho fixo = maior chave
    keys = {0: (0, 0, 100, 100), 20: (200, 100, 160, 120)}
    assert core.keyframe_rect(keys, 10, 640, 360) == (100, 50, 130, 110)
    o3 = core.ExportOptions(start=0, end=30, fmt="gif", crop_motion="keys", crop_keys=keys)
    pk = core.motion_path(VID, p, o3)
    assert {r[2:] for r in pk.values()} == {(160, 120)} and pk[30] == pk[20] == (200, 100, 160, 120)
    assert pk[10] == (85, 45, 160, 120), pk[10]
    out3 = os.path.join(DEST, "chaves.gif")
    r = ex.export(VID, out3, p, o3)
    assert r["count"] == 31 and Image.open(out3).size == (160, 120)
    print(f"RECORTE QUE SEGUE OK ({cw}x{ch}, x {xs[0]}→{xs[-1]}); QUADROS-CHAVE OK")


def test_spritesheet():
    p = core.KeyParams()
    base = os.path.join(DEST, "sheet")
    shutil.rmtree(base, ignore_errors=True); os.makedirs(base)
    # hash, trim, colunas automáticas
    o = core.ExportOptions(start=0, end=11, fmt="sheet", crop=(0, 60, 640, 300), sheet_pad=4)
    r = ex.export(VID, os.path.join(base, "anim.png"), p, o)
    assert r["count"] == 12
    d = json.load(open(os.path.join(base, "anim.json"), encoding="utf-8"))
    assert isinstance(d["frames"], dict) and len(d["frames"]) == 12
    fr = d["frames"]["anim_00000.png"]
    assert fr["trimmed"] and fr["sourceSize"] == {"w": 640, "h": 300}
    assert d["meta"]["image"] == "anim.png" and d["meta"]["format"] == "RGBA8888"
    sheet = np.asarray(Image.open(os.path.join(base, "anim.png")))
    assert sheet.shape[0] == d["meta"]["size"]["h"] and sheet.shape[1] == d["meta"]["size"]["w"]
    g = d["meta"]["grid"]
    assert g["columns"] * g["rows"] >= 12 and g["padding"] == 4
    for k, v in d["frames"].items():   # cada quadro dentro da folha e com conteúdo
        f = v["frame"]; assert f["x"] + f["w"] <= sheet.shape[1] and f["y"] + f["h"] <= sheet.shape[0]
        assert sheet[f["y"]:f["y"] + f["h"], f["x"]:f["x"] + f["w"], 3].max() == 255
    # array, sem trim, 5 colunas
    o = core.ExportOptions(start=0, end=11, fmt="sheet", scale=0.25, sheet_cols=5, sheet_pad=0, sheet_trim=False,
                           sheet_json="array")
    ex.export(VID, os.path.join(base, "arr.png"), p, o)
    d = json.load(open(os.path.join(base, "arr.json"), encoding="utf-8"))
    assert isinstance(d["frames"], list) and d["frames"][7]["filename"] == "arr_00007.png"
    assert d["frames"][7]["frame"] == {"x": 2 * 160, "y": 90, "w": 160, "h": 90}
    assert not d["frames"][0]["trimmed"] and d["meta"]["size"] == {"w": 800, "h": 270}
    # tamanho máximo: várias folhas
    o = core.ExportOptions(start=0, end=11, fmt="sheet", scale=0.25, sheet_pad=0, sheet_trim=False, sheet_max=400)
    r = ex.export(VID, os.path.join(base, "multi.png"), p, o)
    files = sorted(n for n in os.listdir(base) if n.startswith("multi"))
    assert files == ["multi_0.json", "multi_0.png", "multi_1.json", "multi_1.png"], files
    n = sum(len(json.load(open(os.path.join(base, f), encoding="utf-8"))["frames"]) for f in files if f.endswith(".json"))
    assert n == 12 and max(Image.open(os.path.join(base, "multi_0.png")).size) <= 400
    try:
        ex._SheetWriter.layout(3, 500, 10, 0, 0, 400); raise AssertionError("deveria falhar")
    except ValueError:
        pass
    print("SPRITE SHEET OK (hash/array, colunas, espaço, tamanho máximo, trim)")


def test_ai():
    # download: progresso, verificação SHA-256 e mensagem de erro
    shutil.rmtree(ai.models_dir(), ignore_errors=True)
    local = os.environ.get("CHROMAQUI_TEST_MODELS", "/workspace/models")
    orig = {k: dict(v) for k, v in ai.MODELS.items()}
    try:
        bad = dict(ai.MODELS["u2netp"], url="http://127.0.0.1:9/nada.onnx")
        ai.MODELS["u2netp"] = bad
        try:
            ai.download("u2netp", timeout=3); raise AssertionError("deveria falhar")
        except ai.AIError as e:
            assert str(e)
        assert not ai.is_downloaded("u2netp") and not os.path.exists(ai.model_path("u2netp") + ".part")
        ai.MODELS.update({k: dict(v) for k, v in orig.items()})
        for name in ("u2netp", "modnet"):
            src = os.path.join(local, {"u2netp": "u2netp.onnx", "modnet": "modnet.onnx"}[name])
            if os.path.exists(src):
                from pathlib import Path
                ai.MODELS[name]["url"] = Path(src).as_uri()
            prog = []
            try:
                ai.download(name, progress=lambda g, t: prog.append((g, t)))
            except ai.AIError as e:
                print(f"IA: download de {name} indisponível ({e}); inferência pulada")
                return
            assert ai.is_downloaded(name) and prog and prog[-1][0] == ai.MODELS[name]["size"]
    finally:
        ai.MODELS.clear(); ai.MODELS.update(orig)
    assert ai.runtime_available()
    f = _frame(10)
    for name in ("u2netp", "modnet"):
        a = ai.predict(f, name)
        assert a.shape == f.shape[:2] and a.dtype == np.float32 and 0 <= a.min() and a.max() <= 1
        assert ai.predict(f, name) is a                       # cache
    # u2netp acha a bola num fundo liso
    a = ai.predict(f, "u2netp"); assert a[180, 150] > 0.5 and a[20, 600] < 0.5, (a[180, 150], a[20, 600])
    # integração: a IA substitui o alfa da cor-chave; limpeza e retoque continuam valendo
    p = core.KeyParams(); p.source = "ai"; p.ai_model = "u2netp"; p.values["refine"] = 0
    a1 = core.compute_alpha(f, p)
    p.values["choke"] = 30
    a2 = core.compute_alpha(f, p)
    assert a2.sum() < a1.sum() * 0.97, (a1.sum(), a2.sum())
    rt = Retouch(640, 360); rt.dab(150, 180, 30, 1.0, "remove"); p.retouch = rt
    assert core.compute_alpha(f, p)[180, 150] < 0.05
    # spill desligado na IA (fundo pode ter qualquer cor)
    c = core.process_color(f, p, a1)
    assert np.isfinite(c).all()
    # exportação com IA
    p.retouch = None
    r = ex.export(VID, os.path.join(DEST, "ia"), p, core.ExportOptions(start=0, end=2, fmt="png"))
    assert r["count"] == 3
    # modelo ausente -> volta para a cor-chave (sem erro)
    p.ai_model = "inexistente"
    assert core.compute_alpha(f, p).shape == f.shape[:2]
    print("IA OK (download com progresso/erro/SHA, u2netp + MODNet, refinamento e retoque combinados)")


def test_updates():
    V = updates.parse_version
    assert V("3.2.0-beta.1") < V("3.2.0-beta.2") < V("3.2.0-rc.1") < V("3.2.0") < V("3.2.1") < V("3.10.0")
    assert V("v3.1.0") == V("3.1.0") and V("3.1.0") < V("3.2.0-beta.1")
    rels = [{"tag_name": "v3.3.0-beta.1", "prerelease": True, "draft": False, "html_url": "u1"},
            {"tag_name": "v3.2.0", "prerelease": False, "draft": False, "html_url": "u2"},
            {"tag_name": "v9.0.0", "prerelease": False, "draft": True, "html_url": "u3"}]
    assert updates.pick_update(rels, "3.2.0-beta.1", False)["tag_name"] == "v3.2.0"
    assert updates.pick_update(rels, "3.2.0-beta.1", True)["tag_name"] == "v3.3.0-beta.1"
    assert updates.pick_update(rels, "3.3.0", True) is None
    assert updates.pick_update(rels, "3.2.0", False) is None
    # falha de rede é silenciosa (None)
    assert updates.check("3.0.0", True, url="http://127.0.0.1:9/x", timeout=2) is None
    print("ATUALIZAÇÕES OK (versões beta/rc, escolha estável/beta, rede silenciosa)")


if __name__ == "__main__":
    if not os.path.exists(VID):
        import test_core; test_core.make_video(VID)
    os.makedirs(DEST, exist_ok=True)
    test_retouch(); test_glow(); test_tracking(); test_spritesheet(); test_updates(); test_ai()
    print("TEST FEATURES OK")
