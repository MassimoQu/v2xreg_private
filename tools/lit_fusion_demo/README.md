# LitFusion demo (DeepTutor × gpt-researcher inspired)

目标：把

- DeepTutor 的「学习导读 / 问答 / 练习 / 可视化」
- gpt-researcher 的「问题拆解 → 来源收集 → 可溯源长报告」

融合成一个最小可用的 *文献管理 + 领域速通* demo：给定一个领域主题，自动从 **ArXiv**（可选再加 **Zotero**）拉候选文献，然后让 LLM **仅从候选集中**挑出 Key papers / Surveys / Benchmarks / Datasets，并生成可视化 + 7 天学习计划 + 自测题。

注：为了让 demo 更稳，这里默认用 **OpenAlex** 做“文献检索/聚合”（不需要额外 key），可选再启用 ArXiv（见下文）。

## 1) LLM 配置

### 1.1 推荐：本地 Ollama（不依赖 OpenAI 配额）

如果你本机装了 Ollama（默认地址 `http://localhost:11434`），建议直接用本地模型跑全流程：

```bash
export LITFUSION_PROVIDER=ollama
export OLLAMA_MODEL=deepseek-r1:32b        # 或 deepseek-r1:7b / deepseek-r1:70b
export OLLAMA_EMBED_MODEL=nomic-embed-text # 用于向量索引
```

### 1.2 OpenAI 兼容 / 中转站（可选）

默认会自动读取：

- `~/.codex/config.toml` 的 `base_url` / `model`
- `~/.codex/auth.json` 的 `OPENAI_API_KEY`

你也可以用环境变量覆盖：

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

另外支持：

- `LITFUSION_PROVIDER=auto`（默认）：优先 OpenAI 兼容接口，遇到鉴权/配额问题会自动回退到 Ollama
- `LITFUSION_PROVIDER=openai`
- `LITFUSION_PROVIDER=ollama`

## 2) 可选：Zotero 联动（只读搜索）

设置环境变量（至少前两个）：

- `ZOTERO_API_KEY`
- `ZOTERO_LIBRARY_ID`（userID 或 groupID）
- `ZOTERO_LIBRARY_TYPE`（`user` 或 `group`，默认 `user`）

## 3) 运行 demo

在仓库根目录运行：

```bash
python3 tools/lit_fusion_demo/cli.py research --topic "retrieval augmented generation"
```

如果想用 gpt-researcher 风格的 *Deep Research*（递归深挖 + 并发分支）：

```bash
python3 tools/lit_fusion_demo/cli.py research --topic "VGGT cooperative perception" --mode deep --breadth 4 --depth 2 --concurrency 2
```

输出在 `outputs/lit_fusion_demo/<topic-slug>/`：

- `report.md`：最终报告（含 Mermaid 图）
- `candidates.json`：候选来源（可溯源）
- `curation.json`：LLM 结构化挑选结果
- `deep_research.json`：`--mode deep` 时的分支/learning 记录
- `fulltext.json`：`--download-pdfs/--build-index` 时的下载与抽取统计
- `index.json`：`--build-index` 生成的向量索引（用于 RAG）

如果不想让 LLM 先做 query 规划（更快、更省 tokens）：

```bash
python3 tools/lit_fusion_demo/cli.py research --topic "retrieval augmented generation" --no-llm-plan
```

如果希望下载 PDF 并抽取全文：

```bash
python3 tools/lit_fusion_demo/cli.py research --topic "VGGT cooperative perception" --download-pdfs
```

如果希望进一步生成向量索引（用于后续 RAG 问答）：

```bash
export OLLAMA_EMBED_MODEL="nomic-embed-text"     # Ollama 模式
export OPENAI_EMBED_MODEL="text-embedding-3-small" # OpenAI 模式（可选）
python3 tools/lit_fusion_demo/cli.py research --topic "VGGT cooperative perception" --download-pdfs --build-index
```

## 4) 管理本地文献库（可选，但推荐）

### 4.1 从 Zotero 导出 CSL-JSON 并导入

在 Zotero 里导出（`CSL JSON`），然后：

```bash
python3 tools/lit_fusion_demo/cli.py library import-csl --input /path/to/zotero-export.json
python3 tools/lit_fusion_demo/cli.py library search --query "rag"
```

默认本地库位置：`outputs/lit_fusion_demo/library.json`

仓库里也附了一个很小的样例文件，方便先跑通流程：

```bash
python3 tools/lit_fusion_demo/cli.py library import-csl --input tools/lit_fusion_demo/sample/zotero_export_csl.json
```

### 4.2 直接从 Zotero API 同步（只读）

```bash
export ZOTERO_API_KEY=...
export ZOTERO_LIBRARY_ID=...
export ZOTERO_LIBRARY_TYPE=user  # or group

python3 tools/lit_fusion_demo/cli.py zotero sync --limit 300
```

### 4.3 把 curation 写回 Zotero（打 tag / 写 note / 建 collection）

默认是 dry-run，不会写入；加 `--apply` 才会真正修改你的 Zotero。

```bash
python3 tools/lit_fusion_demo/cli.py zotero annotate \
  --candidates outputs/lit_fusion_demo/retrieval-augmented-generation/candidates.json \
  --curation outputs/lit_fusion_demo/retrieval-augmented-generation/curation.json \
  --collection "LitFusion: RAG" \
  --apply
```

## 5) DeepTutor 风格问答（基于 report.md）

```bash
python3 tools/lit_fusion_demo/cli.py tutor ask --report outputs/lit_fusion_demo/retrieval-augmented-generation/report.md --question "这个领域常用 benchmark 是什么？"
```

## 5.1 全文 RAG 问答（基于 index.json）

先生成 `index.json`（见上面的 `--build-index`），然后：

```bash
python3 tools/lit_fusion_demo/cli.py rag ask --index outputs/lit_fusion_demo/retrieval-augmented-generation/index.json --question "RAG 的 benchmark 如何评测 citation accuracy？" --rewrite
```

你也可以把回答保存成文件（demo 里我在 VGGT 主题下生成了 `rag_q1.md/rag_q2.md/rag_q3.md`）：

```bash
python3 tools/lit_fusion_demo/cli.py rag ask --index outputs/lit_fusion_demo/vggt-cooperative-perception/index.json --question "V2X cooperative perception 的关键 dataset 是哪些？" --rewrite > outputs/lit_fusion_demo/vggt-cooperative-perception/rag_q1.md
```

## 5.2 学习强化（glossary/flashcards/选择题）

```bash
python3 tools/lit_fusion_demo/cli.py study pack --report outputs/lit_fusion_demo/retrieval-augmented-generation/report.md --out-dir outputs/lit_fusion_demo/retrieval-augmented-generation/study
```

## 6) 可选：启用 ArXiv 直连

如果你希望同时拉 ArXiv API（可能会被 429 限流，已做缓存/退避但仍不保证）：

```bash
export LITFUSION_USE_ARXIV=1
python3 tools/lit_fusion_demo/cli.py research --topic "retrieval augmented generation"
```

OpenAlex/ArXiv 建议加一个联系方式（可选）：

```bash
export OPENALEX_EMAIL="you@example.com"
export ARXIV_CONTACT_EMAIL="you@example.com"
```

## 7) 导出 BibTeX（方便 Zotero/Overleaf）

```bash
python3 tools/lit_fusion_demo/cli.py export bibtex \
  --candidates outputs/lit_fusion_demo/retrieval-augmented-generation/candidates.json \
  --curation outputs/lit_fusion_demo/retrieval-augmented-generation/curation.json \
  --out outputs/lit_fusion_demo/retrieval-augmented-generation/references.bib
```

## 8) 依赖提示（PDF 抽取）

`--download-pdfs/--build-index` 会尝试下载 PDF 并用 `pdftotext` 抽取全文（best-effort）。如果你发现 `texts/` 为空，请确认系统里有 `pdftotext`（通常来自 `poppler-utils`）。
