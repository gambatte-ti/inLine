# 🎪 Festival Queue System (Offline First)

Sistema SaaS **local/offline** para gestão de filas de alimentação em festivais, feiras, eventos e bancas de comida.

Projetado para:

- ⚡ Alta concorrência
- 🔒 Consistência forte
- 🧠 Comportamento determinístico
- 📦 Execução local (SQLite)
- 🔁 Operação offline
- 🧩 Arquitetura modular
- 🧯 Tolerância a falhas

---

## 🎯 Objetivo do Sistema

Gerenciar pedidos em ambientes de alto fluxo (festivais), garantindo:

- Fila organizada
- Prioridade preferencial
- Produção paralela por estação
- Impressão desacoplada
- Painel de cozinha por prato
- Baixa latência
- Zero dependência externa

---

## 🏗️ Arquitetura Geral

```
[ CAIXA ] → Pedido
           ↓
    Explosão por prato
           ↓
   Filas unitárias por estação
           ↓
[ COZINHA POR PRATO ]
           ↓
      Finalização
           ↓
    Impressão / Retirada
```

---

## 🧱 Conceitos-Chave

### Pedido

- Representa a compra no caixa
- Contém múltiplos pratos
- Possui tipo:
  - NORMAL
  - PREFERENCIAL

### Prato

- Item do cardápio
- Preço individual
- Produção independente

### ItemPedido

- Relação Pedido ↔ Prato
- Quantidade
- Valor unitário
- Valor total

### FilaPrato

- Unidade de produção
- Cada prato gera uma fila
- Cada quantidade = uma posição de fila

---

## 🧠 Princípios Arquiteturais

- **Service Layer** como núcleo de negócio
- **Views burros**
- **Transações atômicas**
- **Estado > lock**
- **Update condicional**
- **Sem filas distribuídas**
- **Sem Redis**
- **Sem Kafka**
- **Sem dependências externas**

---

## 🧩 Componentes

### Caixa

Funções:

- Cadastro de pratos
- Criação de pedidos
- Cálculo automático:
  - total por prato
  - total geral

### Sistema

- Explode pedido em filas unitárias
- Cria fila por prato
- Distribui produção

### Cozinha

- Painel por estação (prato)
- Fila própria
- Prioridade preferencial
- Ordem determinística

### Impressão

- Desacoplada
- Evento por estado
- Pode ser:
  - térmica
  - ticket
  - comanda

---

## 📦 Modelo de Dados (Resumo)

```
Pedido
  - id
  - tipo (NORMAL | PREFERENCIAL)
  - status
  - total

Prato
  - id
  - nome
  - preco
  - ativo

ItemPedido
  - pedido
  - prato
  - quantidade
  - valor_unitario
  - valor_total

FilaPrato
  - pedido
  - prato
  - status
  - created_at
  - started_at
  - finished_at
```

---

## 🔁 Fluxo Operacional

### 1️⃣ Caixa

- Seleciona pratos
- Define quantidades
- Sistema calcula valores
- Pedido criado

### 2️⃣ Explosão

Pedido vira filas:

Exemplo:

```
Pedido:
2x Pastel
1x Caldo

Fila:
Pastel #1
Pastel #2
Caldo #1
```

---

### 3️⃣ Produção

Cada estação consome sua própria fila:

- Estação do pastel → só vê pastel
- Estação do caldo → só vê caldo

---

### 4️⃣ Painel da Cozinha

Endpoint:

```
GET /api/cozinha/<prato_id>/painel/
```

Retorna:

- em_producao
- pendentes

Com prioridade:

1. Preferencial
2. Normal

---

### 5️⃣ Finalização

```
POST /api/cozinha/finalizar/<fila_prato_id>/
```

Estado:

- PENDENTE → EM_PRODUCAO → RETIRADO

---

## ⚡ Concorrência

- SQLite em WAL
- Transações atômicas
- UPDATE condicional
- Sem deadlock lógico
- Sem race condition
- Sem starvation

---

## 🧪 Garantias

| Requisito    | Garantia               |
| ------------ | ---------------------- |
| Ordem        | Determinística         |
| Concorrência | Segura                 |
| Offline      | Total                  |
| Escala       | Horizontal por estação |
| Falhas       | Isoladas               |
| Latência     | Baixa                  |

---

## 🧠 Filosofia

> "Não é um CRUD. É um sistema de produção."

> "Fila não é tabela. É estado."

> "Concorrência não se resolve com lock, se resolve com modelo."

---

## 🎪 Casos de Uso

- Festivais
- Feiras
- Eventos
- Food trucks
- Praças de alimentação
- Shows
- Eventos esportivos

---

## 🚀 Roadmap

- WebSocket local
- Auto-refresh painel
- Dashboard geral da cozinha
- Balanceamento de estação
- Métricas de produção
- TMA por prato
- Heatmap de pedidos
- BI local

---

## 🧬 Stack

- Python
- Django 5.x
- Django REST Framework
- SQLite (WAL)
- Execução local
- HTML5
- CSS3 (Tailwind)
- JavaScript

---

## 🧪 Ambiente Local

Crie a virtualenv na **raiz do repositório**:

```bash
cd /home/cassiano/workspace/inLine
python3 -m venv .venv
```

Se o Python reclamar de `ensurepip`, instale antes os pacotes de sistema:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip
```

Depois ative a virtualenv e instale as dependências do projeto:

```bash
source .venv/bin/activate
pip install -r inLine/requirements.txt
```

O projeto Django fica dentro da pasta `inLine/`, então os comandos de gestão devem ser rodados nela:

```bash
cd inLine
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

---

## ✅ Testes

A suíte foi organizada em `inLine/core/tests/` e cobre:

- services de criação/finalização/retirada/TMA
- APIs principais de cardápio, pedidos, atendimento, produção e monitor
- middleware de licença
- smoke tests das páginas HTML

Para rodar:

```bash
cd /home/cassiano/workspace/inLine/inLine
make test
```

---

## 🛡️ Restrições de Projeto

❌ Sem Redis
❌ Sem Memcached
❌ Sem Kafka
❌ Sem RabbitMQ
❌ Sem cloud
❌ Sem serviços externos
❌ Sem banco distribuído

✔ 100% local
✔ Offline-first
✔ Determinístico
✔ Reprodutível

---

## 🏁 Conclusão

Este projeto implementa uma **arquitetura real de produção para festivais**, não um sistema acadêmico.

Ele resolve:

- Fila real
- Produção real
- Concorrência real
- Escala real
- Offline real

Com simplicidade estrutural, robustez lógica e previsibilidade operacional.

---

🎯 **Festival-grade system. Production-ready architecture. Offline-first by design.**
