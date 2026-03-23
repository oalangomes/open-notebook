#!/bin/bash
# Script de Build e Deploy do Open Notebook com Ollama Local

set -e  # Exit on error

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

clear

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                                                            ║${NC}"
echo -e "${BLUE}║   🚀 Open Notebook - Build & Deploy (Local Ollama)        ║${NC}"
echo -e "${BLUE}║                                                            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Validações
echo -e "${YELLOW}⏳ Validando pré-requisitos...${NC}"

# Verificar Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker não encontrado. Instale Docker antes de continuar.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker instalado${NC}"

# Verificar Ollama rodando
echo -e "${YELLOW}⏳ Verificando Ollama em http://localhost:11434...${NC}"
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "${RED}❌ Ollama não está respondendo em http://localhost:11434${NC}"
    echo -e "${YELLOW}   Execute: ollama serve${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Ollama está rodando${NC}"

cd "$(dirname "$0")"

echo ""
echo -e "${YELLOW}📦 Etapa 1/3: Building Docker images...${NC}"
docker compose build --no-cache

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Build falhou${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Build concluído${NC}"

echo ""
echo -e "${YELLOW}🚀 Etapa 2/3: Iniciando containers...${NC}"
docker compose up -d

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Falha ao iniciar containers${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Containers iniciados${NC}"

echo ""
echo -e "${YELLOW}⏳ Etapa 3/3: Aguardando inicialização dos serviços...${NC}"
sleep 3

# Aguardar SurrealDB
echo -e "${YELLOW}   Aguardando SurrealDB...${NC}"
for i in {1..30}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}   ✓ SurrealDB pronto${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}   ⚠ SurrealDB demorou muito para iniciar${NC}"
    fi
    sleep 1
done

# Aguardar API
echo -e "${YELLOW}   Aguardando API...${NC}"
for i in {1..30}; do
    if curl -s http://localhost:5055/docs > /dev/null 2>&1; then
        echo -e "${GREEN}   ✓ API pronto${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}   ⚠ API demorou muito para iniciar${NC}"
    fi
    sleep 1
done

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✓ Deployment concluído com sucesso!                     ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${BLUE}📡 URLs de Acesso:${NC}"
echo -e "   ${YELLOW}Frontend:${NC}      http://localhost:3000"
echo -e "   ${YELLOW}API Backend:${NC}   http://localhost:5055"
echo -e "   ${YELLOW}API Docs:${NC}      http://localhost:5055/docs"
echo -e "   ${YELLOW}Database:${NC}      http://localhost:8000"
echo -e "   ${YELLOW}Ollama:${NC}        http://localhost:11434"
echo ""

echo -e "${BLUE}🛠️  Comandos úteis:${NC}"
echo -e "   ${YELLOW}Ver logs:${NC}"
echo -e "      docker compose logs -f open_notebook"
echo -e "      docker compose logs -f surrealdb"
echo ""
echo -e "   ${YELLOW}Parar:${NC}"
echo -e "      docker compose down"
echo ""
echo -e "   ${YELLOW}Reiniciar:${NC}"
echo -e "      docker compose restart"
echo ""

echo -e "${BLUE}⚙️  Próximos passos:${NC}"
echo -e "   1. Acesse ${YELLOW}http://localhost:3000${NC} no navegador"
echo -e "   2. Faça login (padrão: password)"
echo -e "   3. Vá em ${YELLOW}Settings → API Keys${NC}"
echo -e "   4. Adicione Ollama com URL: ${YELLOW}http://host.docker.internal:11434${NC}"
echo ""
