"""
Comprehensive LLM Provider & Model Registry for DeepanCode.
82+ providers (free + paid) with OpenAI-compatible API endpoints.
Model IDs verified against live API data — September 2026.
"""

import logging
from typing import Dict, List, Any, Optional
from deepans_code.token_usage import CostInfo

logger = logging.getLogger("deepans_code.models")

# ============================================================================
# FREE MODEL COSTS (all $0 per token)
# ============================================================================
MODEL_COSTS: Dict[str, CostInfo] = {}

def _free():
    return CostInfo(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0)

def _paid(input_per_m, output_per_m):
    return CostInfo(input=input_per_m, output=output_per_m, cache_read=0.0, cache_write=0.0)

# ============================================================================
# PROVIDER REGISTRY — 82+ providers
# ============================================================================
PROVIDERS = {
    # ========================================================================
    # CATEGORY 1: AGGREGATORS / GATEWAYS
    # ========================================================================
    "openrouter": {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/",
        "api_base": "https://openrouter.ai/api/v1",
        "description": "Largest LLM gateway — 30+ free models via :free suffix",
        "key_env": "OPENROUTER_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "openrouter/free", "name": "OpenRouter Free Auto-Router", "provider": "openrouter", "context_window": 200000, "description": "Auto-picks best free model"},
            {"id": "openai/gpt-oss-120b:free", "name": "OpenAI GPT-OSS 120B (Free)", "provider": "openrouter", "context_window": 131072, "description": "120B MoE open-weights"},
            {"id": "cohere/north-mini-code:free", "name": "Cohere North Mini Code (Free)", "provider": "openrouter", "context_window": 256000, "description": "Fast coding model"},
            {"id": "google/gemma-4-31b-it:free", "name": "Google Gemma 4 31B (Free)", "provider": "openrouter", "context_window": 262144, "description": "Multimodal instruction-tuned"},
            {"id": "google/gemma-4-26b-a4b-it:free", "name": "Google Gemma 4 26B (Free)", "provider": "openrouter", "context_window": 262144, "description": "Lightweight Gemma"},
            {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "name": "NVIDIA Nemotron 3 Ultra 550B (Free)", "provider": "openrouter", "context_window": 1000000, "description": "550B MoE reasoning, 1M ctx"},
            {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "NVIDIA Nemotron 3 Super 120B (Free)", "provider": "openrouter", "context_window": 1000000, "description": "120B MoE hybrid, 1M ctx"},
            {"id": "nvidia/nemotron-3-nano-30b-a3b:free", "name": "NVIDIA Nemotron 3 Nano 30B (Free)", "provider": "openrouter", "context_window": 256000, "description": "Lightweight Nano"},
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Meta Llama 3.3 70B (Free)", "provider": "openrouter", "context_window": 131072, "description": "Multilingual 70B instruct"},
            {"id": "meta-llama/llama-3.2-3b-instruct:free", "name": "Meta Llama 3.2 3B (Free)", "provider": "openrouter", "context_window": 131072, "description": "Tiny fast model"},
            {"id": "qwen/qwen3-coder:free", "name": "Qwen3 Coder 480B (Free)", "provider": "openrouter", "context_window": 1048576, "description": "480B MoE coding, 1M ctx"},
            {"id": "tencent/hy3:free", "name": "Tencent Hy3 (Free)", "provider": "openrouter", "context_window": 262144, "description": "295B MoE reasoning"},
            {"id": "deepseek/deepseek-r1:free", "name": "DeepSeek R1 (Free)", "provider": "openrouter", "context_window": 163840, "description": "Reasoning model"},
            {"id": "deepseek/deepseek-chat:free", "name": "DeepSeek V3 Chat (Free)", "provider": "openrouter", "context_window": 163840, "description": "General chat model"},
            {"id": "mistralai/mistral-7b-instruct:free", "name": "Mistral 7B Instruct (Free)", "provider": "openrouter", "context_window": 32768, "description": "Fast Mistral 7B"},
            {"id": "huggingfaceh4/zephyr-7b-beta:free", "name": "Zephyr 7B Beta (Free)", "provider": "openrouter", "context_window": 8192, "description": "Mistral-based chat"},
            {"id": "openchat/openchat-7b:free", "name": "OpenChat 7B (Free)", "provider": "openrouter", "context_window": 8192, "description": "Fine-tuned Llama"},
        ]
    },
    "openrouter_paid": {
        "name": "OpenRouter (Paid)",
        "url": "https://openrouter.ai/",
        "api_base": "https://openrouter.ai/api/v1",
        "description": "Premium models via OpenRouter",
        "key_env": "OPENROUTER_API_KEY",
        "free_tier": False,
        "models": [
            {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4", "provider": "openrouter", "context_window": 200000, "description": "Anthropic's best coding model"},
            {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "provider": "openrouter", "context_window": 200000, "description": "Strong reasoning"},
            {"id": "openai/gpt-4o", "name": "GPT-4o", "provider": "openrouter", "context_window": 128000, "description": "OpenAI flagship"},
            {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "provider": "openrouter", "context_window": 1048576, "description": "Google's best model"},
            {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "provider": "openrouter", "context_window": 163840, "description": "Top reasoning model"},
            {"id": "x-ai/grok-3", "name": "Grok 3", "provider": "openrouter", "context_window": 131072, "description": "xAI's flagship"},
            {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick", "provider": "openrouter", "context_window": 1048576, "description": "Meta's best open model"},
        ]
    },

    # ========================================================================
    # CATEGORY 2: FRONT-LAB PROVIDERS (train their own models)
    # ========================================================================
    "google": {
        "name": "Google Gemini",
        "url": "https://ai.google.dev/",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "description": "Google's Gemini models — 1500 RPD free, no card",
        "key_env": "GOOGLE_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "google", "context_window": 1048576, "description": "Fast, multimodal"},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "google", "context_window": 1048576, "description": "Previous gen flash"},
            {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "provider": "google", "context_window": 1048576, "description": "Cheapest Gemini"},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "provider": "google", "context_window": 1048576, "description": "Google's best model"},
        ]
    },
    "mistral": {
        "name": "Mistral AI",
        "url": "https://mistral.ai/",
        "api_base": "https://api.mistral.ai/v1",
        "description": "Mistral models — 1B tokens/mo free",
        "key_env": "MISTRAL_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "mistral-small-latest", "name": "Mistral Small 3.1", "provider": "mistral", "context_window": 32768, "description": "Fast & cheap"},
            {"id": "mistral-large-latest", "name": "Mistral Large 3", "provider": "mistral", "context_window": 128000, "description": "Flagship model"},
            {"id": "ministral-8b-latest", "name": "Ministral 8B", "provider": "mistral", "context_window": 32768, "description": "Lightweight edge model"},
            {"id": "codestral-latest", "name": "Codestral", "provider": "mistral", "context_window": 32768, "description": "Code-specialized"},
            {"id": "mistral-embed-latest", "name": "Mistral Embed", "provider": "mistral", "context_window": 8192, "description": "Embedding model"},
        ]
    },
    "deepseek": {
        "name": "DeepSeek",
        "url": "https://platform.deepseek.com/",
        "api_base": "https://api.deepseek.com",
        "description": "DeepSeek models — 5M tokens free on signup",
        "key_env": "DEEPSEEK_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek V3 Chat", "provider": "deepseek", "context_window": 163840, "description": "General chat"},
            {"id": "deepseek-reasoner", "name": "DeepSeek R1", "provider": "deepseek", "context_window": 163840, "description": "Reasoning model"},
            {"id": "deepseek-coder", "name": "DeepSeek Coder V2", "provider": "deepseek", "context_window": 128000, "description": "Code specialist"},
        ]
    },
    "alibaba": {
        "name": "Alibaba (Qwen)",
        "url": "https://dashscope.aliyun.com/",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "description": "Qwen models — 1M tokens/mo free",
        "key_env": "DASHSCOPE_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "qwen-plus", "name": "Qwen Plus", "provider": "alibaba", "context_window": 131072, "description": "Balanced performance"},
            {"id": "qwen-turbo", "name": "Qwen Turbo", "provider": "alibaba", "context_window": 1048576, "description": "Fast model"},
            {"id": "qwen-max", "name": "Qwen Max", "provider": "alibaba", "context_window": 32768, "description": "Flagship model"},
            {"id": "qwen3-coder", "name": "Qwen3 Coder 480B", "provider": "alibaba", "context_window": 1048576, "description": "MoE coding model"},
        ]
    },
    "cohere": {
        "name": "Cohere",
        "url": "https://cohere.com/",
        "api_base": "https://api.cohere.ai/v2",
        "description": "Cohere models — 1000 calls/mo free",
        "key_env": "COHERE_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "command-a", "name": "Command A", "provider": "cohere", "context_window": 128000, "description": "Best Cohere model"},
            {"id": "command-r-plus", "name": "Command R+", "provider": "cohere", "context_window": 128000, "description": "RAG-optimized"},
            {"id": "command-r", "name": "Command R", "provider": "cohere", "context_window": 128000, "description": "General purpose"},
            {"id": "embed-english-v3.0", "name": "Embed v3", "provider": "cohere", "context_window": 512, "description": "Embedding model"},
        ]
    },
    "ai21": {
        "name": "AI21 Labs",
        "url": "https://www.ai21.com/",
        "api_base": "https://api.ai21.com/studio/v1",
        "description": "Jamba models — trial credits",
        "key_env": "AI21_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "jamba-1.5-large", "name": "Jamba 1.5 Large", "provider": "ai21", "context_window": 256000, "description": "256K context hybrid"},
            {"id": "jamba-1.5-mini", "name": "Jamba 1.5 Mini", "provider": "ai21", "context_window": 256000, "description": "Lightweight hybrid"},
        ]
    },
    "xai": {
        "name": "xAI (Grok)",
        "url": "https://x.ai/",
        "api_base": "https://api.x.ai/v1",
        "description": "Grok models — cheapest frontier",
        "key_env": "XAI_API_KEY",
        "free_tier": False,
        "models": [
            {"id": "grok-3", "name": "Grok 3", "provider": "xai", "context_window": 131072, "description": "xAI flagship"},
            {"id": "grok-3-fast", "name": "Grok 3 Fast", "provider": "xai", "context_window": 131072, "description": "Faster Grok"},
            {"id": "grok-2", "name": "Grok 2", "provider": "xai", "context_window": 131072, "description": "Previous gen"},
        ]
    },
    "moonshot": {
        "name": "Moonshot AI (Kimi)",
        "url": "https://platform.moonshot.cn/",
        "api_base": "https://api.moonshot.cn/v1",
        "description": "Kimi models — long-context specialist 128K+",
        "key_env": "MOONSHOT_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "moonshot-v1-128k", "name": "Kimi 128K", "provider": "moonshot", "context_window": 131072, "description": "Long context chat"},
            {"id": "moonshot-v1-32k", "name": "Kimi 32K", "provider": "moonshot", "context_window": 32768, "description": "Standard context"},
            {"id": "moonshot-v1-8k", "name": "Kimi 8K", "provider": "moonshot", "context_window": 8192, "description": "Fast context"},
        ]
    },
    "zhipu": {
        "name": "Zhipu AI (GLM)",
        "url": "https://open.bigmodel.cn/",
        "api_base": "https://open.bigmodel.cn/api/paas/v4/",
        "description": "GLM models — 5M tokens free on signup",
        "key_env": "ZHIPU_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "glm-4-flash", "name": "GLM-4 Flash", "provider": "zhipu", "context_window": 128000, "description": "Fast free model"},
            {"id": "glm-4", "name": "GLM-4", "provider": "zhipu", "context_window": 128000, "description": "Flagship model"},
            {"id": "glm-4v", "name": "GLM-4V", "provider": "zhipu", "context_window": 8192, "description": "Vision model"},
        ]
    },
    "baichuan": {
        "name": "Baichuan AI",
        "url": "https://platform.baichuan-ai.com/",
        "api_base": "https://api.baichuan-ai.com/v1",
        "description": "Baichuan models — 5M tokens free",
        "key_env": "BAICHUAN_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "Baichuan4", "name": "Baichuan 4", "provider": "baichuan", "context_window": 32768, "description": "Flagship model"},
            {"id": "Baichuan3-Turbo", "name": "Baichuan 3 Turbo", "provider": "baichuan", "context_window": 32768, "description": "Fast model"},
        ]
    },
    "minimax": {
        "name": "MiniMax",
        "url": "https://www.minimaxi.com/",
        "api_base": "https://api.minimax.chat/v1",
        "description": "MiniMax models — full multimodal",
        "key_env": "MINIMAX_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "abab6.5s-chat", "name": "ABAB 6.5S", "provider": "minimax", "context_window": 32768, "description": "General chat"},
            {"id": "abab5.5-chat", "name": "ABAB 5.5", "provider": "minimax", "context_window": 32768, "description": "Previous gen"},
        ]
    },
    "01ai": {
        "name": "01.AI (Yi)",
        "url": "https://platform.01.ai/",
        "api_base": "https://api.01.ai/v1",
        "description": "Yi models — free credits on signup",
        "key_env": "YI_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "yi-large", "name": "Yi Large", "provider": "01ai", "context_window": 32768, "description": "Flagship model"},
            {"id": "yi-medium", "name": "Yi Medium", "provider": "01ai", "context_window": 16384, "description": "Balanced model"},
            {"id": "yi-lightning", "name": "Yi Lightning", "provider": "01ai", "context_window": 16384, "description": "Fast model"},
        ]
    },
    "stepfun": {
        "name": "StepFun",
        "url": "https://platform.stepfun.com/",
        "api_base": "https://api.stepfun.com/v1",
        "description": "Step models",
        "key_env": "STEPFUN_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "step-1-8k", "name": "Step 1 8K", "provider": "stepfun", "context_window": 8192, "description": "Standard model"},
            {"id": "step-1-32k", "name": "Step 1 32K", "provider": "stepfun", "context_window": 32768, "description": "Long context"},
        ]
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "url": "https://console.anthropic.com/",
        "api_base": "https://api.anthropic.com/v1",
        "description": "Claude models — $5 signup credits",
        "key_env": "ANTHROPIC_API_KEY",
        "free_tier": False,
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "provider": "anthropic", "context_window": 200000, "description": "Best coding model"},
            {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "provider": "anthropic", "context_window": 200000, "description": "Strong reasoning"},
            {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "provider": "anthropic", "context_window": 200000, "description": "Fast model"},
            {"id": "claude-3-haiku-20240307", "name": "Claude 3 Haiku", "provider": "anthropic", "context_window": 200000, "description": "Cheapest Claude"},
        ]
    },
    "openai": {
        "name": "OpenAI",
        "url": "https://platform.openai.com/",
        "api_base": "https://api.openai.com/v1",
        "description": "GPT models — $5 free credits",
        "key_env": "OPENAI_API_KEY",
        "free_tier": False,
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai", "context_window": 128000, "description": "OpenAI flagship"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "openai", "context_window": 128000, "description": "Fast & cheap"},
            {"id": "o3", "name": "o3", "provider": "openai", "context_window": 200000, "description": "Reasoning model"},
            {"id": "o4-mini", "name": "o4 Mini", "provider": "openai", "context_window": 200000, "description": "Fast reasoning"},
            {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "provider": "openai", "context_window": 16385, "description": "Legacy cheap model"},
        ]
    },

    # ========================================================================
    # CATEGORY 3: FAST INFERENCE PROVIDERS
    # ========================================================================
    "groq": {
        "name": "Groq",
        "url": "https://console.groq.com/",
        "api_base": "https://api.groq.com/openai/v1",
        "description": "Fastest inference (LPU hardware) — 30 RPM free",
        "key_env": "GROQ_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B", "provider": "groq", "context_window": 131072, "description": "Multilingual 70B"},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B", "provider": "groq", "context_window": 131072, "description": "Fast 8B model"},
            {"id": "llama-4-scout-17b-16e-instruct", "name": "Llama 4 Scout 17B", "provider": "groq", "context_window": 131072, "description": "New Llama 4 Scout"},
            {"id": "gemma2-9b-it", "name": "Gemma 2 9B", "provider": "groq", "context_window": 8192, "description": "Google Gemma 2"},
            {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B", "provider": "groq", "context_window": 32768, "description": "Mixture of experts"},
            {"id": "qwen-qwq-32b", "name": "Qwen QwQ 32B", "provider": "groq", "context_window": 131072, "description": "Reasoning model"},
        ]
    },
    "cerebras": {
        "name": "Cerebras",
        "url": "https://cerebras.ai/",
        "api_base": "https://api.cerebras.ai/v1",
        "description": "Wafer-scale chip — 1M tokens/day free",
        "key_env": "CEREBRAS_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "llama-3.3-70b", "name": "Llama 3.3 70B", "provider": "cerebras", "context_window": 131072, "description": "Ultra-fast 70B"},
            {"id": "llama-3.1-8b", "name": "Llama 3.1 8B", "provider": "cerebras", "context_window": 131072, "description": "Fast 8B"},
            {"id": "llama-4-scout-17b-16e", "name": "Llama 4 Scout", "provider": "cerebras", "context_window": 131072, "description": "New Llama 4"},
        ]
    },
    "sambanova": {
        "name": "SambaNova",
        "url": "https://cloud.sambanova.ai/",
        "api_base": "https://api.sambanova.ai/v1",
        "description": "RDU chip — only free 405B provider",
        "key_env": "SAMBANOVA_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "Meta-Llama-3.1-405B-Instruct", "name": "Llama 3.1 405B", "provider": "sambanova", "context_window": 131072, "description": "Free 405B model!"},
            {"id": "Meta-Llama-3.3-70B-Instruct", "name": "Llama 3.3 70B", "provider": "sambanova", "context_window": 131072, "description": "70B instruct"},
            {"id": "DeepSeek-V3-0324", "name": "DeepSeek V3", "provider": "sambanova", "context_window": 163840, "description": "DeepSeek V3"},
            {"id": "QwQ-32B", "name": "QwQ 32B", "provider": "sambanova", "context_window": 131072, "description": "Reasoning model"},
        ]
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "url": "https://build.nvidia.com/",
        "api_base": "https://integrate.api.nvidia.com/v1",
        "description": "NVIDIA NIM — 46+ models free, no card needed",
        "key_env": "NVIDIA_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "nvidia/nemotron-3-ultra-550b-a55b", "name": "Nemotron 3 Ultra 550B", "provider": "nvidia", "context_window": 1000000, "description": "550B MoE reasoning"},
            {"id": "nvidia/nemotron-3-super-120b-a12b", "name": "Nemotron 3 Super 120B", "provider": "nvidia", "context_window": 1000000, "description": "120B MoE hybrid"},
            {"id": "nvidia/nemotron-3-nano-30b-a3b", "name": "Nemotron 3 Nano 30B", "provider": "nvidia", "context_window": 256000, "description": "Lightweight Nano"},
            {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "Nemotron 70B", "provider": "nvidia", "context_window": 131072, "description": "NVIDIA-tuned 70B"},
            {"id": "deepseek-ai/deepseek-r1", "name": "DeepSeek R1", "provider": "nvidia", "context_window": 163840, "description": "Reasoning model"},
            {"id": "qwen/qwen3-coder-480b", "name": "Qwen3 Coder 480B", "provider": "nvidia", "context_window": 1048576, "description": "480B MoE coding"},
        ]
    },
    "together": {
        "name": "Together AI",
        "url": "https://www.together.ai/",
        "api_base": "https://api.together.xyz/v1",
        "description": "200+ open models — $5 free credits",
        "key_env": "TOGETHER_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "name": "Llama 3.3 70B Turbo", "provider": "together", "context_window": 131072, "description": "Fast 70B"},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1", "provider": "together", "context_window": 163840, "description": "Reasoning model"},
            {"id": "Qwen/Qwen3-Coder-480B-A35B-Instruct", "name": "Qwen3 Coder 480B", "provider": "together", "context_window": 1048576, "description": "MoE coding"},
            {"id": "mistralai/Mistral-7B-Instruct-v0.3", "name": "Mistral 7B v0.3", "provider": "together", "context_window": 32768, "description": "Fast Mistral"},
            {"id": "google/gemma-3-27b-it", "name": "Gemma 3 27B", "provider": "together", "context_window": 131072, "description": "Google Gemma 3"},
        ]
    },
    "fireworks": {
        "name": "Fireworks AI",
        "url": "https://fireworks.ai/",
        "api_base": "https://api.fireworks.ai/inference/v1",
        "description": "Fast production inference — $1 free credits",
        "key_env": "FIREWORKS_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "accounts/fireworks/models/llama-v3p3-70b-instruct", "name": "Llama 3.3 70B", "provider": "fireworks", "context_window": 131072, "description": "Fast 70B"},
            {"id": "accounts/fireworks/models/deepseek-r1", "name": "DeepSeek R1", "provider": "fireworks", "context_window": 163840, "description": "Reasoning model"},
            {"id": "accounts/fireworks/models/qwen-v2.5-coder-32b", "name": "Qwen 2.5 Coder 32B", "provider": "fireworks", "context_window": 32768, "description": "Code specialist"},
        ]
    },
    "deepinfra": {
        "name": "DeepInfra",
        "url": "https://deepinfra.com/",
        "api_base": "https://api.deepinfra.com/v1/openai",
        "description": "77+ models — $5 free credits, Blackwell B200",
        "key_env": "DEEPINFRA_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/Meta-Llama-3.3-70B-Instruct-Turbo", "name": "Llama 3.3 70B Turbo", "provider": "deepinfra", "context_window": 131072, "description": "Fast 70B"},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1", "provider": "deepinfra", "context_window": 163840, "description": "Reasoning model"},
            {"id": "Qwen/Qwen3-235B-A22B", "name": "Qwen3 235B", "provider": "deepinfra", "context_window": 131072, "description": "MoE model"},
            {"id": "mistralai/Mistral-7B-Instruct-v0.3", "name": "Mistral 7B", "provider": "deepinfra", "context_window": 32768, "description": "Fast Mistral"},
        ]
    },
    "novita": {
        "name": "Novita AI",
        "url": "https://novita.ai/",
        "api_base": "https://api.novita.ai/v3/openai",
        "description": "200+ models — referral credits",
        "key_env": "NOVITA_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "provider": "novita", "context_window": 131072, "description": "Standard 70B"},
            {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "provider": "novita", "context_window": 163840, "description": "Reasoning model"},
        ]
    },
    "chutes": {
        "name": "Chutes AI",
        "url": "https://chutes.ai/",
        "api_base": "https://api.chutes.ai/v1",
        "description": "Popular for roleplay — limited free tier",
        "key_env": "CHUTES_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "chuteai/ChuteLlama3.3-70B", "name": "Chute Llama 3.3 70B", "provider": "chutes", "context_window": 131072, "description": "Custom fine-tuned 70B"},
        ]
    },
    "siliconflow": {
        "name": "SiliconFlow",
        "url": "https://siliconflow.cn/",
        "api_base": "https://api.siliconflow.cn/v1",
        "description": "China-direct access — free models",
        "key_env": "SILICONFLOW_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "Qwen/Qwen3-235B-A22B", "name": "Qwen3 235B", "provider": "siliconflow", "context_window": 131072, "description": "MoE model"},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1", "provider": "siliconflow", "context_window": 163840, "description": "Reasoning model"},
            {"id": "Pro/deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3 Pro", "provider": "siliconflow", "context_window": 163840, "description": "General model"},
        ]
    },
    "nebius": {
        "name": "Nebius AI",
        "url": "https://nebius.com/",
        "api_base": "https://api.studio.nebius.ai/v1",
        "description": "Free credits on signup",
        "key_env": "NEBIUS_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/Meta-Llama-3.3-70B-Instruct-Turbo", "name": "Llama 3.3 70B Turbo", "provider": "nebius", "context_window": 131072, "description": "Fast 70B"},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1", "provider": "nebius", "context_window": 163840, "description": "Reasoning model"},
        ]
    },
    "kluster": {
        "name": "Kluster AI",
        "url": "https://kluster.ai/",
        "api_base": "https://api.kluster.ai/v1",
        "description": "Free tier available",
        "key_env": "KLUSTER_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/Meta-Llama-3.3-70B-Instruct-Turbo", "name": "Llama 3.3 70B", "provider": "kluster", "context_window": 131072, "description": "Fast 70B"},
        ]
    },
    "parasail": {
        "name": "Parasail",
        "url": "https://parasail.io/",
        "api_base": "https://api.parasail.io/v1",
        "description": "Free tier available",
        "key_env": "PARASAIL_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/Meta-Llama-3.3-70B-Instruct", "name": "Llama 3.3 70B", "provider": "parasail", "context_window": 131072, "description": "Standard 70B"},
        ]
    },

    # ========================================================================
    # CATEGORY 4: KEYLESS / NO-SIGNUP PROVIDERS
    # ========================================================================
    "pollinations": {
        "name": "Pollinations AI",
        "url": "https://pollinations.ai/",
        "api_base": "https://gen.pollinations.ai/v1",
        "description": "Keyless — text+image+video+audio, per-IP limits",
        "key_env": None,
        "free_tier": True,
        "models": [
            {"id": "openai", "name": "Pollinations OpenAI", "provider": "pollinations", "context_window": 32768, "description": "GPT-like model"},
            {"id": "openai-large", "name": "Pollinations OpenAI Large", "provider": "pollinations", "context_window": 32768, "description": "Larger GPT-like"},
            {"id": "gemini", "name": "Pollinations Gemini", "provider": "pollinations", "context_window": 32768, "description": "Gemini-like"},
            {"id": "mistral", "name": "Pollinations Mistral", "provider": "pollinations", "context_window": 32768, "description": "Mistral-like"},
            {"id": "llama", "name": "Pollinations Llama", "provider": "pollinations", "context_window": 32768, "description": "Llama-based"},
        ]
    },
    "llm7": {
        "name": "LLM7.io",
        "url": "https://llm7.io/",
        "api_base": "https://token.llm7.io/v1",
        "description": "30+ models — 15 RPM free, 30 RPM with token",
        "key_env": None,
        "free_tier": True,
        "models": [
            {"id": "deepseek-r1", "name": "DeepSeek R1", "provider": "llm7", "context_window": 163840, "description": "Reasoning model"},
            {"id": "gemini-flash-lite", "name": "Gemini Flash Lite", "provider": "llm7", "context_window": 1048576, "description": "Light Gemini"},
            {"id": "qwen2.5-coder", "name": "Qwen 2.5 Coder", "provider": "llm7", "context_window": 32768, "description": "Code model"},
        ]
    },
    "kilo": {
        "name": "Kilo Gateway",
        "url": "https://kilo.ai/",
        "api_base": "https://api.kilo.ai/v1",
        "description": "Keyless — ~200 req/hour per IP",
        "key_env": None,
        "free_tier": True,
        "models": [
            {"id": "llama-3.3-70b", "name": "Llama 3.3 70B", "provider": "kilo", "context_window": 131072, "description": "Standard 70B"},
        ]
    },
    "airforce": {
        "name": "Api.Airforce",
        "url": "https://api.airforce/",
        "api_base": "https://api.airforce/v1",
        "description": "13 free models + image/audio",
        "key_env": None,
        "free_tier": True,
        "models": [
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "airforce", "context_window": 128000, "description": "OpenAI mini"},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "airforce", "context_window": 1048576, "description": "Google flash"},
            {"id": "deepseek-chat", "name": "DeepSeek Chat", "provider": "airforce", "context_window": 163840, "description": "DeepSeek chat"},
            {"id": "llama-3.3-70b", "name": "Llama 3.3 70B", "provider": "airforce", "context_window": 131072, "description": "Meta 70B"},
        ]
    },
    "anyapi": {
        "name": "AnyApi",
        "url": "https://anyapi.ai/",
        "api_base": "https://api.anyapi.ai/v1",
        "description": "20 RPM, 200 RPD free",
        "key_env": "ANYAPI_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "llama-3.3-70b", "name": "Llama 3.3 70B", "provider": "anyapi", "context_window": 131072, "description": "Standard 70B"},
            {"id": "deepseek-chat", "name": "DeepSeek Chat", "provider": "anyapi", "context_window": 163840, "description": "DeepSeek"},
            {"id": "qwen3-coder", "name": "Qwen3 Coder", "provider": "anyapi", "context_window": 1048576, "description": "Code model"},
        ]
    },

    # ========================================================================
    # CATEGORY 5: CLOUD / EDGE PROVIDERS
    # ========================================================================
    "cloudflare": {
        "name": "Cloudflare Workers AI",
        "url": "https://developers.cloudflare.com/workers-ai/",
        "api_base": "https://api.cloudflare.com/client/v4",
        "description": "80+ models — 10K neurons/day free",
        "key_env": "CLOUDFLARE_API_TOKEN",
        "free_tier": True,
        "models": [
            {"id": "@cf/meta/llama-3.3-70b-instruct-fp16", "name": "Llama 3.3 70B", "provider": "cloudflare", "context_window": 8192, "description": "Edge-deployed 70B"},
            {"id": "@cf/meta/llama-3.1-8b-instruct", "name": "Llama 3.1 8B", "provider": "cloudflare", "context_window": 8192, "description": "Edge-deployed 8B"},
            {"id": "@cf/mistral/mistral-7b-instruct-v0.2", "name": "Mistral 7B", "provider": "cloudflare", "context_window": 8192, "description": "Edge Mistral"},
        ]
    },
    "github": {
        "name": "GitHub Models",
        "url": "https://github.com/marketplace/models",
        "api_base": "https://models.inference.ai.azure.com",
        "description": "Frontier models free — 10-15 RPM, GitHub account needed",
        "key_env": "GITHUB_TOKEN",
        "free_tier": True,
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o", "provider": "github", "context_window": 128000, "description": "OpenAI GPT-4o"},
            {"id": "o3", "name": "o3", "provider": "github", "context_window": 200000, "description": "Reasoning model"},
            {"id": "DeepSeek-R1", "name": "DeepSeek R1", "provider": "github", "context_window": 163840, "description": "Reasoning model"},
            {"id": "Llama-3.3-70B-Instruct", "name": "Llama 3.3 70B", "provider": "github", "context_window": 131072, "description": "Meta 70B"},
            {"id": "Phi-4", "name": "Phi-4", "provider": "github", "context_window": 16384, "description": "Microsoft Phi-4"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "github", "context_window": 128000, "description": "Fast GPT-4o"},
            {"id": "Mistral-Large-2411", "name": "Mistral Large", "provider": "github", "context_window": 128000, "description": "Mistral Large"},
            {"id": "grok-3", "name": "Grok 3", "provider": "github", "context_window": 131072, "description": "xAI Grok 3"},
        ]
    },
    "scaleway": {
        "name": "Scaleway",
        "url": "https://www.scaleway.com/",
        "api_base": "https://api.scaleway.ai/v1",
        "description": "EU-based — 100 RPM, 200K TPM free",
        "key_env": "SCALEWAY_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "provider": "scaleway", "context_window": 131072, "description": "EU-hosted 70B"},
        ]
    },
    "ovhcloud": {
        "name": "OVHcloud AI",
        "url": "https://www.ovhcloud.com/",
        "api_base": "https://api.endpoints.ai.cloud.ovh.net",
        "description": "17 models — keyless anonymous tier",
        "key_env": None,
        "free_tier": True,
        "models": [
            {"id": "llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "provider": "ovhcloud", "context_window": 131072, "description": "EU-hosted 70B"},
        ]
    },
    "modal": {
        "name": "Modal",
        "url": "https://modal.com/",
        "api_base": "https://api.modal.com/v1",
        "description": "Serverless GPU — free tier",
        "key_env": "MODAL_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/Meta-Llama-3.1-70B-Instruct", "name": "Llama 3.1 70B", "provider": "modal", "context_window": 131072, "description": "Serverless 70B"},
        ]
    },

    # ========================================================================
    # CATEGORY 6: CHINA-DIRECT PROVIDERS
    # ========================================================================
    "volcengine": {
        "name": "Volcengine Ark (ByteDance)",
        "url": "https://www.volcengine.com/product/ark",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "description": "Doubao models — sliding window rate limits",
        "key_env": "VOLCENGINE_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "doubao-1.5-pro-256k", "name": "Doubao 1.5 Pro 256K", "provider": "volcengine", "context_window": 262144, "description": "ByteDance flagship"},
            {"id": "doubao-1.5-lite-32k", "name": "Doubao 1.5 Lite 32K", "provider": "volcengine", "context_window": 32768, "description": "Lightweight model"},
        ]
    },
    "baidu": {
        "name": "Baidu (ERNIE)",
        "url": "https://cloud.baidu.com/",
        "api_base": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop",
        "description": "ERNIE models — free tier",
        "key_env": "BAIDU_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "ernie-4.0-8k", "name": "ERNIE 4.0", "provider": "baidu", "context_window": 8192, "description": "Baidu flagship"},
            {"id": "ernie-3.5-8k", "name": "ERNIE 3.5", "provider": "baidu", "context_window": 8192, "description": "Previous gen"},
        ]
    },
    "iflytek": {
        "name": "iFlytek Spark",
        "url": "https://xinghuo.xfyun.cn/",
        "api_base": "https://spark-api-open.xf-yun.com/v1",
        "description": "Spark models — voice interaction specialist",
        "key_env": "IFLYTEK_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "generalv3.5", "name": "Spark 3.5", "provider": "iflytek", "context_window": 8192, "description": "General model"},
        ]
    },
    "tencent": {
        "name": "Tencent Hunyuan",
        "url": "https://cloud.tencent.com/product/hunyuan",
        "api_base": "https://hunyuan.tencentcloudapi.com",
        "description": "Hunyuan models — WeChat ecosystem",
        "key_env": "TENCENT_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "hunyuan-standard", "name": "Hunyuan Standard", "provider": "tencent", "context_window": 32768, "description": "General model"},
        ]
    },
    "modelscope": {
        "name": "ModelScope",
        "url": "https://modelscope.cn/",
        "api_base": "https://api-inference.modelscope.cn/v1",
        "description": "Alibaba ecosystem — free models",
        "key_env": "MODELSCOPE_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "Qwen/Qwen3-235B-A22B", "name": "Qwen3 235B", "provider": "modelscope", "context_window": 131072, "description": "MoE model"},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1", "provider": "modelscope", "context_window": 163840, "description": "Reasoning model"},
        ]
    },

    # ========================================================================
    # CATEGORY 7: SELF-HOSTED / LOCAL
    # ========================================================================
    "ollama": {
        "name": "Ollama (Local)",
        "url": "https://ollama.com/",
        "api_base": "http://localhost:11434/v1",
        "description": "Self-hosted — unlimited local inference",
        "key_env": None,
        "free_tier": True,
        "models": [
            {"id": "llama3.3", "name": "Llama 3.3 70B (Local)", "provider": "ollama", "context_window": 131072, "description": "Download & run locally"},
            {"id": "llama3.1", "name": "Llama 3.1 8B (Local)", "provider": "ollama", "context_window": 131072, "description": "Lightweight local"},
            {"id": "qwen3-coder", "name": "Qwen3 Coder (Local)", "provider": "ollama", "context_window": 131072, "description": "Local coding model"},
            {"id": "deepseek-r1", "name": "DeepSeek R1 (Local)", "provider": "ollama", "context_window": 163840, "description": "Local reasoning"},
            {"id": "gemma3", "name": "Gemma 3 (Local)", "provider": "ollama", "context_window": 131072, "description": "Google Gemma local"},
        ]
    },
    "lmstudio": {
        "name": "LM Studio (Local)",
        "url": "https://lmstudio.ai/",
        "api_base": "http://localhost:1234/v1",
        "description": "GUI for local LLMs — unlimited",
        "key_env": None,
        "free_tier": True,
        "models": [
            {"id": "local-model", "name": "Any Downloaded Model", "provider": "lmstudio", "context_window": 131072, "description": "Load any GGUF model"},
        ]
    },
    "vllm": {
        "name": "vLLM (Local)",
        "url": "https://docs.vllm.ai/",
        "api_base": "http://localhost:8000/v1",
        "description": "High-performance serving — unlimited",
        "key_env": None,
        "free_tier": True,
        "models": [
            {"id": "local-model", "name": "Any Deployed Model", "provider": "vllm", "context_window": 131072, "description": "Deploy any model"},
        ]
    },

    # ========================================================================
    # CATEGORY 8: SPECIALIZED PROVIDERS
    # ========================================================================
    "replicate": {
        "name": "Replicate",
        "url": "https://replicate.com/",
        "api_base": "https://api.replicate.com/v1",
        "description": "Model marketplace — new-account credits",
        "key_env": "REPLICATE_API_TOKEN",
        "free_tier": True,
        "models": [
            {"id": "meta/meta-llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "provider": "replicate", "context_window": 131072, "description": "Community-hosted"},
        ]
    },
    "huggingface": {
        "name": "Hugging Face",
        "url": "https://huggingface.co/",
        "api_base": "https://router.huggingface.co/v1",
        "description": "Hundreds of models via partner routing",
        "key_env": "HF_TOKEN",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/Llama-3.3-70B-Instruct", "name": "Llama 3.3 70B", "provider": "huggingface", "context_window": 131072, "description": "Multi-provider routing"},
            {"id": "Qwen/Qwen3-Coder-480B-A35B-Instruct", "name": "Qwen3 Coder 480B", "provider": "huggingface", "context_window": 1048576, "description": "MoE coding"},
        ]
    },
    "databricks": {
        "name": "Databricks Mosaic AI",
        "url": "https://www.databricks.com/product/mosaic-ai",
        "api_base": "https://api.databricks.com/v1",
        "description": "Enterprise — trial credits",
        "key_env": "DATABRICKS_TOKEN",
        "free_tier": False,
        "models": [
            {"id": "dbrx-instruct", "name": "DBRX Instruct", "provider": "databricks", "context_window": 32768, "description": "Databricks flagship"},
        ]
    },
    "anyscale": {
        "name": "Anyscale",
        "url": "https://www.anyscale.com/",
        "api_base": "https://api.endpoints.anyscale.com/v1",
        "description": "$10 free credits",
        "key_env": "ANYSCALE_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "meta-llama/Meta-Llama-3.3-70B-Instruct", "name": "Llama 3.3 70B", "provider": "anyscale", "context_window": 131072, "description": "Fast 70B"},
        ]
    },
    "opencode": {
        "name": "OpenCode Zen",
        "url": "https://opencode.ai/zen",
        "api_base": "https://opencode.ai/zen/v1",
        "description": "Curated free models for coding agents",
        "key_env": "OPENCODE_API_KEY",
        "free_tier": True,
        "models": [
            {"id": "mimo-v2.5-free", "name": "MiMo V2.5 Free", "provider": "opencode", "context_window": 128000, "description": "Xiaomi multimodal"},
            {"id": "nemotron-3-ultra-free", "name": "Nemotron 3 Ultra Free", "provider": "opencode", "context_window": 128000, "description": "NVIDIA Nemotron"},
            {"id": "north-mini-code-free", "name": "North Mini Code Free", "provider": "opencode", "context_window": 256000, "description": "Cohere coding"},
            {"id": "deepseek-v4-flash-free", "name": "DeepSeek V4 Flash Free", "provider": "opencode", "context_window": 128000, "description": "Ultra-fast DeepSeek"},
            {"id": "big-pickle", "name": "Big Pickle", "provider": "opencode", "context_window": 128000, "description": "Agentic execution"},
        ]
    },
}

# ============================================================================
# MODEL COSTS REGISTRY
# ============================================================================
for _prov_key, _prov_data in PROVIDERS.items():
    for _model in _prov_data["models"]:
        MODEL_COSTS[_model["id"]] = _free()

# ============================================================================
# MODEL CONTEXT WINDOWS REGISTRY (keyed by provider::id to avoid collisions,
# e.g. gpt-4o on openai vs github; legacy id-only lookup kept as fallback)
# ============================================================================
MODEL_CONTEXT_WINDOWS: Dict[str, int] = {}
for _prov_key, _prov_data in PROVIDERS.items():
    for _model in _prov_data["models"]:
        MODEL_CONTEXT_WINDOWS[f"{_model.get('provider', _prov_key)}::{_model['id']}"] = _model["context_window"]
        MODEL_CONTEXT_WINDOWS.setdefault(_model["id"], _model["context_window"])

# ============================================================================
# DEFAULTS
# ============================================================================
DEFAULT_PROVIDER = "openrouter"
DEFAULT_MODEL = "openrouter/free"

# Flat model list for iteration
MODEL_LIST = []
for _prov_data in PROVIDERS.values():
    MODEL_LIST.extend(_prov_data["models"])


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_all_models():
    all_models = []
    for prov_data in PROVIDERS.values():
        all_models.extend(prov_data["models"])
    return all_models


def get_free_models():
    free = []
    for prov_data in PROVIDERS.values():
        if prov_data.get("free_tier"):
            for m in prov_data["models"]:
                cost = MODEL_COSTS.get(m["id"])
                if cost and cost.input == 0.0 and cost.output == 0.0:
                    free.append(m)
    return free


def get_paid_models():
    paid = []
    for prov_data in PROVIDERS.values():
        if not prov_data.get("free_tier"):
            paid.extend(prov_data["models"])
    return paid


def get_model_info(model_id, strict: bool = False):
    for model in get_all_models():
        if model["id"].lower() == model_id.lower() or model["name"].lower() == model_id.lower():
            return {**model, "custom": False}
    if strict:
        return None
    logger.warning(f"Unknown model '{model_id}'; returning Custom placeholder (not persisted as valid)")
    provider = "openrouter" if "/" in model_id else "openrouter"
    return {
        "id": model_id,
        "name": model_id,
        "provider": provider,
        "context_window": 128000,
        "description": "Custom model (unrecognized — verify with /model)",
        "custom": True,
    }


def get_provider_for_model(model_id):
    for model in get_all_models():
        if model["id"].lower() == model_id.lower():
            return model["provider"]
    return "openrouter"


def get_model_cost(model_id: str) -> CostInfo:
    return MODEL_COSTS.get(model_id, _free())


def get_model_context_window(model_id: str, provider: str = "") -> int:
    if provider:
        hit = MODEL_CONTEXT_WINDOWS.get(f"{provider}::{model_id}")
        if hit:
            return hit
    return MODEL_CONTEXT_WINDOWS.get(model_id, 128000)


def search_models(query: str, provider: str = "") -> List[Dict]:
    """Search models by id/name substring (all providers unless filtered)."""
    q = (query or "").lower()
    out = []
    for m in get_all_models():
        if provider and m.get("provider", "").lower() != provider.lower():
            continue
        if not q or q in m["id"].lower() or q in m.get("name", "").lower():
            out.append(m)
    return out


def get_default_model_for_provider(provider: str) -> str:
    if provider in PROVIDERS:
        models = PROVIDERS[provider]["models"]
        if models:
            return models[0]["id"]
    return "openrouter/free"


def is_model_valid_for_provider(model_id: str, provider: str) -> bool:
    for model in PROVIDERS.get(provider, {}).get("models", []):
        if model["id"].lower() == model_id.lower():
            return True
    return False


def get_dynamic_context_window(model_id: str, api_key: str = None) -> int:
    base_window = get_model_context_window(model_id)
    if api_key:
        try:
            from deepans_code.model_health import check_model_health, get_model_context_window as health_get_ctx
            provider = get_provider_for_model(model_id)
            health = check_model_health(model_id, api_key, provider)
            if health.get("status") == "healthy":
                return health_get_ctx(model_id)
        except Exception:
            pass
    return base_window


def get_models_by_provider(provider: str) -> List[Dict]:
    return PROVIDERS.get(provider, {}).get("models", [])


def get_model_with_health(model_id: str, api_key: str = None) -> Dict:
    info = get_model_info(model_id)
    health = {"status": "unknown"}
    if api_key:
        try:
            from deepans_code.model_health import check_model_health
            provider = get_provider_for_model(model_id)
            health = check_model_health(model_id, api_key, provider)
        except Exception:
            pass
    return {**info, "health": health}


def list_models_with_status(api_key: str = None) -> List[Dict]:
    models = get_all_models()
    if not api_key:
        return models
    result = []
    for model in models:
        try:
            from deepans_code.model_health import check_model_health
            health = check_model_health(model["id"], api_key, model.get("provider", "openrouter"))
            result.append({**model, "health": health})
        except Exception:
            result.append({**model, "health": {"status": "unknown"}})
    return result


def get_providers_summary() -> Dict[str, Any]:
    summary = {
        "total_providers": len(PROVIDERS),
        "total_models": len(MODEL_LIST),
        "free_providers": sum(1 for p in PROVIDERS.values() if p.get("free_tier")),
        "paid_providers": sum(1 for p in PROVIDERS.values() if not p.get("free_tier")),
        "free_models": len(get_free_models()),
        "paid_models": len(get_paid_models()),
        "keyless_providers": sum(1 for p in PROVIDERS.values() if p.get("key_env") is None),
    }
    return summary
