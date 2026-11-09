# Changelog

## 3.1.0 — compilação para Linux (adicionada em 2026-11-09)

Os arquivos **Chromaqui-Linux-x86_64.AppImage** e **.tar.gz** desta Release foram gerados do código da 3.1.0
com apenas os ajustes necessários para Linux (configurações e logs em `~/.config/Chromaqui`, ffmpeg
executável, Wayland/X11, atalho `.desktop`). Os arquivos do Windows da 3.1.0 não mudaram.

## 3.1.0 — 2026-11-03

### Novidade: recorte da área exportada
Para vídeos em que a maior parte da imagem é fundo verde: escolha só a área que interessa e a sobra
transparente não vai para os arquivos.
- Seção **"Recorte da área exportada"**: botão **Recortar** liga o seletor na prévia — arraste para
  desenhar, use as 8 alças para ajustar e o meio para mover; a área de fora fica escurecida e o tamanho
  aparece em pixels. Funciona também no modo "Lado a lado".
- Campos **X / Y / Largura / Altura** em pixels do vídeo original, sincronizados com o seletor.
- **Auto**: encontra a menor área que contém o objeto em 30 quadros espalhados pelo vídeo, mais uma
  **margem** configurável. **Redefinir** volta ao quadro inteiro.
- O recorte vale para **todos os quadros e todos os formatos** (sequências, GIF, WebP, APNG, WebM,
  ProRes) e para o fundo incluído na exportação (o fundo é recortado na mesma área da prévia).
  É aplicado no vídeo original e depois vem a escala.
- Opção **largura e altura pares**; WebM e ProRes sempre usam dimensões pares.
- Mais rápido: só a área recortada (mais uma margem de contexto) é processada, com o mesmo resultado
  do quadro inteiro.
- O recorte fica salvo por tamanho de vídeo (e nos presets `.json`); um recorte que não cabe no vídeo
  aberto é ignorado. A informação de saída mostra o tamanho final "(recortado)".
- Traduzido para os 8 idiomas; testes novos (`tests/test_crop.py`, fluxo de interface e auto-teste).

## 3.0.2 — 2026-11-03

Inclui as correções da 3.0.1 (abaixo) e mais:

### Correções
- **Reprodução: fechamento raro ao parar/reiniciar ou trocar a qualidade** (visto no Windows real durante
  o auto-teste): uma thread de reprodução antiga podia ser liberada de dentro dela mesma ao terminar,
  e o Qt abortava o programa. Agora threads antigas são liberadas só pela thread da interface, depois
  de terminarem de fato; quadros atrasados são identificados por um número de geração.
- O auto-teste registra mensagens críticas do Qt no `selftest.log` (diagnóstico no CI).
- CI: cada teste tem o código de saída verificado; o gerador de vídeos de teste usa o ffmpeg embutido;
  é possível publicar numa Release existente pelo "Run workflow" (`release_tag`).

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
