# Changelog

## 3.0.1 — 2026-11-03

### Correções
- **Exportar dava "expected str, bytes or os.PathLike object, not bool"**: o botão Exportar passava o
  estado `checked` (False) do sinal `clicked` no lugar do caminho de saída. Agora o botão chama a
  exportação sem argumentos, o caminho é validado, e uma pasta salva que não existe mais é ignorada
  ao abrir os diálogos.
- **Travava e fechava ao mudar a "Qualidade da reprodução" durante a reprodução**: ao reiniciar a
  reprodução, o aviso de "terminou" da thread antiga chegava depois e apagava a referência da thread
  nova ainda em execução, e o Qt encerrava o programa ("QThread destroyed while running"). Agora:
  - a qualidade muda na hora, sem reiniciar a thread;
  - threads antigas só são liberadas depois de terminarem (reprodução, miniaturas, exportação, prévia);
  - sinais e quadros atrasados de uma thread antiga são ignorados;
  - no máximo 1 quadro "em voo" para a interface: em resolução alta os quadros são descartados em vez
    de acumular numa fila.
- **Registro de erros**: erros inesperados e travamentos agora ficam em
  `%APPDATA%\Chromaqui\logs` (`erros.log` e `travamento.log`), e o programa mostra um aviso em vez de
  fechar em silêncio.

### Testes
- Novo `tests/test_ui_flows.py`: exporta clicando no botão (diálogos simulados) em todos os formatos,
  com configurações novas, salvas e com pasta inexistente; estresse de reprodução trocando a qualidade
  centenas de vezes, buscas, reinícios rápidos, fim do vídeo e troca de idioma, inclusive com vídeo 1080p.
- `--self-test` também exporta pelo botão e troca a qualidade durante a reprodução.

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
