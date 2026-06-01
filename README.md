# Denunciados de 01/01/2025 a 31/05/2026 — Promotoria Crimiminal de Piracicaba

Painel HTML interativo rodando PyScript + Chart.js.
Não requer instalação.

## Estrutura

```
/
├── index.html        # layout + Chart.js + PyScript
├── style.css         # tema corporativo
├── main.py           # lógica Python: carga, fase, filtros, gráficos, tabela
├── pyscript.toml     # declara pacotes (pandas)
└── dados/
    └── relatorio.csv # base de dados
```

## Rodar localmente

O `fetch()` exige servidor HTTP — não abre direto com `file://`.

**Python (mais simples):**
```bash
cd /caminho/para/dash_denunciados
python3 -m http.server 8080
# Abrir: http://localhost:8080
```

**Node.js:**
```bash
npx serve .
```

O primeiro carregamento baixa o runtime Pyodide + pandas (~10 MB). Após isso a interação é fluida.

## Atualizar a base de dados

1. Exportar novo relatório do SAJ no mesmo formato CSV (16 colunas, UTF-8).
2. Substituir `dados/relatorio.csv` pelo novo arquivo.
3. Fazer commit e push.
4. GitHub Pages publicará automaticamente (veja abaixo).

## Publicar no GitHub Pages

1. Criar repositório público no GitHub.
2. `git init && git add . && git commit -m "Dashboard inicial"`
3. `git remote add origin <url> && git push -u origin main`
4. No repositório → Settings → Pages → Branch: `main`, pasta: `/ (root)` → Save.
5. Aguardar ~1 min. O painel estará em `https://<usuario>.github.io/<repo>/`.

## Decisão de sigilo

A base não contém nomes de partes ou testemunhas. O link e-SAJ é autenticado pelo próprio sistema.

## Notas técnicas

- PyScript: `https://pyscript.net/releases/2024.11.1/core.js` — verificar versão mais recente em [pyscript.net](https://pyscript.net).
- Gargalo definido como: `sem denúncia AND dias_desde_distribuição > 365` (ajustável em `main.py`).
- Paginação: 50 feitos por página.
