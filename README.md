<p align="center">
  <img src="assets/icons/icon_256.png" width="160" alt="Chromaqui! logo">
</p>

<h1 align="center">Chromaqui!</h1>

<p align="center">
  Remova o fundo verde ou azul (chroma key) de vídeos e exporte quadros e animações com transparência.<br>
  <b>PNG · TGA · TIFF · WebP · GIF · APNG · WebM VP9 (alfa) · ProRes 4444 (alfa)</b>
</p>

<p align="center">
  <a href="https://github.com/cleitinhodev/">Repositório</a> ·
  <a href="https://www.bugzinho.com/">Site</a> ·
  <a href="https://www.bugzinho.com/donate">Doar 💚</a> ·
  <a href="#english">English</a>
</p>

| Tema escuro | Tema claro |
|---|---|
| ![Tema escuro](docs/screenshot_escuro.png) | ![Tema claro](docs/screenshot_claro.png) |
| ![Exportar (escuro)](docs/screenshot_exportar_escuro.png) | ![Exportar (claro)](docs/screenshot_exportar_claro.png) |

## Download

Baixe o `.zip` mais recente em **Releases**:

- **Chromaqui-Windows.zip** — pasta com `Chromaqui.exe` (abre mais rápido; recomendado).
- **Chromaqui-Windows-onefile.zip** — um único `Chromaqui.exe` (mais prático, demora alguns segundos para abrir).

Não precisa instalar nada: descompacte e execute. Windows 10/11 64 bits.
Na primeira execução o SmartScreen pode avisar ("Executar assim mesmo"), porque o executável não é assinado.

## Recursos

- **Chroma key de qualidade**: verde, azul ou qualquer cor (conta-gotas na prévia); tolerância, faixa de
  transição, realces/sombras, pedestal; **refinamento de bordas** (guided filter), descontaminação,
  suavização de croma (H.264 4:2:0), **colorização de bordas**, supressão de reflexo (spill),
  limpeza da máscara, correção de cor e recorte (garbage matte). Presets em `.json`.
- **Prévia e reprodução**: resultado, máscara, original, lado a lado; play/pause com FPS ajustável;
  linha do tempo com miniaturas.
- **Fundo de teste**: xadrez, preto, branco, cor, **imagem ou vídeo** (preencher/ajustar/esticar).
  Só vai para o arquivo se você marcar **"Incluir fundo na exportação"** (resultado opaco).
- **Exportação** (sempre com transparência, respeitando intervalo, passo "1 a cada N", escala e FPS):

  | Formato | Observações |
  |---|---|
  | Sequência PNG | 8 ou 16 bits, compressão 0–9 |
  | Sequência TGA / TIFF / WebP | TIFF com LZW (8 bits) ou Deflate (16 bits), alfa marcado corretamente |
  | GIF animado | transparência de 1 bit: limiar de alfa, nº de cores, qualidade da paleta, pontilhado e **cor de borda (matte)** para bordas sem serrilhado |
  | WebP animado / APNG | alfa completo (8 bits), repetições |
  | WebM VP9 | `yuva420p` com alfa (navegadores, OBS, editores) |
  | MOV ProRes 4444 | `yuva444p10le` com alfa (Premiere, DaVinci Resolve, Final Cut) |

  WebM/ProRes/WebP/APNG usam o **ffmpeg embutido** (imageio-ffmpeg); nada para instalar.
- **Temas Claro/Escuro** com gradientes nas cores do logo, **animações** e **brilho neon**
  (desligáveis em ⚙ Configurações). Tudo fica salvo entre sessões.
- **Idiomas** (trocados **na hora**, sem perder o vídeo nem os ajustes): Português (Brasil) — padrão —,
  English, Español, Français, Deutsch, Italiano, 日本語, 简体中文.
- **GPU**: em Configurações → Renderização, escolha **Automático / CPU / GPU (OpenCL)**. O Automático só usa
  a placa de vídeo se ela existir **e** passar num teste de conferência; senão volta para a CPU com segurança.
  O resultado é o mesmo — muda só a velocidade. A barra de status mostra o backend em uso e o tempo da prévia.

## Rodar a partir do código

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python run_chromaqui.py
```

No Windows também dá para dar dois cliques em `executar.bat`.

### Auto-teste

```bash
python run_chromaqui.py --self-test caminho\video.mp4 pasta_saida
# ou no executável:  Chromaqui.exe --self-test video.mp4 pasta_saida
```

Testa tema, efeitos, ícone, Sobre/Configurações, todos os idiomas, presets, visualizações, CPU/GPU,
fundo, reprodução, **todos os formatos** (conferidos com ffprobe/Pillow), fundo na exportação e cancelar.
Resultado em `pasta_saida/selftest.log`. Outros testes: `tests/test_core.py`, `tests/test_exporters.py`,
`tests/test_gpu.py`, `tests/test_playback.py` (rode `tests/make_soft_video.py` antes).

### Gerar o executável

```bash
pip install -r requirements-build.txt
python tools/build_exe.py --both --zip
```

Gera `dist/Chromaqui/Chromaqui.exe`, `dist1/Chromaqui.exe` e os dois `.zip`. O workflow
`.github/workflows/release.yml` faz isso automaticamente no GitHub ao criar uma tag `v*`
(ex.: `git tag v3.0.0 && git push --tags`) e anexa os zips à Release.

### Trocar o logo / ícone

```bash
python tools/prepare_logo.py meu_logo.png assets/logo.png   # remove o fundo, recorta e deixa quadrado
python tools/make_icon.py assets/logo.png                    # icon.ico, favicon.ico, icons/*.png
python tools/logo_preview.py                                 # docs/logo_preview.png (claro/escuro)
```

`prepare_logo.py` aceita PNG transparente ou com fundo branco (remove só o branco ligado às bordas,
preservando partes brancas do desenho). As cores da interface derivam de uma única cor,
`ACCENT` em `chromaqui/theme.py`.

### Traduções

Arquivos em `assets/i18n/<idioma>.json` (chave = texto em português). Para incluir frases novas:
`python tools/extract_strings.py --template` (atualiza `_template.json` e mostra o que falta em cada idioma).
Os textos-fonte numerados ficam em `tools/i18n_src/*.txt` → `python tools/i18n_build.py`.

## Estrutura

```
chromaqui/      app.py (janela), core.py (chroma key), exporters.py (formatos), gpu.py (OpenCL),
                theme.py, fx.py, i18n.py, dialogs.py, widgets.py, settings.py, selftest.py
assets/         logo.png, icon.ico, favicon.ico, icons/, i18n/
tools/          build_exe.py, make_icon.py, prepare_logo.py, logo_preview.py, extract_strings.py, i18n_build.py
tests/          testes e geradores de vídeos de teste
docs/           capturas de tela
```

## Licença

[MIT](LICENSE) — software livre.

---

## English

**Chromaqui!** is a free Windows app that removes green/blue (chroma key) backgrounds from videos and
exports frames and animations with transparency: **PNG/TGA/TIFF/WebP sequences, transparent animated GIF,
animated WebP, APNG, WebM VP9 with alpha and MOV ProRes 4444 with alpha** (bundled ffmpeg).

- High-quality keying: guided-filter edge refinement, despill, edge decontamination and colorization,
  chroma smoothing, matte cleanup, color correction, garbage matte, presets.
- Preview over checkerboard/solid color or **your own image/video background**; it is only baked into
  the export when **"Include background in export"** is checked.
- **Light/Dark themes**, optional animations and neon glow, **8 languages switchable at runtime**
  (pt-BR, en, es, fr, de, it, ja, zh-CN).
- **GPU rendering** via OpenCV OpenCL (Auto/CPU/GPU) with a verification test and safe CPU fallback.

**Download:** grab `Chromaqui-Windows.zip` (folder build, faster start) or
`Chromaqui-Windows-onefile.zip` (single exe) from **Releases**, unzip and run.

**From source:** `pip install -r requirements.txt && python run_chromaqui.py`.
**Build:** `pip install -r requirements-build.txt && python tools/build_exe.py --both --zip`.
**Self-test:** `Chromaqui.exe --self-test video.mp4 out_dir` (writes `out_dir/selftest.log`).

Notes: GIF only supports 1-bit transparency (use the matte color to avoid jagged edges);
the bundled ffmpeg adds ~100 MB; the "LZW" option means LZW for 8-bit TIFF and Deflate for 16-bit TIFF.

License: [MIT](LICENSE).
