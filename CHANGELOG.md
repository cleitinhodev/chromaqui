# Changelog

## 3.0.0 — 2026-11-03

**Novo nome: Chromaqui!** (antes "Chroma Frames").

### Novidades
- **Logo e ícones novos**: `assets/logo.png` + `icon.ico` (16–256 px), `favicon.ico` e PNGs de 16 a 1024 px,
  gerados por `tools/prepare_logo.py` + `tools/make_icon.py` (16/24/32 px com recorte justo e nitidez extra).
- **Visual renovado**: temas **Claro/Escuro** com gradientes nas cores do logo (lima → verde → esmeralda),
  lembrados entre sessões; animações e brilho neon opcionais (desligáveis em Configurações).
- **8 idiomas**, trocados na hora sem perder o vídeo/ajustes: Português (Brasil), English, Español,
  Français, Deutsch, Italiano, 日本語, 简体中文 (inclui as dicas/tooltips).
- **Diálogo Sobre** com versão, descrição e links (repositório, site, doação).
- **Novos formatos de exportação** (todos com transparência):
  sequências PNG / TGA / TIFF / WebP, **GIF animado transparente** (limiar de alfa, cores, qualidade da
  paleta, pontilhado, cor de borda/matte), **WebP animado**, **APNG**, **WebM VP9 com alfa** e
  **MOV ProRes 4444 com alfa** (ffmpeg embutido). Intervalo, passo, escala, FPS e repetições respeitados;
  progresso e cancelar em todos.
- **Fundo de teste na prévia**: imagem ou vídeo (preencher/ajustar/esticar). Só vai para o arquivo se
  "Incluir fundo na exportação" estiver marcado.
- **Renderização na GPU** (OpenCL) com opção Automático/CPU/GPU, teste de conferência e volta segura
  para a CPU; a barra de status mostra o backend e o tempo da prévia / FPS real.
- `--self-test` ampliado: tema, efeitos, ícone, Sobre/Configurações, todos os idiomas, presets,
  visualizações, CPU/GPU, fundo, reprodução e **todos os formatos** (conferidos com ffprobe/Pillow).
- Repositório com README, licença MIT, CHANGELOG e workflow de Release no GitHub Actions.

### Mantido da 2.x
Remoção de verde/azul/cor personalizada, conta-gotas, refinamento de bordas (guided filter),
descontaminação, colorização de bordas, supressão de spill, correção de cor, garbage matte, presets,
reprodução com FPS ajustável e linha do tempo.
