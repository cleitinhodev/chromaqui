# Changelog

## 3.2.0-beta.2 — 2026-11-09 (pré-release, versão de testes)

> Versão **de testes** (*pre-release*). A **3.1.0 continua sendo a versão estável** ("Latest").

### Novidade: versão nativa para Linux (x86_64)
- **Chromaqui-Linux-x86_64.AppImage** (um arquivo; `chmod +x` e execute) e **Chromaqui-Linux-x86_64.tar.gz**
  (pasta portátil + `install-desktop.sh` para o menu de aplicativos). Mesmos recursos do Windows: ffmpeg
  embutido, remoção por IA (onnxruntime), GPU via OpenCL com volta automática para a CPU, 8 idiomas.
- Compilado no Ubuntu 22.04 (glibc 2.35): roda no Ubuntu 22.04+, Debian 12+, Fedora, Mint, Arch etc.
- **X11 e Wayland**: usa o Wayland nativo quando disponível e cai para o X11/XWayland se precisar
  (`QT_QPA_PLATFORM=xcb` força o X11). Ícone e atalho `.desktop` (ícones hicolor 16–512 px).
- Pastas do usuário no padrão Linux: configurações e logs em `~/.config/Chromaqui` (respeita
  `$XDG_CONFIG_HOME`; as preferências antigas de `~/.config/bugzinho/Chromaqui.conf` são migradas), modelos
  de IA em `~/.local/share/Chromaqui/models` (`$XDG_DATA_HOME`). No Windows nada muda (`%APPDATA%\Chromaqui`).
- O ffmpeg embutido ganha permissão de execução automaticamente (cópia em `~/.cache/Chromaqui` se a pasta
  for somente leitura).
- Aviso de atualização mostra o arquivo certo para o sistema (AppImage no Linux, .zip no Windows).

### Correções
- Dependência do Qt limitada a PySide6 < 6.12 (a 6.12.0 com Python 3.11 podia fechar com erro ao sair).

### CI
- Novo job Linux no `release.yml` (Ubuntu 22.04): testes completos, auto-teste do executável e do AppImage
  (offscreen e X11/Xvfb) e envio do AppImage e do .tar.gz para a Release. A publicação agora acontece num
  job único depois de Windows e Linux passarem.

## 3.2.0-beta.1 — 2026-11-04 (pré-release, versão de testes)

> Versão **de testes**: publicada como *pre-release*. A **3.1.0 continua sendo a versão estável**
> ("Latest" nas Releases). Os recursos marcados *(beta)* podem mudar até a 3.2.0.

### Já existia (sem mudanças)
- **Exportar só um trecho**: os campos *De / Até / 1 a cada N* em "Opções de exportação" já exportam
  um intervalo do vídeo (`ExportOptions.start/end/step`).

### Novidades (beta)
- **Recorte que acompanha o objeto** — em "Recorte da área exportada", *Movimento*:
  - **Seguir o objeto**: a área (tamanho fixo = o maior necessário + margem) acompanha o objeto,
    com **suavização** ajustável; **Analisar movimento** mostra o caminho na prévia.
  - **Quadros-chave**: posicione a área em alguns quadros (mover/redimensionar marca o quadro) e ela é
    interpolada entre eles; marcar/remover/limpar quadros-chave.
- **Retoque com pincel**: pinte na prévia o que deve ficar (**Manter**), sumir (**Remover**) ou voltar ao
  automático (**Borracha**); tamanho e dureza, máscara fixa (todos os quadros) ou só no quadro atual.
  Atalhos `B`, `[` e `]`.
- **Sprite sheet (PNG + JSON)**: novo formato com colunas automáticas ou fixas, espaçamento, tamanho
  máximo (divide em várias folhas), *trim* de transparência e JSON do **TexturePacker** (hash ou array;
  Phaser, Pixi, Godot, Unity).
- **Exportação em lote**: fila de vídeos (arrastar e soltar), ajustes atuais ou um preset `.json`,
  recorte salvo por tamanho de vídeo, progresso por vídeo e total, cancelar.
- **Remoção por IA (sem tela verde)**: *Origem do recorte* = IA, com **onnxruntime** (CPU). Modelos
  *Pessoas — MODNet* e *Objetos — U²-Net pequeno*, baixados **uma vez, no primeiro uso**, para
  `%APPDATA%\Chromaqui\models` (com verificação SHA-256 e cancelamento); depois funciona offline.
  Refinamento de borda, limpeza, retoque e o resto continuam valendo.
- **Sombra projetada / brilho neon** atrás do objeto (cor, desfoque, deslocamento, opacidade, expansão),
  na prévia e, se marcado, na exportação.
- **Desfazer/Refazer** (`Ctrl+Z`, `Ctrl+Y`/`Ctrl+Shift+Z`) para ajustes, recorte, quadros-chave e pincel;
  **Comparar** (prévia dividida, divisória arrastável) e botão **Antes** (segure para ver o original).
- **Verificação de atualizações**: consulta as Releases do GitHub em segundo plano (desligável em
  ⚙ Configurações → Atualizações, com opção de incluir betas e "Verificar agora"); sem internet, nada acontece.
- "beta" aparece no título da janela e no **Sobre**.

### Interno
- Todas as frases novas nos 8 idiomas; novos testes (`tests/test_features.py`, fluxo de interface
  `test_ui_flows.py beta`, auto-teste do `.exe` cobrindo sprite sheet, pincel, brilho, seguir objeto,
  desfazer, lote e IA).
- CI: tags `-alpha`/`-beta`/`-rc` são publicadas como **pre-release** sem virar a "Latest".
- As threads novas (análise de movimento, download do modelo, lote, atualizações) seguem o mesmo
  padrão seguro da 3.0.2.

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
