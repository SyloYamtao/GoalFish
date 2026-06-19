"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config
from ..llm_json_mode import (
    build_json_repair_messages,
    json_object_response_format,
    prepare_json_object_messages,
)
from ..llm_protocol import (
    chat_protocol_requires_api_key,
    is_ollama_chat_protocol,
    llm_api_key_or_dummy,
    normalize_chat_protocol,
    unsupported_chat_protocol_error,
)
from .llm_logging import create_logged_ollama_chat_completion


class LLMClient:
    """LLM客户端"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        chat_protocol: Optional[str] = None,
    ):
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        protocol_source = chat_protocol
        if protocol_source is None:
            protocol_source = Config.LLM_CHAT_PROTOCOL if base_url is None else "auto"
        self.chat_protocol = normalize_chat_protocol(protocol_source)
        protocol_error = unsupported_chat_protocol_error(self.chat_protocol, "LLM_CHAT_PROTOCOL")
        if protocol_error:
            raise NotImplementedError(protocol_error)

        self.api_key = llm_api_key_or_dummy(
            api_key or Config.LLM_API_KEY,
            self.base_url,
            self.chat_protocol,
        )
        self._use_ollama_native = is_ollama_chat_protocol(self.chat_protocol, self.base_url)
        
        if not self.api_key and chat_protocol_requires_api_key(self.chat_protocol, self.base_url):
            raise ValueError("LLM_API_KEY 未配置")
        
        self.client = None
        if not self._use_ollama_native:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（如JSON模式）
            
        Returns:
            模型响应文本
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if response_format:
            kwargs["response_format"] = response_format

        if self._use_ollama_native:
            response = create_logged_ollama_chat_completion(self.base_url, kwargs)
        else:
            response = self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content or ""
        if not content.strip():
            reasoning_content = getattr(choice.message, "reasoning_content", None)
            raise ValueError(
                "LLM返回内容为空"
                f"（finish_reason={choice.finish_reason}, "
                f"reasoning_tokens={getattr(getattr(response.usage, 'completion_tokens_details', None), 'reasoning_tokens', None)}, "
                f"reasoning_content_length={len(reasoning_content or '')}）"
            )
        # 部分模型（如MiniMax M2.5）会在content中包含<think>思考内容，需要移除
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            解析后的JSON对象
        """
        request_messages = prepare_json_object_messages(messages)
        response_format = json_object_response_format()
        response = self.chat(
            messages=request_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

        try:
            return _parse_json_object_response(response)
        except (json.JSONDecodeError, ValueError) as parse_error:
            if response_format:
                cleaned_response = _clean_json_response(response)
                raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}") from parse_error

            repair_response = self.chat(
                messages=build_json_repair_messages(
                    original_messages=messages,
                    invalid_content=response,
                    parse_error=parse_error,
                ),
                temperature=0.0,
                max_tokens=max_tokens,
                response_format=None,
            )
            try:
                return _parse_json_object_response(repair_response)
            except (json.JSONDecodeError, ValueError) as repair_error:
                cleaned_response = _clean_json_response(repair_response)
                raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}") from repair_error


def _parse_json_object_response(response: str) -> Dict[str, Any]:
    cleaned_response = _clean_json_response(response)
    result = json.loads(cleaned_response)
    if not isinstance(result, dict):
        raise ValueError(f"LLM返回的JSON不是object: {cleaned_response}")
    return result


def _clean_json_response(response: str) -> str:
    cleaned_response = response.strip()
    cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
    cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
    return cleaned_response.strip()
